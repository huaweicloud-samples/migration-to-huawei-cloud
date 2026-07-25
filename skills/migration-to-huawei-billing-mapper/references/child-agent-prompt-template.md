# Step 5 Child-Agent Prompt Template

Use this template when the parent session delegates Step 5 category work to a child session. The parent must replace every placeholder before spawning the child session.

## Required Placeholders

- `{{CATEGORY_NAME}}`: one of `Compute`, `Storage`, `Network`, `Database`, `Other`
- `{{USER_LANGUAGE}}`: the user's language for notes and rationale
- `{{INPUT_FILE}}`: usually `output/billing_matched.md`
- `{{CATEGORY_TABLE_MARKDOWN}}`: the exact category section or table that the child must process
- `{{DOC_REFERENCE_FILE}}`: usually `skills/migration-to-huawei-billing-mapper/references/product-docs.md`
- `{{DOC_CACHE_DIR}}`: usually `output/spec-docs/<category>/`
- `{{CATEGORY_OUTPUT_FILE}}`: recommended path such as `output/spec-results/<category>.md`

## Prompt Body

```text
You are the Step 5 child agent for the `{{CATEGORY_NAME}}` category in the source-cloud-to-Huawei-cloud billing migration workflow.

Your objective:
1. Work only on the `{{CATEGORY_NAME}}` category from `{{INPUT_FILE}}`.
2. Fetch the required official Huawei Cloud documentation pages for the Huawei Cloud products that appear in this category.
3. Save every fetched documentation page locally under `{{DOC_CACHE_DIR}}` before using it for any recommendation.
4. Produce the completed category result at `{{CATEGORY_OUTPUT_FILE}}`.

Execution context:
- User language for prose output: `{{USER_LANGUAGE}}`
- Product documentation reference file: `{{DOC_REFERENCE_FILE}}`
- Full matched inventory file: `{{INPUT_FILE}}`
- Category content to process:

{{CATEGORY_TABLE_MARKDOWN}}

Hard constraints:
- Do not process, edit, or comment on any category other than `{{CATEGORY_NAME}}`.
- Use only official Huawei Cloud documentation as evidence for product behavior, supported specs, and region support.
- Save the fetched official documentation pages locally before making recommendations.
- Verify target-region support against each row's `HWC Target Region` before recommending a Huawei Cloud spec.
- Keep the fixed English table headers intact.
- Keep `Recommendation Notes`, rationale text, and any added prose in `{{USER_LANGUAGE}}`.
- Do not invent Huawei Cloud products, specs, feature claims, or region support statements.
- If the existing `Huawei Cloud Product` cell is empty or unsupported by evidence, keep `Recommended Spec` empty and explain why in `Recommendation Notes`.
- Keep `Recommended Spec` concise. Put rationale in `Recommendation Notes`, not in the spec cell.
- Use one migration signal label at the start of each `Recommendation Notes` value: `🟢`, `🟡`, or `🔴`.
- Treat a serverless-to-fixed/provisioned mapping, in either direction, as `🟡` rather than `🟢` when it is a workable substitute, and explain the service-model and scaling difference. Use `🔴` instead when no defensible substitute exists.
- Before making a recommendation, run the service-region precheck for every non-empty `Huawei Cloud Product` row and its `HWC Target Region`:
  `uv run skills/migration-to-huawei-billing-mapper/scripts/check_service_region.py --product "<Huawei Cloud Product>" --region "<HWC Target Region>" --json`
- The precheck must resolve service codes only from `skills/migration-to-huawei-billing-mapper/data/code.json`. If the matched code has `global: true`, treat it as available without an API request. Otherwise, if the code exists in `skills/migration-to-huawei-billing-mapper/data/product-regions.json`, use that region list first; `all` matches every target region. Only codes absent from both local sources query the API Explorer endpoint catalog. A successful API response containing the target region means the service is available; a successful response without it means the service is unavailable. Request failures, timeouts, invalid JSON, or an unregistered service endpoint default to available and must be recorded as an API-check failure. An unmatched product name is `Skipped`, must be recorded, and must not result in an invented code.
- For `Unavailable`, leave `Recommended Spec` empty unless official documentation confirms a supported alternative in the same target region. Record the service code, target region, and precheck status in `Recommendation Notes` for every checked row.

Required workflow:
1. Identify the distinct Huawei Cloud products present in this category.
2. Run the service-region precheck for each product and target-region pair using `check_service_region.py` and `data/code.json`.
3. Read `{{DOC_REFERENCE_FILE}}`.
4. Fetch the needed official documentation pages for those products.
5. Save the fetched pages under `{{DOC_CACHE_DIR}}` using stable product-oriented filenames such as `ecs.md`, `evs.md`, or `rds-mysql.md`.
6. For each row, recommend the closest defensible Huawei Cloud spec by comparing source capacity and product model:
   - vCPU and memory
   - storage capacity, media type, IOPS, and throughput
   - bandwidth model and traffic model
   - database engine, edition, topology, and class
   - serverless or managed-service behavior differences
7. If the mapping is approximate, still fill `Recommended Spec` when defensible, but explain the difference in `Recommendation Notes`.
8. If no defensible recommendation exists, leave `Recommended Spec` empty and explain the blocker in `Recommendation Notes`.
9. Add a category-level rationale paragraph at the bottom:
   `**Recommendation rationale:** <2-3 sentences in {{USER_LANGUAGE}}>`
10. Append a short evidence section after the table so the parent session can audit the sources, including the service-region precheck result for each distinct product and target region.

Output requirements:
- Write the result to `{{CATEGORY_OUTPUT_FILE}}`.
- The file must contain only the processed `{{CATEGORY_NAME}}` section, not the full multi-category document.
- Preserve the existing table rows and add these columns if they are not already present:
  - `Recommended Spec`
  - `Recommendation Notes`
- Do not add `Availability` in this step.

Suggested output shape:

## {{CATEGORY_NAME}}

| # | Category | Source Product | Source Spec | Monthly (USD) | Qty | Source Est. Resource Count | Region | HWC Target Region | Notes | Huawei Cloud Product | Recommended Spec | Recommendation Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ... |

**Recommendation rationale:** ...

### Evidence
- `<local saved doc path>`: what this page confirmed
- `<local saved doc path>`: what this page confirmed

Completion checklist:
- Every referenced doc page was saved locally.
- Every non-empty `Huawei Cloud Product` row was reviewed.
- Region support was checked per row.
- `Recommendation Notes` begins with `🟢`, `🟡`, or `🔴`.
- The file at `{{CATEGORY_OUTPUT_FILE}}` is complete and limited to this category only.

When done, return a concise summary with:
- output file path
- saved documentation files
- unresolved rows that must remain unresolved and be reported by the parent without the parent completing their recommendation work
```
