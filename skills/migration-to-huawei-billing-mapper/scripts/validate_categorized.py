# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Validate output/billing_categorized.md before Step 4.

This is a blocking validator for Step 3. It checks the fixed schema and
rule-shaped constraints from Step 2.2, then prints a PASS/FAIL checklist.
Exit code is non-zero when any blocking issue is found.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REQUIRED_HEADERS = [
    "#",
    "Category",
    "Source Product",
    "Source Spec",
    "Monthly (USD)",
    "Qty",
    "Source Est. Resource Count",
    "Region",
    "HWC Target Region",
    "Notes",
]

HOUR_KEYWORDS = (
    "hr",
    "hrs",
    "hour",
    "hours",
    "ocpu hour",
    "ecpu hour",
)

TRAFFIC_KEYWORDS = (
    "data transfer",
    "nat gateway data processed",
    "processed by nat",
    "data processed by nat gateway",
    "nat processed",
    "数据传输",
    "nat 网关流量",
    "nat网关流量",
    "nat 网关已处理流量",
    "nat网关已处理流量",
)

OUTBOUND_KEYWORDS = (
    "outbound",
    "egress",
    "data transfer out",
    "出站",
)

CROSS_REGION_KEYWORDS = (
    "cross-region",
    "cross region",
    "inter-region",
    "inter region",
    "regional data transfer",
    "跨区域",
    "区域间",
)

SEPARATORS = ("+", ";", "<br>", "\n")


@dataclass
class TableRow:
    section: str
    headers: list[str]
    cells: list[str]
    line_no: int

    def get(self, header: str) -> str:
        return self.cells[self.headers.index(header)].strip()


@dataclass
class ValidationResult:
    name: str
    passed: bool
    details: list[str]


def parse_document(md_path: Path) -> list[TableRow]:
    lines = md_path.read_text(encoding="utf-8").splitlines()
    rows: list[TableRow] = []
    current_section = ""
    i = 0

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        if line.startswith("> "):
            i += 1
            continue

        if line.startswith("## "):
            current_section = line[3:].strip()
            i += 1
            continue

        if (
            line.startswith("|")
            and "---" not in line
            and i + 1 < len(lines)
            and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip())
        ):
            headers = [cell.strip() for cell in line.split("|")[1:-1]]
            i += 2
            while i < len(lines):
                row_line = lines[i].strip()
                if not (row_line.startswith("|") and row_line.endswith("|")):
                    break
                cells = [cell.strip() for cell in row_line.split("|")[1:-1]]
                if len(cells) == len(headers):
                    rows.append(
                        TableRow(
                            section=current_section,
                            headers=headers,
                            cells=cells,
                            line_no=i + 1,
                        )
                    )
                i += 1
            continue

        i += 1

    return rows


def _is_single_region(value: str) -> bool:
    if not value:
        return False
    return not any(token in value for token in SEPARATORS)


def _is_non_hourly(qty: str) -> bool:
    qty_lower = qty.lower()
    return not any(token in qty_lower for token in HOUR_KEYWORDS)


def _looks_like_traffic(product: str, spec: str) -> bool:
    product_lower = product.lower()
    spec_lower = spec.lower()

    # CDN and other network products may use a bare "data transfer" spec label;
    # that phrase alone should not trigger Data Transfer normalization.
    product_has_traffic_label = any(
        keyword in product_lower for keyword in TRAFFIC_KEYWORDS
    )
    spec_has_other_traffic_label = any(
        keyword in spec_lower
        for keyword in TRAFFIC_KEYWORDS
        if keyword != "data transfer"
    )
    return product_has_traffic_label or spec_has_other_traffic_label


def _contains_any(value: str, keywords: tuple[str, ...]) -> bool:
    value_lower = value.lower()
    return any(keyword in value_lower for keyword in keywords)


def _is_data_transfer(row: TableRow) -> bool:
    return row.get("Source Product").strip().lower() == "data transfer"


def _is_nat_related(row: TableRow) -> bool:
    haystack = f"{row.get('Source Product')} {row.get('Source Spec')}".lower()
    return bool(re.search(r"\bnat\b", haystack)) or any(
        keyword in haystack for keyword in ("nat 网关", "nat网关")
    )


def _is_nat_transfer(row: TableRow) -> bool:
    if not _is_data_transfer(row):
        return False
    haystack = f"{row.get('Source Spec')} {row.get('Notes')}".lower()
    return bool(re.search(r"\bnat\b", haystack)) or any(
        keyword in haystack for keyword in ("nat 网关", "nat网关")
    )


def validate_headers(rows: list[TableRow]) -> ValidationResult:
    failures = []
    for row in rows:
        if row.headers != REQUIRED_HEADERS:
            failures.append(
                f"line {row.line_no}: headers must be exactly {REQUIRED_HEADERS}"
            )
            break
    return ValidationResult("Fixed Table Schema", not failures, failures)


def validate_regions(rows: list[TableRow]) -> ValidationResult:
    failures = []
    for row in rows:
        region = row.get("Region")
        target = row.get("HWC Target Region")
        if not _is_single_region(region):
            failures.append(
                f"line {row.line_no}: Region must contain exactly one source region"
            )
        if not _is_single_region(target):
            failures.append(
                f"line {row.line_no}: HWC Target Region must contain exactly one region"
            )
    return ValidationResult("Single-Region Rows", not failures, failures)


def validate_duplicates(rows: list[TableRow]) -> ValidationResult:
    seen: dict[tuple[str, str, str], int] = {}
    failures = []
    for row in rows:
        key = (
            row.get("Source Product"),
            row.get("Source Spec"),
            row.get("Region"),
        )
        if key in seen:
            failures.append(
                "duplicate tuple "
                f"{key!r} at line {seen[key]} and line {row.line_no}"
            )
        else:
            seen[key] = row.line_no
    return ValidationResult("Merged Rows By Product+Spec+Region", not failures, failures)


def validate_non_empty_required_cells(rows: list[TableRow]) -> ValidationResult:
    failures = []
    required = [
        "#",
        "Category",
        "Source Product",
        "Source Spec",
        "Monthly (USD)",
        "Qty",
        "Source Est. Resource Count",
        "Region",
        "HWC Target Region",
    ]
    for row in rows:
        for header in required:
            if not row.get(header):
                failures.append(f"line {row.line_no}: `{header}` must not be empty")
    return ValidationResult("Required Cell Presence", not failures, failures)


def validate_resource_count(rows: list[TableRow]) -> ValidationResult:
    failures = []
    for row in rows:
        qty = row.get("Qty")
        count = row.get("Source Est. Resource Count")
        if _is_non_hourly(qty) and count != "—":
            failures.append(
                f"line {row.line_no}: non-hourly Qty must use `—` in Source Est. Resource Count"
            )
    return ValidationResult("Resource Count Basis", not failures, failures)


def validate_category_vs_section(rows: list[TableRow]) -> ValidationResult:
    failures = []
    section_categories: dict[str, str] = {}
    for row in rows:
        if not row.section:
            failures.append(f"line {row.line_no}: row is not under a category section")
            continue
        category = row.get("Category")
        if row.section not in section_categories:
            section_categories[row.section] = category
            continue
        if section_categories[row.section] != category:
            failures.append(
                f"line {row.line_no}: Category `{category}` "
                f"must stay consistent within section `{row.section}` "
                f"(expected `{section_categories[row.section]}`)"
            )
    return ValidationResult(
        "Category Column Consistent Within Section", not failures, failures
    )


def validate_traffic_normalization(rows: list[TableRow]) -> ValidationResult:
    failures = []
    for row in rows:
        product = row.get("Source Product")
        spec = row.get("Source Spec")
        if _looks_like_traffic(product, spec) and product != "Data Transfer":
            failures.append(
                f"line {row.line_no}: supported traffic item (`Data Transfer` or "
                f"`NAT processed`) should be normalized to "
                "`Source Product = Data Transfer`"
            )
    return ValidationResult("Traffic Normalization", not failures, failures)


def validate_data_transfer_consolidation(rows: list[TableRow]) -> ValidationResult:
    failures = []
    transfer_scope_rows = []
    for row in rows:
        product_and_spec = f"{row.get('Source Product')} {row.get('Source Spec')}"
        is_network_transfer_detail = (
            row.get("Category").strip().lower() == "network"
            and (
                _contains_any(product_and_spec, OUTBOUND_KEYWORDS)
                or _contains_any(product_and_spec, CROSS_REGION_KEYWORDS)
            )
        )
        if _is_data_transfer(row) or _is_nat_related(row) or is_network_transfer_detail:
            transfer_scope_rows.append(row)

    if not transfer_scope_rows:
        return ValidationResult("Data Transfer Consolidation", True, [])

    regions = sorted({row.get("Region") for row in transfer_scope_rows})
    for region in regions:
        region_rows = [row for row in rows if row.get("Region") == region]
        data_transfer_rows = [row for row in region_rows if _is_data_transfer(row)]
        nat_present = any(_is_nat_related(row) for row in region_rows)
        nat_transfer_rows = [
            row for row in data_transfer_rows if _is_nat_transfer(row)
        ]
        ordinary_transfer_rows = [
            row for row in data_transfer_rows if not _is_nat_transfer(row)
        ]

        separate_detail_rows = []
        for row in region_rows:
            if row.get("Category").strip().lower() != "network":
                continue
            product_and_spec = f"{row.get('Source Product')} {row.get('Source Spec')}"
            has_transfer_detail = _contains_any(
                product_and_spec, OUTBOUND_KEYWORDS
            ) or _contains_any(product_and_spec, CROSS_REGION_KEYWORDS)
            if has_transfer_detail and not _is_data_transfer(row):
                separate_detail_rows.append(row)

        if len(ordinary_transfer_rows) != 1:
            lines = (
                ", ".join(str(row.line_no) for row in ordinary_transfer_rows)
                or "none"
            )
            failures.append(
                f"region `{region}`: non-NAT transfer charges must be consolidated "
                "into exactly one `Data Transfer` row; "
                f"found {len(ordinary_transfer_rows)} at lines {lines}"
            )

        expected_nat_rows = 1 if nat_present else 0
        if len(nat_transfer_rows) != expected_nat_rows:
            lines = (
                ", ".join(str(row.line_no) for row in nat_transfer_rows) or "none"
            )
            failures.append(
                f"region `{region}`: expected {expected_nat_rows} NAT processed "
                "`Data Transfer` row(s) based on NAT presence; "
                f"found {len(nat_transfer_rows)} at lines {lines}"
            )

        expected_total = 2 if nat_present else 1
        if len(data_transfer_rows) != expected_total:
            expected_shape = "ordinary + NAT processed" if nat_present else "ordinary only"
            failures.append(
                f"region `{region}`: expected {expected_total} total `Data Transfer` "
                f"row(s) ({expected_shape}); "
                f"found {len(data_transfer_rows)}"
            )

        for ordinary_row in ordinary_transfer_rows:
            spec = ordinary_row.get("Source Spec")
            if _contains_any(spec, OUTBOUND_KEYWORDS) or _contains_any(
                spec, CROSS_REGION_KEYWORDS
            ):
                failures.append(
                    f"line {ordinary_row.line_no} (region `{region}`): outbound and "
                    "cross-region details belong in `Notes`, not `Source Spec`"
                )

        for row in separate_detail_rows:
            failures.append(
                f"line {row.line_no} (region `{region}`): outbound or cross-region "
                "transfer must be folded into the ordinary `Data Transfer` row"
            )

    return ValidationResult("Data Transfer Consolidation", not failures, failures)


def validate_price_format(rows: list[TableRow]) -> ValidationResult:
    failures = []
    for row in rows:
        price = row.get("Monthly (USD)")
        if not price.startswith("$"):
            failures.append(
                f"line {row.line_no}: Monthly (USD) should start with `$`"
            )
    return ValidationResult("Monthly Price Formatting", not failures, failures)


def run_validation(md_path: Path) -> list[ValidationResult]:
    rows = parse_document(md_path)
    if not rows:
        return [
            ValidationResult(
                "Parsed Resource Rows",
                False,
                ["No Markdown table rows were parsed from the input file"],
            )
        ]

    return [
        validate_headers(rows),
        validate_regions(rows),
        validate_duplicates(rows),
        validate_non_empty_required_cells(rows),
        validate_resource_count(rows),
        validate_category_vs_section(rows),
        validate_traffic_normalization(rows),
        validate_data_transfer_consolidation(rows),
        validate_price_format(rows),
    ]


def print_results(results: list[ValidationResult]) -> int:
    failed = False
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.name}")
        for detail in result.details:
            print(f"  - {detail}")
        if not result.passed:
            failed = True
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate billing_categorized.md before Step 4"
    )
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    exit_code = print_results(run_validation(args.input))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
