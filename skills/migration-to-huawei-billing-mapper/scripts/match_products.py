# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Match source-cloud products to Huawei Cloud products using CSV mapping.

Loads the CSV as rows, then for each source-cloud product from the billing
table, searches the CSV row by row: if the billing product's keywords match
the source-product keywords in that CSV row, the row's Huawei Cloud product
is the result.
"""

import csv
import argparse
import re
import sys
from pathlib import Path


SOURCE_PRODUCT_COL = "Source Product"
SOURCE_SPEC_COL = "Source Spec"
HUAWEI_PRODUCT_COL = "Huawei Cloud Product"
ROW_NUM_COL = "#"


def load_csv_rows(csv_path: Path) -> list[dict]:
    """
    Load CSV as a list of rows.
    Each row: {huawei: [str, ...], source: [str, ...]}

    CSV format: Huawei Cloud Product,Source Product
    Both columns can have multiple products separated by newlines (quoted).
    """
    rows: list[dict] = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.reader(f)
        for row_num, row in enumerate(reader):
            if len(row) < 2:
                continue
            huawei = row[0].strip()
            source_raw = row[1].strip()
            if row_num == 0 and huawei == HUAWEI_PRODUCT_COL and source_raw == SOURCE_PRODUCT_COL:
                continue
            if not huawei or not source_raw:
                continue
            huawei_products = [p.strip() for p in huawei.split("\n") if p.strip()]
            source_products = [p.strip() for p in source_raw.split("\n") if p.strip()]
            if huawei_products and source_products:
                rows.append({"huawei": huawei_products, "source": source_products})
    return rows


# Words to ignore when comparing product names
_STOP_WORDS = {
    "amazon", "aws", "for", "and", "the", "with", "service", "services",
    "google", "gcp", "oracle", "oci", "cloud", "platform",
    "of", "in", "to", "a", "an", "or", "on", "at", "by", "per", "is",
    "running", "using", "first", "standard",
}

# Special acronyms — product codes that should be treated as keywords
# even though they're short. e.g., "S3", "EC2", "RDS", "SES", "SQS", etc.
_PRODUCT_CODES = {
    "s3", "ec2", "ecs", "eks", "ebs", "efs", "rds", "dms", "sqs", "sns",
    "ses", "vpc", "elb", "alb", "nlb", "nat", "vpn", "cdn", "dns", "waf",
    "iam", "kms", "ecr", "cbr", "obs", "evs", "dcs", "ccm", "dew", "cts",
    "ces", "lts", "aom", "apm", "dds", "css", "dis", "dli", "ges", "mrs",
    "cce", "swr", "cae", "smn", "dws", "bms", "gpu", "gce", "gke", "gcs",
    "sql", "oke", "ocpu", "ecpu", "ocir", "oci", "adb",
}

# Broad product-family words are still useful for fallback matching, but they
# should contribute less than product-identifying terms such as "aurora" or "dynamodb".
_WEAK_KEYWORDS = {
    "storage", "compute", "database", "gateway", "server", "servers",
    "instance", "instances", "cluster", "clusters", "node", "nodes",
    "data", "disk", "volume", "volumes", "network", "cache",
}


def _keywords(name: str) -> set[str]:
    """
    Extract meaningful keywords from a product name.

    - Lowercase and extract all alphanumeric tokens
    - Keep product codes (S3, EC2, etc.) regardless of length
    - For other words: keep if length > 2 and not a stop word
    - Also keep words inside parentheses (acronyms)
    """
    tokens = re.findall(r'[a-z0-9]+', name.lower())
    keywords: set[str] = set()
    for t in tokens:
        if t in _STOP_WORDS:
            continue
        if t in _PRODUCT_CODES:
            keywords.add(t)
        elif len(t) > 2:
            keywords.add(t)
    return keywords


def _keyword_weight(token: str) -> float:
    """
    Weight broad family words lower than product-identifying terms.

    This prevents billing sub-items like "Aurora Storage" from being pulled
    toward unrelated "Storage Gateway" style mappings purely due to the shared
    generic word "storage".
    """
    if token in _PRODUCT_CODES:
        return 1.5
    if token in _WEAK_KEYWORDS:
        return 0.25
    return 1.0


def match_product(
    source_name: str, csv_rows: list[dict], source_spec: str = ""
) -> list[str]:
    """
    Search CSV rows for a matching source-cloud product.

    Strategy: for each CSV row, compute keyword overlap between
    the billing source-cloud product name and the row's source-product names.
    Best overlap (most shared keywords) wins.

    When multiple rows tie, disambiguate using source_spec if available.

    Returns: list of Huawei Cloud product names, or empty list.
    """
    input_kw = _keywords(source_name)
    if not input_kw:
        return []

    # Phase 1: try to find rows with keyword overlap
    candidates: list[tuple[float, int, int, list[str]]] = []
    # Tuple shape:
    # (weighted_overlap, strong_overlap_count, -row_kw_count, hw_products)
    for row in csv_rows:
        # Collect all keywords from all source product names in this CSV row
        row_kw: set[str] = set()
        for source_entry in row["source"]:
            row_kw |= _keywords(source_entry)

        shared_kw = input_kw & row_kw
        weighted_overlap = sum(_keyword_weight(token) for token in shared_kw)
        strong_overlap_count = sum(
            1 for token in shared_kw if _keyword_weight(token) >= 1.0
        )
        if weighted_overlap > 0:
            # Store negative keyword count: fewer keywords = more specific match
            candidates.append(
                (weighted_overlap, strong_overlap_count, -len(row_kw), row["huawei"])
            )

    if not candidates:
        return []

    # Sort by weighted overlap first, then prefer matches that share more
    # product-identifying terms, then break ties by specificity.
    candidates.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    best_key = candidates[0][:3]

    # Keep only candidates that are truly tied after all ranking keys.
    tied = [c for c in candidates if c[:3] == best_key]

    # Flatten all huawei products from all tied rows
    all_hw: list[str] = []
    for _, _, _, hw_list in tied:
        for hw in hw_list:
            if hw not in all_hw:
                all_hw.append(hw)

    # If only one candidate row AND it only has one product, return it
    if len(tied) == 1 and len(all_hw) == 1:
        return tied[0][3]

    # --- Disambiguation: use spec to pick among all candidates ---
    filtered = _disambiguate_by_spec(all_hw, source_name, source_spec)
    return filtered


# Rules for disambiguating between tied Huawei Cloud products based on
# source-cloud spec / instance type.
_SPEC_DISAMBIGUATION: dict[str, dict] = {
    # EC2: virtual machine → ECS, bare metal → BMS
    ("弹性云服务器ECS", "裸金属服务器BMS"): {
        "bare_metal_keywords": ["metal", "bare", ".metal"],
        "bare_metal_product": "裸金属服务器BMS",
        "default_product": "弹性云服务器ECS",
    },
    # SQS → RocketMQ (closest to AWS SQS semantics)
    ("分布式消息服务Kafka版", "分布式消息服务RocketMQ版"): {
        "right_keywords": ["queue", "sqs", "standard"],
        "right_product": "分布式消息服务RocketMQ版",
        "default_product": "分布式消息服务DMS",
    },
    # CloudWatch: logs-related → LTS, metrics/alarms → CES
    ("云监控服务 CES", "云日志服务LTS"): {
        "left_keywords": ["metric", "alarm", "dashboard"],
        "left_product": "云监控服务 CES",
        "right_keywords": ["log", "logs", "logging", "日志"],
        "right_product": "云日志服务LTS",
        "default_product": "云监控服务 CES",
    },
}


def _disambiguate_by_spec(
    hw_products: list[str], source_name: str, source_spec: str
) -> list[str]:
    """
    When multiple Huawei Cloud products could match, use the source spec
    to pick the best one. Rules defined in _SPEC_DISAMBIGUATION.
    """
    if not source_spec or len(hw_products) <= 1:
        return hw_products

    spec_lower = source_spec.lower()

    # Check each disambiguation rule
    for (a, b), rule in _SPEC_DISAMBIGUATION.items():
        if a in hw_products and b in hw_products:
            # Bare metal check (a=ECS, b=BMS)
            if "bare_metal_keywords" in rule:
                for kw in rule["bare_metal_keywords"]:
                    if kw in spec_lower:
                        return [rule["bare_metal_product"]]
                return [rule["default_product"]]

            # Keyword-based check (e.g. CES vs LTS, Kafka vs RocketMQ)
            if "left_keywords" in rule or "right_keywords" in rule:
                for kw in rule.get("left_keywords", []):
                    if kw in spec_lower:
                        return [rule["left_product"]]
                for kw in rule.get("right_keywords", []):
                    if kw in spec_lower:
                        return [rule["right_product"]]
                return [rule.get("default_product", hw_products[0])]

    # No disambiguation rule matched — pick first (CSV order priority)
    return [hw_products[0]]


# --- Markdown table parsing and writing (unchanged from original) ---

def parse_md_tables(md_path: Path) -> list[dict]:
    """Parse Markdown tables from billing_categorized.md."""
    rows = []
    with open(md_path, encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    i = 0
    current_headers: list[str] = []
    in_table = False

    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and "---" not in line and not in_table:
            headers = [h.strip() for h in line.split("|")[1:-1]]
            if i + 1 < len(lines) and re.match(
                r"^\|[\s\-:|]+\|$", lines[i + 1].strip()
            ):
                current_headers = headers
                in_table = True
                i += 2
                continue
        elif in_table and line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) == len(current_headers):
                row_dict = dict(zip(current_headers, cells))
                rows.append(row_dict)
        elif in_table and (not line.startswith("|") or not line.strip()):
            in_table = False
            current_headers = []
        i += 1

    return rows


def _require_expected_headers(headers: list[str]) -> None:
    required = {ROW_NUM_COL, SOURCE_PRODUCT_COL, SOURCE_SPEC_COL}
    missing = [name for name in required if name not in headers]
    if missing:
        raise ValueError(
            "Missing required table headers: " + ", ".join(missing)
        )


def write_matched_md(input_path: Path, output_path: Path, rows: list[dict]):
    """Rewrite the categorized MD with a new Huawei Cloud Product column."""
    with open(input_path, encoding="utf-8") as f:
        content = f.read()

    match_lookup: dict[tuple[str, str, str], str] = {}
    if rows:
        _require_expected_headers(list(rows[0].keys()))

    for row in rows:
        hw = row.get(HUAWEI_PRODUCT_COL, "")
        key = (
            row.get(ROW_NUM_COL, ""),
            row.get(SOURCE_PRODUCT_COL, ""),
            row.get(SOURCE_SPEC_COL, ""),
        )
        match_lookup[key] = hw

    lines = content.split("\n")
    out_lines = []
    i = 0
    current_headers: list[str] = []
    in_table = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("|") and "---" not in stripped and not in_table:
            headers = [h.strip() for h in stripped.split("|")[1:-1]]
            if i + 1 < len(lines) and re.match(
                r"^\|[\s\-:|]+\|$", lines[i + 1].strip()
            ):
                new_headers = headers + ["Huawei Cloud Product"]
                out_lines.append("| " + " | ".join(new_headers) + " |")
                sep_count = len(new_headers)
                out_lines.append("|" + "|".join(["------"] * sep_count) + "|")
                current_headers = headers
                in_table = True
                i += 1
                continue
        elif in_table and re.match(r"^\|[\s\-:|]+\|$", stripped):
            i += 1
            continue
        elif in_table and stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if len(cells) == len(current_headers):
                row_dict = dict(zip(current_headers, cells))
                _require_expected_headers(list(row_dict.keys()))
                key = (
                    row_dict.get(ROW_NUM_COL, ""),
                    row_dict.get(SOURCE_PRODUCT_COL, ""),
                    row_dict.get(SOURCE_SPEC_COL, ""),
                )
                hw_match = match_lookup.get(key, "")
                new_cells = cells + [hw_match]
                out_lines.append("| " + " | ".join(new_cells) + " |")
                i += 1
                continue
            else:
                in_table = False
        elif in_table and not (stripped.startswith("|") and stripped):
            in_table = False
            current_headers = []

        out_lines.append(line)
        i += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines))


def main():
    parser = argparse.ArgumentParser(
        description="Match source-cloud products to Huawei Cloud products"
    )
    parser.add_argument(
        "--input", required=True, type=Path, help="billing_categorized.md"
    )
    parser.add_argument(
        "--csv", required=True, type=Path, help="source-to-hwc mapping CSV"
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Output billing_matched.md"
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    if not args.csv.exists():
        print(f"Error: CSV file not found: {args.csv}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading CSV from {args.csv}...")
    csv_rows = load_csv_rows(args.csv)
    print(f"  Loaded {len(csv_rows)} mapping rows")

    print(f"Parsing tables from {args.input}...")
    rows = parse_md_tables(args.input)
    print(f"  Found {len(rows)} resource rows")

    if rows:
        _require_expected_headers(list(rows[0].keys()))

    matched = 0
    for row in rows:
        source_product = row.get(SOURCE_PRODUCT_COL, "")
        source_spec = row.get(SOURCE_SPEC_COL, "")
        hw_products = match_product(source_product, csv_rows, source_spec)
        row[HUAWEI_PRODUCT_COL] = "<br>".join(hw_products) if hw_products else ""
        if hw_products:
            matched += 1
            print(f"  OK  {source_product} → {', '.join(hw_products)}")
        else:
            print(f"  --  {source_product} → (no match)")

    print(f"Matched: {matched}/{len(rows)}")
    print(f"Writing {args.output}...")
    write_matched_md(args.input, args.output, rows)
    print("Done.")


if __name__ == "__main__":
    main()
