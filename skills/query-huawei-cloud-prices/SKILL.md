---
name: query-huawei-cloud-prices
description: Use when users ask for current Huawei Cloud product prices, regional pricing, product specifications, or on-demand, monthly, and yearly prices. Resolve product names through the Huawei Cloud international calculator menu, query live product pricing, and filter by resourceSpecCode when provided.
---

# Huawei Cloud Price Query

Use the bundled Python helper for every price lookup. It queries a Huawei Cloud calculator site at runtime; the default site is the international portal. Do not invent prices or use a stale local price table.

## Workflow

1. Collect the product name or `urlPath` and the required Huawei Cloud region from the user. Ask for the region when it is missing.
2. If the user provides a region ID such as `ap-southeast-1`, run `scripts/query_prices.py` with `--product` and `--region`. This script accepts region IDs only and passes that ID to `productInfo`.
3. If the user provides a region display name or a fuzzy region description, run `scripts/find_region_id_by_name.py` with `--region-name`. This standalone script only reads `menuInfo.global` and prints the resolved region ID; it does not query product prices or call `query_prices.py`. Pass its output as `--region` to `query_prices.py`.
4. Use `--site intl` by default; use `--site china` when the user requests China site pricing. Add `--resource-spec-code` when the user gives an exact resource specification code.
5. The helper resolves products in this order: exact `urlPath`, exact `categoryName`, then a unique exact match in `associateList`. Matching is case-insensitive for Latin text. If no product or more than one product matches, report the candidates and ask the user to choose; do not guess.
6. The helper checks the product's `regionOnline.regionList` before requesting prices. Do not return prices for an unsupported region.
7. For ECS, a `resourceSpecCode` without an image suffix automatically matches the `.linux` variant. Pass `.windows` or `.byol` explicitly when that image variant is required. Other products use the supplied specification code unchanged.
8. Read the compact JSON result. Explain each returned specification using `productSpecSysDesc`, and present prices by `billingMode`: `ONDEMAND` (on-demand), `MONTHLY` (monthly), and `YEARLY` (yearly). A missing billing mode means that the API did not publish that plan; never fill it in by calculation.
9. Preserve `tiers` as tiered pricing. Do not reduce a tiered plan to one price.
10. The helper maps documented billing modes, usage factors, and measurement IDs to stable English values. Keep `resourceSpecCode` unchanged because it is the exact query identifier. Unknown codes remain unchanged.

## Output Rules

- The success JSON contains only `product`, `region`, `specifications`, `resourceSpecCode`, `productSpecSysDesc`, and compact price fields.
- The success JSON also contains `site` and `currency`: international returns `intl` and `USD`; China returns `china` and `CNY`.
- When a display name is used, pass the region ID printed by `find_region_id_by_name.py` to `query_prices.py`; the price JSON always contains the region ID sent to `productInfo`.
- Treat `amount` as the live site amount and use the returned `currency` in the natural-language answer. Do not convert between USD and CNY.
- Do not apply exchange rates, taxes, discounts, or usage estimates. On-demand amounts can be unit prices rather than a monthly total; show `usageFactor` and measure fields when present.
- Interpret mapped `measureUnit` and tier `unit` values as the price measurement, not as a currency conversion or a total-cost calculation.
- Keep the answer in the user's language while retaining API field names where they aid verification.
- Prices are reference quotations from the calculator and are not a final invoice amount.

For the documented parameter mappings and product specification codes, read [price-parameter-meanings.md](references/price-parameter-meanings.md).

## Command

```bash
python3 skills/query-huawei-cloud-prices/scripts/query_prices.py \
  --product ecs \
  --region ap-southeast-1 \
  --resource-spec-code s3.large.2
```

For a region display name or fuzzy region description:

```bash
python3 skills/query-huawei-cloud-prices/scripts/find_region_id_by_name.py \
  --region-name Singapore
# Use the printed region ID with query_prices.py --region.
```

For China site pricing:

```bash
python3 skills/query-huawei-cloud-prices/scripts/query_prices.py \
  --site china \
  --product ecs \
  --region cn-north-4 \
  --resource-spec-code s3.large.2
```

Omit `--resource-spec-code` to return all valid specifications. The command writes successful JSON to stdout. On failure it writes a JSON error object to stdout and exits non-zero; use the error message and details when explaining the problem.

The helper uses only Python's standard library and requires network access to the selected portal: `portal-intl.huaweicloud.com` for `intl` or `portal.huaweicloud.com` for `china`.
