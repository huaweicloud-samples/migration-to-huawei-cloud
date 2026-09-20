# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Check whether a Huawei Cloud service is offered in a target region."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


DEFAULT_CODE_FILE = Path(__file__).resolve().parents[1] / "data" / "code.json"
DEFAULT_PRODUCT_REGIONS_FILE = Path(__file__).resolve().parents[1] / "data" / "product-regions.json"
DEFAULT_SPECIAL_PRODUCTS_FILE = Path(__file__).resolve().parents[1] / "data" / "calculator-special-products.json"
CALCULATOR_MENU_ENDPOINTS = {
    "intl": "https://portal-intl.huaweicloud.com/api/calculator/rest/cbc/portalcalculatornodeservice/v4/api/menuInfo",
    "china": "https://portal.huaweicloud.com/api/calculator/rest/cbc/portalcalculatornodeservice/v4/api/menuInfo",
}
CALCULATOR_PRODUCT_ENDPOINTS = {
    "intl": "https://portal-intl.huaweicloud.com/api/calculator/rest/cbc/portalcalculatornodeservice/v4/api/productInfo",
    "china": "https://portal.huaweicloud.com/api/calculator/rest/cbc/portalcalculatornodeservice/v4/api/productInfo",
}
DEFAULT_ENDPOINT_URL = (
    "https://console-intl.huaweicloud.com/apiexplorer/new/v1/endpoints/"
    "{code}/search?offset=0&limit=50"
)

AVAILABLE = "Available"
UNAVAILABLE = "Unavailable"
SKIPPED = "Skipped"
API_FAILURE = "Available (API check failed)"
CALCULATOR_FAILURE = "Pending Confirmation (calculator check failed)"


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


def load_special_products(path: Path = DEFAULT_SPECIAL_PRODUCTS_FILE) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        data = json.load(source)
    if not isinstance(data, dict):
        raise ValueError("calculator-special-products.json must contain an object")
    return data


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


def _fetch_calculator(endpoint: str, params: dict[str, str], timeout: int, opener) -> Any:
    url = f"{endpoint}?{urlencode(params)}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "migration-to-huawei-billing-mapper"})
    with opener(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _calculator_products(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("menuInfos"), list):
        raise ValueError("Calculator menu response does not contain menuInfos")

    products: list[dict[str, Any]] = []

    def visit(nodes: list[Any], parent: str | None = None) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            current_parent = node.get("parentCategoryName", parent)
            if node.get("urlPath") and node.get("categoryName"):
                item = dict(node)
                item.setdefault("parentCategoryName", current_parent)
                products.append(item)
            children = node.get("subCategoryLists")
            if isinstance(children, list):
                visit(children, current_parent)

    visit(payload["menuInfos"])
    return products


def _calculator_product_match(products: list[dict[str, Any]], queries: list[str]) -> dict[str, Any] | None:
    normalized = {_normalize_name(query) for query in queries if query}
    for product in products:
        values = {product.get("urlPath"), product.get("categoryName"), *(product.get("associateList") or [])}
        if any(_normalize_name(value) in normalized for value in values if isinstance(value, str)):
            return product
    return None


def _special_rule(product: str, site: str, rules: dict[str, Any]) -> dict[str, Any] | None:
    normalized = _normalize_name(product)
    for rule in (rules.get(site) or {}).values():
        if any(_normalize_name(alias) in normalized for alias in rule.get("aliases", [])):
            return rule
    return None


def _has_product_group(payload: Any, groups: list[str]) -> bool:
    if not isinstance(payload, dict) or not isinstance(payload.get("product"), dict):
        raise ValueError("Calculator product response does not contain product")
    products = payload["product"]
    return any(
        isinstance(products.get(group), list)
        and any(isinstance(item, dict) and item.get("resourceSpecCode") and isinstance(item.get("planList"), list) and item["planList"] for item in products[group])
        for group in groups
    )


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
    special_products_file: Path = DEFAULT_SPECIAL_PRODUCTS_FILE,
    site: str = "intl",
    timeout: int = 15,
    endpoint_template: str = DEFAULT_ENDPOINT_URL,
    opener=None,
) -> dict[str, Any]:
    """Return the service-region result and evidence for one inventory row."""
    if site not in CALCULATOR_MENU_ENDPOINTS:
        raise ValueError(f"Unsupported calculator site: {site}")
    opener = opener or urlopen
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
    for service in services:
        if service.get("global") is True:
            return {
                "status": AVAILABLE,
                "product": product,
                "region": region,
                "codes": [item["code"] for item in services],
                "matched_code": service["code"],
                "source": "code.json:global",
            }

    try:
        rules = load_special_products(special_products_file)
        menu = _fetch_calculator(
            CALCULATOR_MENU_ENDPOINTS[site],
            {"sign": "common", "language": "zh-cn" if site == "china" else "en-us"},
            timeout,
            opener,
        )
        special = _special_rule(product, site, rules)
        if special:
            parent = _calculator_product_match(_calculator_products(menu), [special["parent_url_path"]])
            if parent is None:
                return {"status": UNAVAILABLE, "product": product, "region": region, "codes": [item["code"] for item in services], "matched_code": services[0]["code"], "reason": "Parent product is absent from calculator menuInfo", "source": "calculator:menuInfo", "site": site}
            region_online = parent.get("regionOnline")
            if not isinstance(region_online, dict) or region not in (region_online.get("regionList") or []):
                return {"status": UNAVAILABLE, "product": product, "region": region, "codes": [item["code"] for item in services], "matched_code": services[0]["code"], "reason": "Target region is absent from parent product in calculator menuInfo", "source": "calculator:menuInfo", "site": site}
            product_payload = _fetch_calculator(
                CALCULATOR_PRODUCT_ENDPOINTS[site],
                {
                    "urlPath": special["parent_url_path"],
                    "tag": "general.online.portal",
                    "region": region,
                    "tab": "calc",
                    "sign": "common",
                },
                timeout,
                opener,
            )
            if _has_product_group(product_payload, special["product_groups"]):
                return {"status": AVAILABLE, "product": product, "region": region, "codes": [item["code"] for item in services], "matched_code": services[0]["code"], "source": "calculator:productInfo", "site": site}
            return {"status": UNAVAILABLE, "product": product, "region": region, "codes": [item["code"] for item in services], "matched_code": services[0]["code"], "reason": "Special product group is absent or has no valid price plan in productInfo", "source": "calculator:productInfo", "site": site}

        queries = [product, *[item["code"] for item in services]]
        menu_product = _calculator_product_match(_calculator_products(menu), queries)
        if menu_product is not None:
            region_online = menu_product.get("regionOnline")
            if not isinstance(region_online, dict) or not isinstance(region_online.get("regionList"), list):
                raise ValueError("Calculator menu product has no usable regionOnline.regionList")
            if region in region_online["regionList"]:
                return {"status": AVAILABLE, "product": product, "region": region, "codes": [item["code"] for item in services], "matched_code": services[0]["code"], "source": "calculator:menuInfo", "site": site}
            return {"status": UNAVAILABLE, "product": product, "region": region, "codes": [item["code"] for item in services], "matched_code": services[0]["code"], "reason": "Target region is absent from calculator menuInfo", "source": "calculator:menuInfo", "site": site}
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        calculator_failure = f"{exc.__class__.__name__}: {exc}"
    else:
        calculator_failure = None

    if calculator_failure:
        return {
            "status": CALCULATOR_FAILURE,
            "product": product,
            "region": region,
            "codes": [item["code"] for item in services],
            "reason": f"Calculator check failed: {calculator_failure}",
        }

    failures: list[str] = []
    checked_codes: list[str] = []
    known_unavailable = False
    for service in services:
        code = service["code"]
        checked_codes.append(code)

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
    parser.add_argument("--special-products-file", type=Path, default=DEFAULT_SPECIAL_PRODUCTS_FILE)
    parser.add_argument("--site", choices=sorted(CALCULATOR_MENU_ENDPOINTS), default="intl")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    try:
        result = check_service_region(
            args.product,
            args.region,
            code_file=args.code_file,
            product_regions_file=args.product_regions_file,
            special_products_file=args.special_products_file,
            site=args.site,
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
