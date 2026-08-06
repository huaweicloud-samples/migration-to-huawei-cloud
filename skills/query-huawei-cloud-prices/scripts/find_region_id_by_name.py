#!/usr/bin/env python3
"""Resolve a Huawei Cloud region display name to a region ID."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


MENU_ENDPOINTS = {
    "intl": "https://portal-intl.huaweicloud.com/api/calculator/rest/cbc/portalcalculatornodeservice/v4/api/menuInfo",
    "china": "https://portal.huaweicloud.com/api/calculator/rest/cbc/portalcalculatornodeservice/v4/api/menuInfo",
}
DEFAULT_LANGUAGES = {"intl": "en-us", "china": "zh-cn"}
DEFAULT_TIMEOUT = 20


class RegionResolveError(Exception):
    """An expected, user-actionable region resolution failure."""

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


def _request_json(endpoint: str, params: dict[str, str], timeout: float,
                  opener: Callable[..., Any] | None = None) -> dict[str, Any]:
    opener = opener or urlopen
    url = f"{endpoint}?{urlencode(params)}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "query-huawei-cloud-region/1.0"})
    try:
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status is not None and not 200 <= status < 300:
                raise RegionResolveError("http_error", f"Huawei Cloud calculator returned HTTP {status}.", {"url": url})
            body = response.read()
    except RegionResolveError:
        raise
    except HTTPError as exc:
        raise RegionResolveError("http_error", f"Huawei Cloud calculator returned HTTP {exc.code}.", {"url": url, "reason": str(exc.reason)}) from exc
    except (OSError, URLError, TimeoutError) as exc:
        raise RegionResolveError("network_error", "Could not reach the Huawei Cloud calculator API.", {"url": url, "reason": str(exc)}) from exc
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegionResolveError("invalid_json", "Huawei Cloud calculator returned invalid JSON.", {"url": url}) from exc
    if not isinstance(payload, dict):
        raise RegionResolveError("invalid_response", "Huawei Cloud calculator returned a non-object JSON response.", {"url": url})
    return payload


def _compact(value: Any) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value).casefold())


def resolve_region_id(region_name: str, menu_payload: dict[str, Any]) -> str:
    """Resolve a region ID or display name with exact/contains matching."""
    query = _compact(region_name)
    if not query:
        raise RegionResolveError("invalid_region_name", "region-name must not be empty.")
    region_map = menu_payload.get("global")
    if not isinstance(region_map, dict):
        raise RegionResolveError("invalid_menu", "The menu response does not contain a valid global region mapping.")

    candidates: list[tuple[int, str, str]] = []
    for code, display_name in region_map.items():
        code_text, name_text = str(code), str(display_name)
        compact_code, compact_name = _compact(code_text), _compact(name_text)
        if query == compact_code or query == compact_name:
            score = 0
        elif query in compact_name:
            score = 1
        elif compact_name in query:
            score = 2
        else:
            continue
        candidates.append((score, code_text, name_text))

    if not candidates:
        raise RegionResolveError("region_not_found", f"No region code or display name fuzzy-matches {region_name!r}.", {"region_name": region_name})
    best_score = min(item[0] for item in candidates)
    best = [item for item in candidates if item[0] == best_score]
    if len(best) > 1:
        raise RegionResolveError(
            "ambiguous_region",
            f"More than one region matches {region_name!r}; choose a more specific name.",
            {"region_name": region_name, "candidates": [{"region": code, "name": name} for _, code, name in best]},
        )
    return best[0][1]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve a Huawei Cloud region name to a region ID.")
    parser.add_argument("--region-name", required=True, help="Region ID or display name")
    parser.add_argument("--site", choices=("intl", "china"), default="intl")
    parser.add_argument("--language", help="menuInfo language; defaults by site")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        menu = _request_json(
            MENU_ENDPOINTS[args.site],
            {"sign": "common", "language": args.language or DEFAULT_LANGUAGES[args.site]},
            args.timeout,
        )
        print(resolve_region_id(args.region_name, menu))
        return 0
    except RegionResolveError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
