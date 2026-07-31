# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Check whether a Huawei Cloud service is offered in a target region.

The API Explorer endpoint catalog is used because a service can be registered
in the control plane without being offered in every region. A request failure
is deliberately treated as service availability: an unregistered service or
an unavailable API Explorer endpoint must not create a false negative.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_CODE_FILE = Path(__file__).resolve().parents[1] / "data" / "code.json"
DEFAULT_PRODUCT_REGIONS_FILE = Path(__file__).resolve().parents[1] / "data" / "product-regions.json"
DEFAULT_ENDPOINT_URL = (
    "https://console-intl.huaweicloud.com/apiexplorer/new/v1/endpoints/"
    "{code}/search?offset=0&limit=50"
)

AVAILABLE = "Available"
UNAVAILABLE = "Unavailable"
SKIPPED = "Skipped"
API_FAILURE = "Available (API check failed)"


def _normalize_name(value: str) -> str:
    """Normalize display names without changing their semantic content."""
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"[\s\u3000]+", "", value)
    return value.casefold()


def load_service_codes(code_file: Path = DEFAULT_CODE_FILE) -> list[dict[str, Any]]:
    """Load and validate the service name/code catalog."""
    with code_file.open(encoding="utf-8") as source:
        data = json.load(source)

    if not isinstance(data, list):
        raise ValueError("Service code catalog must be a JSON array")

    entries: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name, code = item.get("name"), item.get("code")
        if isinstance(name, str) and name.strip() and isinstance(code, str) and code.strip():
            entry: dict[str, Any] = {"name": name.strip(), "code": code.strip()}
            if item.get("global") is True:
                entry["global"] = True
            entries.append(entry)
    return entries


def load_product_regions(
    regions_file: Path = DEFAULT_PRODUCT_REGIONS_FILE,
) -> dict[str, list[str]]:
    """Load optional per-service region overrides keyed by service code."""
    with regions_file.open(encoding="utf-8") as source:
        data = json.load(source)
    if not isinstance(data, dict):
        raise ValueError("product-regions.json must contain an object")

    regions: dict[str, list[str]] = {}
    for code, values in data.items():
        if not isinstance(code, str) or not isinstance(values, list):
            raise ValueError("product-regions.json entries must be code-to-list mappings")
        if not all(isinstance(region, str) for region in values):
            raise ValueError(f"Region list for {code} must contain strings")
        regions[code] = [region.strip() for region in values if region.strip()]
    return regions


def _product_parts(product: str) -> list[str]:
    """Split the multi-value product cell formats used by the inventory."""
    parts = re.split(r"<br\s*/?>|\n", product, flags=re.IGNORECASE)
    return [part.strip() for part in parts if part.strip()]


def resolve_service_codes(
    product: str, service_catalog: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Resolve product display names to codes from ``code.json``.

    Exact matches are preferred. If a mapped product includes a variant such
    as ``RDS for MySQL``, the longest catalog name contained in that product
    is used (``云数据库RDS``). This handles product-family suffixes without
    inventing codes outside the catalog.
    """
    resolved: list[dict[str, str]] = []
    seen_codes: set[str] = set()

    for product_part in _product_parts(product):
        normalized_product = _normalize_name(product_part)
        exact = [
            item
            for item in service_catalog
            if _normalize_name(item["name"]) == normalized_product
        ]
        candidates = exact or [
            item
            for item in service_catalog
            if _normalize_name(item["name"]) in normalized_product
        ]
        if not candidates:
            continue

        longest_name_length = max(len(_normalize_name(item["name"])) for item in candidates)
        for item in candidates:
            if len(_normalize_name(item["name"])) != longest_name_length:
                continue
            if item["code"] not in seen_codes:
                resolved.append(item)
                seen_codes.add(item["code"])

    return resolved


def _fetch_endpoint_payload(url: str, timeout: int) -> Any:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "migration-to-huawei-billing-mapper"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _region_in_payload(payload: Any, region: str) -> bool:
    if not isinstance(payload, dict) or not isinstance(payload.get("endpoints"), list):
        raise ValueError("API response does not contain an endpoints array")
    return any(
        isinstance(endpoint, dict) and endpoint.get("region") == region
        for endpoint in payload["endpoints"]
    )


def check_service_region(
    product: str,
    region: str,
    *,
    service_catalog: list[dict[str, Any]] | None = None,
    product_regions: dict[str, list[str]] | None = None,
    code_file: Path = DEFAULT_CODE_FILE,
    product_regions_file: Path = DEFAULT_PRODUCT_REGIONS_FILE,
    timeout: int = 15,
    endpoint_template: str = DEFAULT_ENDPOINT_URL,
) -> dict[str, Any]:
    """Return the service-region result and evidence for one inventory row."""
    catalog = service_catalog if service_catalog is not None else load_service_codes(code_file)
    supported_regions = (
        product_regions
        if product_regions is not None
        else load_product_regions(product_regions_file)
    )
    services = resolve_service_codes(product, catalog)
    if not services:
        return {
            "status": SKIPPED,
            "product": product,
            "region": region,
            "codes": [],
            "reason": "No matching service name in code.json",
        }

    failures: list[str] = []
    checked_codes: list[str] = []
    known_unavailable = False
    for service in services:
        code = service["code"]
        checked_codes.append(code)

        if service.get("global") is True:
            return {
                "status": AVAILABLE,
                "product": product,
                "region": region,
                "codes": checked_codes,
                "matched_code": code,
                "source": "code.json:global",
            }

        if code in supported_regions:
            regions = supported_regions[code]
            if "all" in {item.casefold() for item in regions} or region in regions:
                return {
                    "status": AVAILABLE,
                    "product": product,
                    "region": region,
                    "codes": checked_codes,
                    "matched_code": code,
                    "source": "product-regions.json",
                }
            known_unavailable = True
            continue

        url = endpoint_template.format(code=quote(code, safe=""))
        try:
            payload = _fetch_endpoint_payload(url, timeout)
            if _region_in_payload(payload, region):
                return {
                    "status": AVAILABLE,
                    "product": product,
                    "region": region,
                    "codes": checked_codes,
                    "matched_code": code,
                }
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            failures.append(f"{code}: {exc.__class__.__name__}")

    if failures:
        return {
            "status": API_FAILURE,
            "product": product,
            "region": region,
            "codes": checked_codes,
            "reason": "; ".join(failures),
        }

    return {
        "status": UNAVAILABLE,
        "product": product,
        "region": region,
        "codes": checked_codes,
        "reason": (
            "Target region is absent from product-regions.json"
            if known_unavailable
            else "Target region is absent from every successful endpoint response"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", required=True, help="Huawei Cloud Product cell")
    parser.add_argument("--region", required=True, help="HWC Target Region")
    parser.add_argument("--code-file", type=Path, default=DEFAULT_CODE_FILE)
    parser.add_argument("--product-regions-file", type=Path, default=DEFAULT_PRODUCT_REGIONS_FILE)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    try:
        result = check_service_region(
            args.product,
            args.region,
            code_file=args.code_file,
            product_regions_file=args.product_regions_file,
            timeout=args.timeout,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Unable to load service code catalog: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        codes = ", ".join(result["codes"]) or "none"
        print(f"{result['status']}: {args.product} [{args.region}] (codes: {codes})")
        if result.get("reason"):
            print(f"Reason: {result['reason']}")


if __name__ == "__main__":
    main()
