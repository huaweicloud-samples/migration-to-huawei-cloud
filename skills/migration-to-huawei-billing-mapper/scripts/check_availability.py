# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Check Huawei Cloud spec availability via hcloud CLI.

Reads billing_with_specs.md, queries hcloud for each recommended spec's
availability in the target region, and outputs billing_final.md with
an "Availability" column while preserving the existing table schema.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROW_NUM_COL = "#"
SOURCE_PRODUCT_COL = "Source Product"
SOURCE_SPEC_COL = "Source Spec"
TARGET_REGION_COL = "HWC Target Region"
HUAWEI_PRODUCT_COL = "Huawei Cloud Product"
RECOMMENDED_SPEC_COL = "Recommended Spec"
AVAILABILITY_COL = "Availability"


# ── hcloud command definitions ──────────────────────────────────────────
# Each entry maps a Huawei Cloud product name to the hcloud command needed
# to check its availability. "extra_args" are appended after --region.
# "jmespath_ok" is the JMESPath expression that returns non-empty when
# the spec/service is available.

HCLOUD_COMMANDS: dict[str, dict] = {
    # Compute ──────────────────────────────────────────────────────────
    "弹性云服务器ECS": {
        "service": "ECS",
        "action": "ListFlavors",
        "jmespath_ok": "flavors[?name=='{flavor}']",
    },
    "弹性云服务器 ECS": {
        "service": "ECS",
        "action": "ListFlavors",
        "jmespath_ok": "flavors[?name=='{flavor}']",
    },
    "裸金属服务器BMS": {
        "service": "BMS",
        "action": "ListFlavors",
        "jmespath_ok": "flavors[?name=='{flavor}']",
    },
    # Database ─────────────────────────────────────────────────────────
    "云数据库 RDS for MySQL": {
        "service": "RDS",
        "action": "ListFlavors",
        "extra_args": ["--database_name=MySQL"],
        # Query with spec_code if available, else query first page
        "jmespath_ok": "flavors[?spec_code=='{flavor}'].az_status",
        "jmespath_fallback": "flavors[0].az_status",
    },
    "云数据库 RDS for MariaDB": {
        "service": "RDS",
        "action": "ListFlavors",
        "extra_args": ["--database_name=MariaDB"],
        "jmespath_ok": "flavors[?spec_code=='{flavor}'].az_status",
        "jmespath_fallback": "flavors[0].az_status",
    },
    "云数据库 RDS for PostgreSQL": {
        "service": "RDS",
        "action": "ListFlavors",
        "extra_args": ["--database_name=PostgreSQL"],
        "jmespath_ok": "flavors[?spec_code=='{flavor}'].az_status",
        "jmespath_fallback": "flavors[0].az_status",
    },
    "云数据库 RDS for SQLServer": {
        "service": "RDS",
        "action": "ListFlavors",
        "extra_args": ["--database_name=SQLServer"],
        "jmespath_ok": "flavors[?spec_code=='{flavor}'].az_status",
        "jmespath_fallback": "flavors[0].az_status",
    },
    "云数据库 TaurusDB": {
        "service": "GaussDB",
        "action": "ShowGaussMySqlFlavors",
        "extra_args": ["--database_name=gaussdb-mysql",
                       "--availability_zone_mode=multi"],
        "jmespath_ok": "flavors[?spec_code=='{flavor}'].az_status",
        "jmespath_fallback": "flavors[0].az_status",
    },
    "云数据库GaussDB": {
        "service": "GaussDBforopenGauss",
        "action": "ListFlavors",
        "jmespath_ok": "flavors[?spec_code=='{flavor}'].az_status",
        "jmespath_fallback": "flavors[0].az_status",
    },
    "分布式缓存服务Redis版": {
        "service": "DCS",
        "action": "ListFlavors",
        "extra_args": ["--engine=Redis"],
        "jmespath_ok": "flavors[?spec_code=='{flavor}'].flavors_available_zones",
    },
    # Network ──────────────────────────────────────────────────────────
    # These are presence APIs → any valid JSON response = Available
    "弹性负载均衡ELB": {
        "service": "ELB",
        "action": "ListLoadBalancers",
        "jmespath_ok": "loadbalancers",
        "any_response_ok": True,
    },
    "NAT网关": {
        "service": "NAT",
        "action": "ListNatGateways",
        "jmespath_ok": "nat_gateways",
        "any_response_ok": True,
    },
    "弹性公网IP EIP": {
        "service": "EIP",
        "action": "ListPublicips",
        "jmespath_ok": "publicips",
        "any_response_ok": True,
    },
    "弹性公网IP EIP (按流量计费)": {
        "service": "EIP",
        "action": "ListBandwidths",
        "jmespath_ok": "bandwidths",
        "any_response_ok": True,
    },
    # Storage ──────────────────────────────────────────────────────────
    "云硬盘EVS": {
        "service": "EVS",
        "action": "CinderListVolumeTypes",
        "jmespath_ok": "volume_types",
        "any_response_ok": True,
    },
    # Note: FunctionGraph, OBS, SWR, CDN, DNS, CES, LTS, DEW, SMN,
    # DMS, DataArts, CBH, COC, APM, CBR, VPC are platform-level
    # regional services → always "N/A".
}


JMESPATH_FAILURE_TEXT = "The JMESPath query on JSON results failed."
INVALID_SPEC_ERROR_CODES = {"DBS.280434"}
AVAILABLE_AZ_STATES = {"normal", "obt", "promotion"}
SOLD_OUT_AZ_STATES = {"sellout"}


def _split_hcloud_stdout(stdout: str) -> tuple[str, list[str]]:
    """
    Separate leading warning/info lines from the JSON payload.

    hcloud may prepend informational lines before printing JSON. We need to
    keep those lines so callers can distinguish harmless warnings from a
    failed --cli-query that falls back to the raw API response.
    """
    stdout = stdout.strip()
    if not stdout:
        return "", []

    lines = stdout.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            prefix = [item.strip() for item in lines[:idx] if item.strip()]
            return "\n".join(lines[idx:]), prefix
    return stdout, []


def _parse_json_prefix(stdout: str) -> Any:
    """Parse the first JSON value from stdout and ignore trailing diagnostics."""
    decoder = json.JSONDecoder()
    data, _ = decoder.raw_decode(stdout)
    return data


def _hcloud_json(args: list[str], timeout: int = 30) -> tuple[Any | None, bool]:
    """
    Run hcloud and return parsed JSON plus whether --cli-query failed.

    When hcloud cannot evaluate the JMESPath expression, it prints a warning
    and falls back to the original unfiltered response. Callers must not treat
    that raw payload as if it were the filtered query result.
    """
    try:
        result = subprocess.run(
            ["hcloud"] + args,
            input="y\n",
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return None, False
        stdout, prefix_lines = _split_hcloud_stdout(result.stdout)
        if not stdout:
            return None, False
        query_failed = any(JMESPATH_FAILURE_TEXT in line for line in prefix_lines)
        return _parse_json_prefix(stdout), query_failed
    except (json.JSONDecodeError, subprocess.TimeoutExpired,
            FileNotFoundError):
        return None, False


def hcloud_available() -> bool:
    """Check if hcloud CLI is installed and configured."""
    try:
        result = subprocess.run(
            ["hcloud", "configure", "list"],
            input="y\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _extract_flavor(spec: str) -> str:
    """
    Extract the short flavor code from a spec recommendation string.
    e.g. "s6.large.2 (2vCPU 4GB) — ..." → "s6.large.2"
         "gaussdb.mysql.tcu.32u.64g (TCU 32vCPU..." → "gaussdb.mysql.tcu.32u.64g"
         "rds.mysql.large.arm2.ha (2vCPU 4GB) — ..." → "rds.mysql.large.arm2.ha"
         "GPSSD General Purpose SSD (300GB, ...)" → "GPSSD"
    """
    spec = spec.strip()
    # ECS flavor: s6.large.2, c6.4xlarge.2
    m = re.match(r'([a-z]+\d+\.[\w.]+)', spec, re.IGNORECASE)
    if m:
        return m.group(1)
    # RDS/TaurusDB/DCS flavors: rds.mysql.xxx, gaussdb.mysql.xxx, redis.xxx
    m = re.match(r'(rds\.[a-z0-9_.-]+|gaussdb\.[a-z0-9_.-]+|redis\.[a-z0-9_.-]+)', spec, re.IGNORECASE)
    if m:
        return m.group(1)
    # Disk type: GPSSD / ESSD / SAS / SATA
    m = re.match(r'(GPSSD2?|ESSD|SAS|SATA|SSD)', spec, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # Fallback: first word
    return spec.split()[0] if spec else spec


def _has_dcs_available_zones(value: Any) -> bool:
    """Check whether a DCS flavor response includes at least one sellable AZ."""
    if isinstance(value, list):
        return any(_has_dcs_available_zones(item) for item in value)
    if isinstance(value, dict):
        zones = value.get("flavors_available_zones")
        if isinstance(zones, list):
            return any(
                isinstance(item, dict)
                and bool(item.get("az_codes"))
                for item in zones
            )
    return False


def _queryable_flavor(hw_product: str, spec: str) -> str | None:
    """Return the exact flavor/spec code only when the cell is machine-queryable."""
    spec = spec.strip()
    if not spec or spec.startswith("—") or spec.startswith("-"):
        return None

    patterns = {
        "弹性云服务器ECS": r"([a-z]+\d+\.[\w.]+)",
        "弹性云服务器 ECS": r"([a-z]+\d+\.[\w.]+)",
        "裸金属服务器BMS": r"([a-z]+\d+\.[\w.]+)",
        "云数据库 RDS for MySQL": r"(rds\.[a-z0-9_.-]+)",
        "云数据库 RDS for MariaDB": r"(rds\.[a-z0-9_.-]+)",
        "云数据库 RDS for PostgreSQL": r"(rds\.[a-z0-9_.-]+)",
        "云数据库 RDS for SQLServer": r"(rds\.[a-z0-9_.-]+)",
        "云数据库 TaurusDB": r"(gaussdb\.[a-z0-9_.-]+)",
        "云数据库GaussDB": r"(gaussdb\.[a-z0-9_.-]+)",
        "分布式缓存服务Redis版": r"(redis\.[a-z0-9_.-]+)",
    }

    pattern = patterns.get(hw_product)
    if not pattern:
        return _extract_flavor(spec)

    match = re.match(pattern, spec, re.IGNORECASE)
    if not match:
        return None
    return match.group(1)


def _get_recommended_spec(spec: str) -> str:
    """
    Read the recommended spec cell.

    Recommended Spec currently stores any rationale inline after an em dash,
    so strip that suffix before querying hcloud.
    """
    spec = spec.strip()
    if not spec:
        return spec
    if " — " in spec:
        return spec.split(" — ", 1)[0].strip()
    if spec.startswith("— "):
        return "—"
    return spec


def _data_ok(data, expression: str) -> bool:
    """
    Check if hcloud's JMESPath-filtered result indicates availability.
    hcloud --cli-query already evaluated the expression, so `data` is
    the query result (not the raw API response).

    Cases:
      - null / None / empty list → unavailable
      - non-empty list of flavors → available
      - az_status dict with any "normal" → available
      - plain truthy value → available
    """
    if data is None:
        return False
    if isinstance(data, list):
        return len(data) > 0
    if isinstance(data, dict):
        # az_status dict: check for "normal" value
        if all(k.startswith("ap-") or k.startswith("eu-") or k.startswith("na-")
               or k.startswith("sa-") or k.startswith("me-") or k.startswith("af-")
               or k.startswith("la-") or k.startswith("cn-") for k in data):
            return any(v == "normal" for v in data.values())
        return len(data) > 0
    return bool(data)


def _az_status_ok(value: Any) -> bool:
    """Check whether any AZ state is reported as normal."""
    if isinstance(value, list):
        return any(_az_status_ok(item) for item in value)
    if isinstance(value, dict):
        return any(item == "normal" for item in value.values())
    return value == "normal"


def _extract_az_states(value: str) -> set[str]:
    """Extract AZ state labels such as normal/sellout from cond:operation:az."""
    if not value:
        return set()
    return {
        match.lower()
        for match in re.findall(r"\(([^()]+)\)", value)
    }


def _invalid_spec_error(data: Any) -> bool:
    """Check for service-side invalid spec/flavor responses."""
    return (
        isinstance(data, dict)
        and data.get("error_code") in INVALID_SPEC_ERROR_CODES
    )


def _raw_response_ok(data: Any, cmd_info: dict[str, Any], flavor: str) -> bool:
    """
    Validate a raw API response when hcloud fails to apply --cli-query.

    This prevents false positives where the CLI emits the original unfiltered
    payload and the caller would otherwise treat "non-empty response" as a hit.
    """
    if not isinstance(data, dict):
        return False

    service = cmd_info.get("service")
    action = cmd_info.get("action")

    if action == "ListFlavors" and service in {"ECS", "BMS"}:
        flavors = data.get("flavors", [])
        return any(
            isinstance(item, dict) and item.get("name") == flavor
            for item in flavors
        )

    if (
        service in {"RDS", "GaussDB", "GaussDBforopenGauss"}
        and action in {"ListFlavors", "ShowGaussMySqlFlavors"}
    ):
        flavors = data.get("flavors", [])
        return any(
            isinstance(item, dict)
            and item.get("spec_code") == flavor
            and _az_status_ok(item.get("az_status"))
            for item in flavors
        )

    if service == "DCS" and action == "ListAvailableZones":
        zones = data.get("available_zones", [])
        return any(
            isinstance(item, dict)
            and str(item.get("resource_availability")).lower() == "true"
            for item in zones
        )

    if service == "DCS" and action == "ListFlavors":
        flavors = data.get("flavors", [])
        return any(
            isinstance(item, dict)
            and item.get("spec_code") == flavor
            and _has_dcs_available_zones(item)
            for item in flavors
        )

    return False


def _classify_ecs_flavor(data: Any) -> str | None:
    """Classify ECS flavor state from a direct ListFlavors response."""
    if not isinstance(data, dict):
        return None
    flavors = data.get("flavors", [])
    if not flavors:
        return "Flavor Not Found"

    states: set[str] = set()
    for item in flavors:
        if not isinstance(item, dict):
            continue
        extra_specs = item.get("os_extra_specs", {})
        if not isinstance(extra_specs, dict):
            continue
        states.update(_extract_az_states(extra_specs.get("cond:operation:az", "")))

    if states & AVAILABLE_AZ_STATES:
        return "Available"
    if states & SOLD_OUT_AZ_STATES:
        return "Sold Out"
    return "Unavailable"


def _classify_db_flavor(data: Any) -> str | None:
    """Classify DB flavor state from a direct spec_code lookup response."""
    if _invalid_spec_error(data):
        return "Flavor Not Found"
    if not isinstance(data, dict):
        return None
    flavors = data.get("flavors", [])
    if not flavors:
        return "Flavor Not Found"
    for item in flavors:
        if isinstance(item, dict) and _az_status_ok(item.get("az_status")):
            return "Available"
    return "Sold Out"


def _classify_dcs_flavor(data: Any) -> str | None:
    """Classify DCS flavor availability from ListFlavors."""
    if not isinstance(data, dict):
        return None
    flavors = data.get("flavors", [])
    if not flavors:
        return "Flavor Not Found"
    for item in flavors:
        if isinstance(item, dict) and _has_dcs_available_zones(item):
            return "Available"
    return "Sold Out"


def _precise_availability(cmd_info: dict[str, Any], region: str, flavor: str) -> str | None:
    """Use service-side flavor/spec filters when the API supports them."""
    service = cmd_info.get("service")
    action = cmd_info.get("action")

    if service == "ECS" and action == "ListFlavors":
        args = [service, action, f"--region={region}", f"--flavor_id={flavor}"]
        data, _ = _hcloud_json(args)
        if data is None:
            return "Not Detected"
        return _classify_ecs_flavor(data)

    if service in {"RDS", "GaussDB", "GaussDBforopenGauss"}:
        args = [service, action, f"--region={region}", f"--spec_code={flavor}"]
        for extra in cmd_info.get("extra_args", []):
            args.append(extra)
        data, _ = _hcloud_json(args)
        if data is None:
            return "Not Detected"
        return _classify_db_flavor(data)

    if service == "DCS" and action == "ListFlavors":
        args = [service, action, f"--cli-region={region}", f"--spec_code={flavor}"]
        for extra in cmd_info.get("extra_args", []):
            args.append(extra)
        data, _ = _hcloud_json(args)
        if data is None:
            return "Not Detected"
        return _classify_dcs_flavor(data)

    return None


def check_availability(cmd_info: dict, region: str, flavor: str) -> str:
    """
    Query hcloud and determine availability.
    Returns: "Available" | "Sold Out" | "Flavor Not Found" |
             "Unavailable" | "Not Detected" | "N/A"
    """
    if not hcloud_available():
        return "Not Detected"

    precise = _precise_availability(cmd_info, region, flavor)
    if precise is not None:
        return precise

    jmespath = cmd_info.get("jmespath_ok", "").replace("{flavor}", flavor)

    args = [
        cmd_info["service"],
        cmd_info["action"],
        f"--region={region}",
        f"--cli-query={jmespath}",
    ]
    for extra in cmd_info.get("extra_args", []):
        args.append(extra)

    data, query_failed = _hcloud_json(args)
    if data is None:
        return "Not Detected"

    # For presence APIs, any valid JSON response = service is available
    if cmd_info.get("any_response_ok"):
        return "Available"

    if query_failed:
        return "Available" if _raw_response_ok(data, cmd_info, flavor) else "Sold Out"

    if _data_ok(data, jmespath):
        return "Available"
    return "Sold Out"


# ── Markdown table parsing / writing ─────────────────────────────────────

def parse_md_tables(md_path: Path) -> list[dict[str, Any]]:
    """Parse Markdown tables and preserve header order for index-based access."""
    rows: list[dict[str, Any]] = []
    with open(md_path, encoding="utf-8") as f:
        content = f.read()
    lines = content.split("\n")
    i, current_headers, in_table = 0, [], False
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and "---" not in line and not in_table:
            headers = [h.strip() for h in line.split("|")[1:-1]]
            if i + 1 < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip()):
                current_headers, in_table = headers, True
                i += 2; continue
        elif in_table and line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) == len(current_headers):
                rows.append(
                    {
                        "headers": current_headers.copy(),
                        "cells": cells,
                    }
                )
        elif in_table and (not line.startswith("|") or not line.strip()):
            in_table, current_headers = False, []
        i += 1
    return rows


def detect_columns(headers: list[str]) -> dict[str, int]:
    required = [
        ROW_NUM_COL,
        SOURCE_PRODUCT_COL,
        SOURCE_SPEC_COL,
        TARGET_REGION_COL,
        HUAWEI_PRODUCT_COL,
        RECOMMENDED_SPEC_COL,
    ]
    missing = [name for name in required if name not in headers]
    if missing:
        raise ValueError(
            "Missing required table headers: " + ", ".join(missing)
        )
    return {
        "row_num": headers.index(ROW_NUM_COL),
        "source_product": headers.index(SOURCE_PRODUCT_COL),
        "source_spec": headers.index(SOURCE_SPEC_COL),
        "target_region": headers.index(TARGET_REGION_COL),
        "hw_product": headers.index(HUAWEI_PRODUCT_COL),
        "recommended_spec": headers.index(RECOMMENDED_SPEC_COL),
        "availability": headers.index(AVAILABILITY_COL) if AVAILABILITY_COL in headers else -1,
    }


def _cell(cells: list[str], index: int) -> str:
    if index < 0 or index >= len(cells):
        return ""
    return cells[index].strip()


def _row_key(headers: list[str], cells: list[str]) -> tuple[str, str, str]:
    columns = detect_columns(headers)
    return (
        _cell(cells, columns["row_num"]),
        _cell(cells, columns["source_product"]),
        _cell(cells, columns["source_spec"]),
    )


def write_final_md(input_path: Path, output_path: Path, rows: list[dict[str, Any]]):
    """Rewrite MD with an Availability column."""
    with open(input_path, encoding="utf-8") as f:
        content = f.read()
    if not rows:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        return

    lookup = {}
    for r in rows:
        headers = r["headers"]
        cells = r["cells"]
        columns = detect_columns(headers)
        key = _row_key(headers, cells)
        lookup[key] = (
            _cell(cells, columns["availability"])
            if columns["availability"] >= 0
            else r.get("availability", "")
        )

    lines = content.split("\n")
    out, i, headers, in_table = [], 0, [], False
    while i < len(lines):
        line, stripped = lines[i], lines[i].strip()
        if stripped.startswith("|") and "---" not in stripped and not in_table:
            hdrs = [h.strip() for h in stripped.split("|")[1:-1]]
            if i + 1 < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip()):
                columns = detect_columns(hdrs)
                new_headers = hdrs if columns["availability"] >= 0 else hdrs + ["Availability"]
                out.append("| " + " | ".join(new_headers) + " |")
                out.append("|" + "|".join(["------"] * len(new_headers)) + "|")
                headers, in_table = hdrs, True; i += 1; continue
        elif in_table and re.match(r"^\|[\s\-:|]+\|$", stripped): i += 1; continue
        elif in_table and stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if len(cells) == len(headers):
                columns = detect_columns(headers)
                avail = lookup.get(_row_key(headers, cells), "")
                if columns["availability"] >= 0:
                    while len(cells) <= columns["availability"]:
                        cells.append("")
                    cells[columns["availability"]] = avail
                    out.append("| " + " | ".join(cells) + " |")
                else:
                    out.append("| " + " | ".join(cells + [avail]) + " |")
                i += 1
                continue
            else: in_table = False
        elif in_table and not (stripped.startswith("|") and stripped): in_table, headers = False, []
        out.append(line); i += 1
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


# ── main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Check spec availability via hcloud")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    hw_ok = hcloud_available()
    if not hw_ok:
        print("Warning: hcloud CLI not detected. All specs will be marked 'Not Detected'.")

    print(f"Parsing tables from {args.input}...")
    rows = parse_md_tables(args.input)
    print(f"  Found {len(rows)} resource rows")

    checked = 0
    for row in rows:
        headers = row["headers"]
        cells = row["cells"]
        columns = detect_columns(headers)
        if columns["availability"] >= 0:
            while len(cells) <= columns["availability"]:
                cells.append("")

        hw_product = _cell(cells, columns["hw_product"])
        raw_spec = _cell(cells, columns["recommended_spec"])
        spec = _get_recommended_spec(raw_spec)
        target_region = _cell(cells, columns["target_region"])

        if columns["availability"] < 0:
            columns["availability"] = len(cells)
            cells.append("")

        if not hw_product or not spec:
            cells[columns["availability"]] = "N/A"
            row["availability"] = "N/A"
            continue

        # Skip rows with no instance spec to check (I/O, backup, storage-only)
        if spec.strip().startswith("—") or spec.strip().startswith("-"):
            cells[columns["availability"]] = "N/A"
            row["availability"] = "N/A"
            continue

        # hw_product may contain <br>-separated values → try each
        cmd_info = None
        flavor_name = None
        for candidate in hw_product.split("<br>"):
            candidate = candidate.strip()
            cmd_info = HCLOUD_COMMANDS.get(candidate)
            if cmd_info:
                flavor_name = _queryable_flavor(candidate, spec)
                if flavor_name or cmd_info.get("any_response_ok"):
                    hw_product = candidate
                    break
                break

        if cmd_info:
            if not flavor_name and not cmd_info.get("any_response_ok"):
                cells[columns["availability"]] = "N/A"
                row["availability"] = "N/A"
                print(f"  {hw_product} / {spec} → N/A (spec not machine-queryable)")
                continue
            if not target_region:
                status = "N/A"
                print(f"  {hw_product} / {flavor_name or spec} → N/A (no target region)")
            else:
                status = check_availability(cmd_info, target_region, flavor_name or spec)
                checked += 1
                print(f"  {hw_product} / {flavor_name or spec} [{target_region}] → {status}")
            cells[columns["availability"]] = status
            row["availability"] = status
        else:
            cells[columns["availability"]] = "N/A"
            row["availability"] = "N/A"
            print(f"  {hw_product} → N/A")

    print(f"Checked: {checked}/{len(rows)} rows")
    print(f"Writing {args.output}...")
    write_final_md(args.input, args.output, rows)
    print("Done.")


if __name__ == "__main__":
    main()
