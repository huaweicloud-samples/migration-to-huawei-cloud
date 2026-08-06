#!/usr/bin/env python3
"""Query live Huawei Cloud international calculator prices."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


INTL_MENU_ENDPOINT = (
    "https://portal-intl.huaweicloud.com/api/calculator/rest/cbc/"
    "portalcalculatornodeservice/v4/api/menuInfo"
)
INTL_PRODUCT_ENDPOINT = (
    "https://portal-intl.huaweicloud.com/api/calculator/rest/cbc/"
    "portalcalculatornodeservice/v4/api/productInfo"
)
CHINA_MENU_ENDPOINT = (
    "https://portal.huaweicloud.com/api/calculator/rest/cbc/"
    "portalcalculatornodeservice/v4/api/menuInfo"
)
CHINA_PRODUCT_ENDPOINT = (
    "https://portal.huaweicloud.com/api/calculator/rest/cbc/"
    "portalcalculatornodeservice/v4/api/productInfo"
)
# Backward-compatible aliases for callers and tests that assume the default site.
MENU_ENDPOINT = INTL_MENU_ENDPOINT
PRODUCT_ENDPOINT = INTL_PRODUCT_ENDPOINT
PRODUCT_TAG = "general.online.portal"
PRODUCT_TAB = "calc"
DEFAULT_TIMEOUT = 20
ECS_IMAGE_SUFFIXES = (".linux", ".windows", ".byol")

SITE_CONFIG = {
    "intl": {
        "menu_endpoint": INTL_MENU_ENDPOINT,
        "product_endpoint": INTL_PRODUCT_ENDPOINT,
        "language": "en-us",
        "currency": "USD",
    },
    "china": {
        "menu_endpoint": CHINA_MENU_ENDPOINT,
        "product_endpoint": CHINA_PRODUCT_ENDPOINT,
        "language": "zh-cn",
        "currency": "CNY",
    },
}

BillingPlan = dict[str, Any]

BILLING_MODE_NAMES = {
    "ondemand": "on-demand",
    "monthly": "monthly",
    "yearly": "yearly",
}
USAGE_FACTOR_NAMES = {
    "duration": "duration",
    "upflow": "upstream-traffic",
    "downflow": "downstream-traffic",
}
MEASURE_UNIT_NAMES = {
    0: "day",
    1: "USD",
    4: "hour",
    10: "GB",
    14: "count",
    15: "Mbit/s",
    17: "GB",
}


class PriceQueryError(Exception):
    """An expected, user-actionable price query failure."""

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            error["details"] = self.details
        return {"error": error}


def _request_json(
    endpoint: str,
    params: dict[str, str],
    timeout: float,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    if opener is None:
        opener = urlopen
    url = f"{endpoint}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "query-huawei-cloud-prices/1.0",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status is not None and not 200 <= status < 300:
                raise PriceQueryError(
                    "http_error", f"Huawei Cloud calculator returned HTTP {status}.", {"url": url}
                )
            body = response.read()
    except PriceQueryError:
        raise
    except HTTPError as exc:
        raise PriceQueryError(
            "http_error",
            f"Huawei Cloud calculator returned HTTP {exc.code}.",
            {"url": url, "reason": str(exc.reason)},
        ) from exc
    except (OSError, URLError, TimeoutError) as exc:
        raise PriceQueryError(
            "network_error",
            "Could not reach the Huawei Cloud calculator API.",
            {"url": url, "reason": str(exc)},
        ) from exc

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PriceQueryError(
            "invalid_json", "Huawei Cloud calculator returned invalid JSON.", {"url": url}
        ) from exc
    if not isinstance(payload, dict):
        raise PriceQueryError(
            "invalid_response", "Huawei Cloud calculator returned a non-object JSON response.", {"url": url}
        )
    return payload


def _iter_menu_products(menu_payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    menu_infos = menu_payload.get("menuInfos")
    if not isinstance(menu_infos, list):
        raise PriceQueryError("invalid_menu", "The menu response does not contain a valid menuInfos list.")

    def visit(nodes: list[Any], parent_category: Any = None) -> Iterator[dict[str, Any]]:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            current_parent = node.get("parentCategoryName", parent_category)
            if node.get("urlPath") and node.get("categoryName"):
                product = dict(node)
                product.setdefault("parentCategoryName", current_parent)
                yield product
            children = node.get("subCategoryLists")
            if isinstance(children, list):
                yield from visit(children, current_parent)

    yield from visit(menu_infos)


def _normalized(value: Any) -> str:
    return str(value).strip().casefold()


def resolve_product(product_query: str, menu_payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve a product by exact path, name, or unique alias."""
    query = _normalized(product_query)
    if not query:
        raise PriceQueryError("invalid_product", "Product name or urlPath must not be empty.")

    products = list(_iter_menu_products(menu_payload))
    for field in ("urlPath", "categoryName"):
        matches = [item for item in products if _normalized(item.get(field)) == query]
        if matches:
            break
    else:
        matches = [
            item
            for item in products
            if any(_normalized(alias) == query for alias in item.get("associateList", []))
        ]

    unique_matches = {str(item.get("urlPath")): item for item in matches}
    if not unique_matches:
        raise PriceQueryError(
            "product_not_found",
            f"No Huawei Cloud calculator product exactly matches {product_query!r}.",
            {"product": product_query},
        )
    if len(unique_matches) > 1:
        candidates = [
            {
                "category_name": item.get("categoryName"),
                "url_path": item.get("urlPath"),
                "parent_category": item.get("parentCategoryName"),
            }
            for item in unique_matches.values()
        ]
        raise PriceQueryError(
            "ambiguous_product",
            f"More than one calculator product matches {product_query!r}; choose a urlPath.",
            {"candidates": candidates},
        )
    return next(iter(unique_matches.values()))


def _check_region(product: dict[str, Any], region: str) -> None:
    region_online = product.get("regionOnline")
    if not isinstance(region_online, dict) or "regionList" not in region_online:
        raise PriceQueryError(
            "invalid_menu",
            "The selected product has no usable regionOnline.regionList in menuInfo.",
            {"url_path": product.get("urlPath")},
        )
    region_list = region_online.get("regionList")
    if not isinstance(region_list, list):
        raise PriceQueryError(
            "invalid_menu",
            "The selected product has an invalid regionOnline.regionList in menuInfo.",
            {"url_path": product.get("urlPath")},
        )
    if region not in region_list:
        raise PriceQueryError(
            "region_not_supported",
            f"Product {product.get('categoryName', product.get('urlPath'))!r} is not listed in region {region!r}.",
            {"url_path": product.get("urlPath"), "region": region, "supported_regions": region_list},
        )


def _get_site_config(site: str) -> dict[str, str]:
    try:
        return SITE_CONFIG[site.casefold()]
    except (AttributeError, KeyError) as exc:
        raise PriceQueryError(
            "invalid_site",
            f"Unsupported site {site!r}; choose intl or china.",
            {"site": site, "supported_sites": sorted(SITE_CONFIG)},
        ) from exc


def _normalize_plan(plan: dict[str, Any]) -> BillingPlan:
    mode = plan.get("billingMode")
    normalized: BillingPlan = {
        "billingMode": _mapped_value(mode, BILLING_MODE_NAMES),
    }
    if isinstance(plan.get("divisionList"), list):
        normalized["tiers"] = []
        for tier in plan["divisionList"]:
            if not isinstance(tier, dict):
                continue
            division = tier.get("division")
            division = division if isinstance(division, dict) else {}
            compact_tier: BillingPlan = {"amount": tier.get("amount")}
            for field in ("beginValue", "endValue"):
                if field in division:
                    compact_tier[field] = division[field]
            if division.get("measureUnitStep") is not None:
                compact_tier["measureUnitStep"] = division["measureUnitStep"]
            if "beginUnit" in division and "endUnit" in division:
                begin_unit = _mapped_measure_unit(division["beginUnit"])
                end_unit = _mapped_measure_unit(division["endUnit"])
                if begin_unit == end_unit:
                    compact_tier["unit"] = begin_unit
                else:
                    compact_tier["beginUnit"] = begin_unit
                    compact_tier["endUnit"] = end_unit
            elif "beginUnit" in division:
                compact_tier["beginUnit"] = _mapped_measure_unit(division["beginUnit"])
            elif "endUnit" in division:
                compact_tier["endUnit"] = _mapped_measure_unit(division["endUnit"])
            normalized["tiers"].append(compact_tier)
    elif "amount" in plan:
        normalized["amount"] = plan["amount"]

    for field in ("usageFactor", "measureUnitStep", "measureUnit"):
        if field in plan and plan[field] is not None:
            if field == "usageFactor":
                normalized[field] = _mapped_value(plan[field], USAGE_FACTOR_NAMES)
            elif field == "measureUnit":
                normalized[field] = _mapped_measure_unit(plan[field])
            else:
                normalized[field] = plan[field]
    return normalized


def _mapped_value(value: Any, mappings: dict[Any, str]) -> Any:
    if isinstance(value, str):
        return mappings.get(value.casefold(), value)
    return mappings.get(value, value)


def _mapped_measure_unit(value: Any) -> Any:
    try:
        numeric_value = int(value)
    except (TypeError, ValueError):
        return value
    return MEASURE_UNIT_NAMES.get(numeric_value, value)


def _extract_specs(product_payload: dict[str, Any], resource_spec_code: str | None) -> list[dict[str, Any]]:
    product_groups = product_payload.get("product")
    if not isinstance(product_groups, dict):
        raise PriceQueryError("invalid_product_response", "The product response does not contain a valid product object.")

    specs: list[dict[str, Any]] = []
    for entries in product_groups.values():
        if not isinstance(entries, list):
            continue
        for spec in entries:
            if not isinstance(spec, dict) or not spec.get("resourceSpecCode"):
                continue
            if resource_spec_code is not None and spec.get("resourceSpecCode") != resource_spec_code:
                continue
            plans = spec.get("planList")
            if not isinstance(plans, list):
                continue
            specs.append(
                {
                    "resourceSpecCode": spec.get("resourceSpecCode"),
                    "productSpecSysDesc": spec.get("productSpecSysDesc"),
                    "prices": [
                        _normalize_plan(plan) for plan in plans if isinstance(plan, dict)
                    ],
                }
            )

    if resource_spec_code is not None and not specs:
        raise PriceQueryError(
            "spec_not_found",
            f"No price specification matches resourceSpecCode {resource_spec_code!r}.",
            {"resource_spec_code": resource_spec_code},
        )
    return specs


def _normalize_requested_spec_code(
    resource_spec_code: str | None, url_path: str
) -> str | None:
    """Default bare ECS flavor IDs to the Linux image variant."""
    if resource_spec_code is None or url_path != "ecs":
        return resource_spec_code
    if resource_spec_code.casefold().endswith(ECS_IMAGE_SUFFIXES):
        return resource_spec_code
    return f"{resource_spec_code}.linux"


def query_prices(
    product: str,
    region: str,
    resource_spec_code: str | None = None,
    language: str | None = None,
    site: str = "intl",
    timeout: float = DEFAULT_TIMEOUT,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    if not region.strip():
        raise PriceQueryError("invalid_region", "region must not be empty.")
    site_config = _get_site_config(site)
    language = language or site_config["language"]
    if not language.strip():
        raise PriceQueryError("invalid_language", "language must not be empty.")

    menu = _request_json(
        site_config["menu_endpoint"],
        {"sign": "common", "language": language},
        timeout,
        opener,
    )
    resolved = resolve_product(product, menu)
    _check_region(resolved, region)

    url_path = str(resolved["urlPath"])
    product_payload = _request_json(
        site_config["product_endpoint"],
        {
            "urlPath": url_path,
            "tag": PRODUCT_TAG,
            "region": region,
            "tab": PRODUCT_TAB,
            "sign": "common",
        },
        timeout,
        opener,
    )
    effective_resource_spec_code = _normalize_requested_spec_code(resource_spec_code, url_path)
    specs = _extract_specs(product_payload, effective_resource_spec_code)
    return {
        "product": resolved.get("categoryName"),
        "region": region,
        "site": site.casefold(),
        "currency": site_config["currency"],
        "specifications": specs,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query Huawei Cloud international calculator prices.")
    parser.add_argument("--product", required=True, help="Product name, exact alias, or urlPath")
    parser.add_argument("--region", required=True, help="Huawei Cloud region, for example ap-southeast-1")
    parser.add_argument("--resource-spec-code", help="Exact resourceSpecCode to return")
    parser.add_argument(
        "--site",
        choices=("intl", "china"),
        default="intl",
        help="Pricing site (default: intl)",
    )
    parser.add_argument(
        "--language",
        help="menuInfo language; defaults to en-us for intl and zh-cn for china",
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="HTTP timeout in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = query_prices(
            product=args.product,
            region=args.region,
            resource_spec_code=args.resource_spec_code,
            language=args.language,
            site=args.site,
            timeout=args.timeout,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except PriceQueryError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
