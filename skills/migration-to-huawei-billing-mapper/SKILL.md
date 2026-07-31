---
name: migration-to-huawei-billing-mapper
description: Use when users provide billing reports, Cost Management exports, or resource inventories from AWS, Microsoft Azure, or another source cloud and need to migrate to Huawei Cloud, including product matching, regional mapping, per-category sub-agent spec recommendation, and exportable migration inventory generation. Azure billing analysis in this skill accepts only preprocessable `.xlsx` workbooks.
---

# Source Cloud to Huawei Cloud Billing Migration

## Overview

9-step pipeline that converts a source-cloud billing file or resource export into a categorized, reviewed, Huawei-Cloud-matched inventory, an alternative-solution section, and an Excel export.

```text
Input: source-cloud billing file / resource inventory
  -> Step 1: Billing Source to Raw Markdown and Detect Source Cloud/Module
  -> Step 2: Categorize & Tabulate (agent analysis)
  -> Step 3: Review Categorized Output (agent review)
  -> Step 4: Product Matching (match_products.py + selected mapping CSV)
  -> Step 5: Spec Recommendation (tool discovery + per-category child agents + Huawei docs)
  -> Step 6: Availability Check (check_availability.py)
  -> Step 7: Review and Replace Unavailable Specs (agent review)
  -> Step 8: Alternative Solution Review (alternative-solutions.md)
  -> Step 9: Excel Export (export_excel.py)
Output: Final inventory MD with availability status and alternative solutions + single-sheet Excel
```

### Supported Source-Cloud Modules

During Step 1, detect the source cloud from the raw bill content and select one module. Keep that module consistent throughout the rest of the run:

| Source Cloud | Module Notes | Mapping CSV | Region Catalog |
| --- | --- | --- | --- |
| AWS | `references/source-clouds/aws.md` | `data/source-clouds/aws-hwc-product.csv` | Region IDs are described in the module and normalized against `references/regions.md` |
| Microsoft Azure | `references/source-clouds/azure.md` | `data/source-clouds/azure-hwc.csv` | `data/source-clouds/azure-regions.csv` |

AWS and Microsoft Azure are the source clouds with bundled modules in this version. If the source cloud is unsupported, do not silently select either mapping CSV. Clone the closest module only when the user wants the skill extended, add provisional mapping rows, and clearly mark assumptions as review-required migration hints rather than contractual pricing truth.

### Language Adaptation

Table column headers use English (fixed schema, scripts depend on them). All other output, including titles, descriptions, notes, rationale, and category labels, must use the same language as the user.

Required fixed headers:

- `#`
- `Category`
- `Source Product`
- `Source Spec`
- `Monthly (USD)`
- `Qty`
- `Source Est. Resource Count`
- `Region`
- `HWC Target Region`
- `Notes`

## Prerequisites

Detect and handle at runtime:

- `markitdown`
  Check: `pip show markitdown`
  Install: `pip install markitdown`
- `uv`
  Check: `which uv`
  Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- OCR stack, only when a PDF is empty or partially extracted by `markitdown`
  Check: `ocrmypdf --version`, `tesseract --list-langs`, `gs --version`
  Requirement: `eng` must exist; install `chi_sim` too when the bill may contain Chinese
  Install: see `references/ocr-billing-pdf.md`
- `hcloud CLI`
  Check: `which hcloud`
  Install: see https://support.huaweicloud.com/hcli/ . If unavailable, skip Step 6 and Step 7.
  Configure language: `hcloud configure set --cli-lang=cn`
  Verify: `hcloud configure list` shows `language: "cn"`
- `Aspose.Cells Python`
  Check: `uv run --with aspose-cells-python python -c "import aspose.cells"`
  Install: auto-installed by `uv run` in Step 9.
- Azure workbook preprocessing dependencies
  Check: `uv run --with pandas --with openpyxl python -c "import pandas, openpyxl"`
  The Azure preprocessor is `scripts/summarize_azure_billing.py` and is mandatory for Azure `.xlsx` input.

Check all prerequisites before starting. If `hcloud` is missing, note that Step 6 and Step 7 may both be skipped. If `hcloud` is present but not configured with `cli-lang=cn`, set it before Step 6 because this workflow depends on the current Chinese KooCLI command surface, including `DCS ListFlavors`.

## Workflow

> IMPORTANT: Run steps sequentially unless noted. Each step's output is the next step's input. All output files go to `output/`.

### Step 1: Billing Source to Raw Markdown

**Goal:** Convert the user-provided source-cloud billing or inventory file into raw Markdown text, then use that raw content to detect the source cloud and select the correct source-specific module. The Azure preprocessing gate applies only after the source has been identified as an Azure bill. Ordinary spreadsheets and non-Azure billing files continue through the shared conversion path.

After `output/billing_raw.md` is produced, determine whether the input comes from AWS, Microsoft Azure, or an unsupported source cloud, then load the correct source-specific hints, mapping CSV, and region-normalization data.

Detection signals:

- Product names or SKUs in the bill, such as `Amazon EC2`, `Virtual Machines`, or `Azure Blob Storage`
- Region formats, such as AWS `us-east-1` or Azure `southeastasia` / `Southeast Asia`
- Export format names, service namespaces, invoice branding, Azure resource IDs, or Cost Management fields

For an Excel workbook, perform a lightweight header/content inspection before choosing the parser. Strong Azure billing evidence includes several fields such as `Meter Category`, `Meter Sub Category`, `Region`, `Resource URI`, `Term And Billing Cycle`, `Usage Quantity`, `Unit`, and `Total Sales Price (...)`, or clear Azure resource and Cost Management identifiers. A generic table, inventory workbook, or spreadsheet containing only common columns such as `Name`, `Region`, `Quantity`, or `Cost` is not Azure by default and must continue through the general spreadsheet path.

Use the selected module only for source-cloud-specific parsing, alias recognition, traffic normalization hints, and product mapping CSV selection. The rest of the pipeline remains shared.

**Azure input gate (mandatory after Azure detection).** First inspect the input using the normal source-cloud detection signals above. Do not classify a file as Azure merely because it is a spreadsheet or contains generic cost columns. When the evidence identifies Microsoft Azure, do not use `markitdown`, PDF OCR, CSV parsing, or direct Markdown normalization as an alternative. The only accepted Azure billing input is an `.xlsx` workbook, and it must be preprocessed before any categorization:

```bash
mkdir -p output/azure_billing_summary
uv run skills/migration-to-huawei-billing-mapper/scripts/summarize_azure_billing.py \
  <azure-billing.xlsx> \
  --output-dir output/azure_billing_summary
```

The preprocessor reads every worksheet and emits one summarized CSV per worksheet. It validates the required Azure billing columns, the `Total Sales Price` column, numeric `Usage Quantity` and price values, and consistent `Unit` values within each grouping. Treat any non-zero exit status as a blocking failure. Do not continue to Step 2, do not attempt OCR or another parser, and tell the user that Azure analysis was stopped because the workbook could not be preprocessed; include the command's concrete error. Do not claim that an Azure result was produced.

After preprocessing succeeds, read every CSV in `output/azure_billing_summary/` and combine their detailed rows into `output/billing_raw.md`. Preserve the worksheet origin in the raw content or notes so that each row remains traceable. The summarized CSVs, rather than the original workbook's unvalidated contents, are the input to Step 2.

Each summarized CSV combines the Azure `Meter Category` and `Meter Sub Category` values into one `Category (Sub Category)` column, for example `Compute (Virtual Machines)`. The source workbook still requires both input columns, and grouping remains distinct by both values.

If the source has been identified as Azure and the input is not `.xlsx`, stop immediately with a message that Azure billing analysis currently accepts Excel `.xlsx` workbooks only. A file extension alone is not sufficient: an unreadable, empty, malformed, or structurally incompatible workbook also fails the gate. If the input is a normal table or a billing file from another source cloud, do not apply this Azure gate; use the general conversion and source-cloud detection path instead.

**Use `markitdown` as the default converter for non-Azure supported inputs:**

```bash
mkdir -p output
markitdown <user-provided-billing-file> > output/billing_raw.md
```

Do not infer that the source must be a PDF from the use of `markitdown`. For non-Azure inputs, the command may receive supported spreadsheet, document, presentation, web, text, image, or other billing-export formats. Inspect the installed `markitdown` version when format support is uncertain. Do not pass an identified Azure workbook through this generic branch.

**OCR fallback path for scanned or partially extractable PDFs.** If `markitdown` produces empty output, obvious parsing errors, or only a partial first-page summary, generate a searchable PDF with a text layer by using forced OCR and rerun `markitdown` on that new PDF. See `references/ocr-billing-pdf.md`.

Recommended pipeline:

```text
original scanned PDF
  -> render each page to image
  -> tesseract OCR
  -> searchable PDF (image background + text layer)
  -> markitdown searchable.pdf
  -> output/billing_raw.md
```

Requires an OCR stack when OCR is needed. Before running OCR, verify that `ocrmypdf`, `tesseract`, the required language packs, and `gs` are all available. For macOS, Ubuntu / Debian, and Windows install commands, see `references/ocr-billing-pdf.md`.

Use this decision tree:

1. Identify the source cloud from the content and format signals. If it is Azure, apply the Azure input gate above before conversion. For an ordinary table or non-Azure input, run `markitdown` directly when the format is supported. For already clean Markdown or plain structured text, direct normalization is also acceptable.
2. Inspect `output/billing_raw.md`.
3. Treat direct extraction as `FAIL` if any of these are true:
   - The file is empty or `markitdown` errors
   - The output is suspiciously short relative to the source, or contains mostly summary text instead of billing detail
   - The output contains branding and totals but not detailed usage rows, service sections, regions, quantities, or SKU-like descriptions
4. If a failed or incomplete non-Azure input is a PDF, run `ocrmypdf --force-ocr --deskew --rotate-pages -l chi_sim+eng input.pdf output/billing_searchable.pdf`, then rerun `markitdown`.
5. If a failed or incomplete non-Azure input is not a PDF, use a format-appropriate structured parser or normalize the source directly when practical; otherwise ask for another supported export. Azure does not enter either fallback branch: preprocessing failure is terminal.
6. Treat forced OCR as the default OCR mode once a non-Azure PDF enters the OCR branch, because billing PDFs often contain vector pages that otherwise get skipped or only partially extracted.

**Verify output** before proceeding:

- It is non-empty
- It contains recognizable source-cloud product names from the selected module
- For paginated inputs, it includes detailed line-item content beyond the first summary page
- It contains enough structure to recover per-service usage, amount, quantity, and region clues

Examples:

- AWS: `EC2`, `S3`, `RDS`, `Lambda`, `us-east-1`, Cost Explorer / CUR fields
- Microsoft Azure after preprocessing: `Meter Category`, `Meter Sub Category`, `Region`, `Resource URI`, `Usage Quantity`, `Total Sales Price`

If non-Azure PDF OCR plus `markitdown` still fails, or a non-PDF format cannot be converted or normalized reliably, ask the user for another supported billing export, pricing export, structured resource inventory, or screenshots. For Azure, report the preprocessing failure and stop; ask the user to provide a valid `.xlsx` workbook only if they want to retry.

**Output:** `output/billing_raw.md`

---

### Step 2: Categorize and Tabulate

**Goal:** Analyze the raw Markdown, identify all source-cloud resources, determine the source region for each billing line item, merge duplicates of the same product + spec + region combination, and organize into 5 category tables.

**Agent-driven step.** Read `output/billing_raw.md` in full and the selected source module in `references/source-clouds/`.

#### 2.1 Parse, Assign Region, and Categorize

Parse each billing line item and determine which source-cloud region that specific line belongs to. Do not treat region extraction as a separate document-level preprocessing step if the line items already contain enough information.

For each line item:

- If the row explicitly contains a source region, use it directly
- If the row does not explicitly contain a region but its surrounding context clearly scopes it to a region, inherit that scoped region for that row
- If the row's region truly cannot be determined, leave the source region as unknown during parsing, then default its `HWC Target Region` to `ap-southeast-3` and add a note explaining the fallback

Normalize each resolved source region with the selected source module, then map it to the geographically nearest Huawei Cloud region using `references/regions.md`. For Azure, accept both display names and programmatic names from `data/source-clouds/azure-regions.csv`; do not treat `global` or an empty `ResourceLocation` as a physical region.

After region assignment, group all line items by **(Source Product, Source Spec, Region)**. Sum quantities and monthly cost. Do not merge resources across different regions.

**Categorization is a hard rule based on service nature, not on the source-cloud brand.**

| Category | Criterion | Cross-cloud examples (non-exhaustive) |
| --- | --- | --- |
| **Compute** | CPU / memory compute capacity, virtual machines, containers, serverless runtimes | EC2, EKS, Lambda, Azure Virtual Machines, AKS, Azure Functions, App Service |
| **Storage** | Persistent data storage, object, block, file, archive, backup | S3, EBS, EFS, Azure Blob Storage, Disk Storage, Azure Files, Azure Backup |
| **Network** | Connectivity, traffic distribution, DNS, CDN, private link, egress / transfer | ELB, NAT Gateway, CloudFront, Azure Load Balancer, Application Gateway, Private Link, Front Door, Data Transfer |
| **Database** | Managed databases, caches, warehouses, migration tooling | RDS, Aurora, ElastiCache, Azure SQL, Cosmos DB, Azure Database for PostgreSQL, Azure Managed Redis |
| **Other** | Security, observability, messaging, analytics, governance, identity, devtools, AI | IAM, CloudWatch, SNS, Entra ID, Azure Monitor, Sentinel, Service Bus, Synapse Analytics, Azure DevOps |

**Decision rule:** classify by the service's primary function. When a service is ambiguous, classify by the dominant buyer intent in the bill. Examples: container registry -> Storage, API gateway -> Network, database migration tooling -> Database.

#### 2.2 Output File

The output file must start with metadata, followed by the tables:

```markdown
# Cloud Billing Inventory

> **Source Cloud:**
> **Total Monthly:**

---

## Compute

| # | Category | Source Product | Source Spec | Monthly (USD) | Qty | Source Est. Resource Count | Region | HWC Target Region | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Compute | Compute Engine | n2-standard-4 (4vCPU 16GB) | $150.00 | 744 Hrs | ≈1 | us-central1 | la-north-2 | |
```

Rules:

- **Merge rule:** if `Source Product + Source Spec + Region` are identical, combine them into one row
- **Traffic-cost normalization rule:** before merging, normalize only the explicitly supported traffic labels for this version instead of trying to collapse every network-byte charge
- Within each source `Region`, consolidate all non-NAT transfer components into exactly one ordinary row with `Source Product = Data Transfer`; outbound/egress and cross-region amounts or breakdowns belong in `Notes`, not separate rows or `Source Spec`
- For a multi-region customer, repeat the ordinary Data Transfer aggregate once per `Region`; rows in different regions do not violate the consolidation rule
- When NAT is present in a region, keep its processed-traffic charge as exactly one additional `Source Product = Data Transfer` row for that same region, so that region has two Data Transfer rows in total: one ordinary aggregate and one NAT processed aggregate
- Do not automatically fold CDN, provisioned bandwidth, or other network-product charges into `Data Transfer`; the specific exception is a row whose charge is semantically outbound/egress or cross-region transfer, which belongs in the ordinary Data Transfer aggregate
- Keep gateway or load-balancer runtime-hour charges as standalone resources if they are instance-hour or provisioned-appliance style charges
- **Source Est. Resource Count:** estimate only for clear runtime-hour style countable resources; otherwise `—`
- The `HWC Target Region` column must contain exactly one Huawei Cloud region per row
- If a product has no discernible spec, leave `Source Spec` as `—`
- If price is free tier or promotional zero, still include it explicitly
- Category labels and section titles must follow the user's language; fixed schema headers stay in English

**Output:** `output/billing_categorized.md`

---

### Step 3: Review `billing_categorized.md`

**Goal:** Review the generated `output/billing_categorized.md` against the full Step 2.2 rules before Huawei Cloud matching begins.

Step 3 is a blocking gate. Do not continue to Step 4 until both the validator and the manual review pass.

#### 3.1 Run Blocking Validator First

Run:

```bash
uv run skills/migration-to-huawei-billing-mapper/scripts/validate_categorized.py \
  --input output/billing_categorized.md
```

The validator checks rule-shaped constraints such as:

- Fixed English table schema
- Exactly one `Region` and one `HWC Target Region` per row
- Duplicate `Source Product + Source Spec + Region` tuples
- Required cell presence
- Non-hourly rows incorrectly using non-`—` resource counts
- `Category` column staying consistent within each section; section titles themselves may be localized
- Supported traffic-normalization rows (`Data Transfer` and NAT processed traffic) that were not normalized to `Source Product = Data Transfer`
- A `data transfer` phrase in `Source Spec` alone does not trigger normalization for another product such as CDN; NAT processed labels in `Source Spec` remain checked
- Data Transfer consolidation count per `Region`: one ordinary row without NAT in that region, or one ordinary row plus one NAT processed row when NAT is present there; different regions may repeat this structure
- Outbound/egress and cross-region transfer details left as separate rows or left in `Source Spec`
- `Monthly (USD)` formatting

If the validator reports any `FAIL`, edit `output/billing_categorized.md` in place and rerun it. Do not proceed while any validator failure remains.

#### 3.2 Perform Manual Review Against Step 2.2

Manual review should focus only on the judgment-based checks that the validator cannot prove. Review each of the following explicitly:

- Semantic merge correctness: rows were not incorrectly merged across different regions or unlike resources even if no exact duplicate tuple remains
- Traffic-cost normalization follows the Step 2.2 rule in full, not just the validator's keyword check
- Within each `Region`, non-NAT transfer charges were consolidated into one ordinary `Data Transfer` row, with outbound/egress and cross-region details preserved in `Notes`
- NAT processed traffic was consolidated into one additional `Data Transfer` row only in each region where NAT is present, and was not mixed into the ordinary aggregate
- CDN were not force-merged into `Data Transfer` by overbroad normalization
- Runtime-hour NAT gateway or load-balancer rows were preserved as standalone resources when they are appliance/runtime charges rather than traffic charges
- For hourly rows, `Source Est. Resource Count` is used only where the row is clearly a countable runtime-hour resource; otherwise `—`
- `Source Spec` uses `—` when the spec is truly not discernible instead of being guessed or left semantically ambiguous
- Free tier or promotional zero-cost rows were kept instead of dropped
- Category assignment follows the hard categorization rule from Step 2.1 rather than loose intuition
- Category labels follow the user's language, and section titles may be localized; fixed schema headers remain English
- The selected source-cloud module was used consistently for parsing assumptions, aliases, and region interpretation

#### 3.3 Required Review Discipline

The review is invalid unless all of the following are true:

- Every review item is evaluated as explicit `PASS` or `FAIL`
- Every `FAIL` cites the exact row number or metadata line and the concrete issue
- If any `FAIL` exists, `output/billing_categorized.md` is corrected in place
- After edits, the validator is rerun and the manual checklist is evaluated again
- Only an all-`PASS` second pass may continue to Step 4

Examples of invalid Step 3 behavior:

- “Reviewed the file and it looks fine”
- Listing generic concerns without row references
- Running the validator once, seeing failures, and continuing anyway
- Checking only schema and skipping the manual traffic-normalization or categorization review

If any violation exists, modify `output/billing_categorized.md` in place. Do not create a second reviewed file.

**Input:** `output/billing_categorized.md`

**Output:** `output/billing_categorized.md`

---

### Step 4: Match Huawei Cloud Products

**Goal:** For each source-cloud product in the categorized table, find the corresponding Huawei Cloud product using the selected source-specific CSV mapping.

**Script:** `uv run skills/migration-to-huawei-billing-mapper/scripts/match_products.py`

**Command shape:**

```bash
uv run skills/migration-to-huawei-billing-mapper/scripts/match_products.py \
  --input output/billing_categorized.md \
  --csv <selected-source-mapping.csv> \
  --output output/billing_matched.md
```

For AWS, pass `data/source-clouds/aws-hwc-product.csv`. For Microsoft Azure, pass `data/source-clouds/azure-hwc.csv`. The source-cloud decision made in Step 1 controls this argument; do not choose a CSV based on an individual row that merely resembles another provider's product name.

**Script behavior:**

- Parses Markdown tables from input
- Loads the selected mapping CSV
- Requires fixed headers `#`, `Source Product`, and `Source Spec`
- For each source product, finds matching Huawei Cloud product
- Exact and keyword-overlap matches are preferred
- Multiple matches are newline-separated in the cell
- No match leaves the cell empty
- Adds the `Huawei Cloud Product` column

**Mandatory matching restriction:**

- Do not invent, guess, synthesize, or hallucinate a Huawei Cloud product name in Step 4
- Do not fill the `Huawei Cloud Product` cell from general intuition, architectural similarity, or downstream Step 5 documentation review alone
- Only keep a product in `Huawei Cloud Product` if it comes from the selected mapping CSV or another explicitly verified mapping source added to this workflow
- If there is no reliable mapping evidence for a row at Step 4, leave `Huawei Cloud Product` empty
- It is acceptable and expected for some rows to remain blank at this stage

**Output:** `output/billing_matched.md`

---

### Step 5: Recommend Specifications

**Goal:** For each matched Huawei Cloud product, look up the product documentation and recommend the closest equivalent spec.

**Agent-driven step.** Read `output/billing_matched.md`, first find the appropriate tool for creating child sessions, then split the work by category table (`Compute`, `Storage`, `Network`, `Database`, `Other`), and spawn one child session per non-empty category.

> **Non-negotiable sub-agent rule:** Step 5 must use sub-agents whenever at least one non-empty category exists. This requirement does not depend on perceived complexity: it still applies when the inventory has only one category or one row, the recommendation looks obvious, the expected product or spec is already familiar, or the required documentation is readily available. A task looking simple is never a reason for the parent session to perform specification recommendation itself or skip spawning the required category sub-agent.

#### 5.0 Find the Sub-Agent Tool First

Before delegating any category work:

- Search the currently available tools for sub-agent or child-session support
- Select the tool that can explicitly create child agents and let the parent coordinate them
- Do not start category recommendation work until the child-session creation tool has been identified

Document the decision briefly in the working notes so it is clear which tool was used for Step 5 delegation.

#### 5.0.1 Enforce the Parent-Session Boundary

When a child-agent tool is available, the parent session must not query Huawei Cloud specifications, write category recommendations, or complete any category result on a child's behalf. This separation keeps every recommendation attributable to the child session that collected and reviewed its supporting documentation.

The parent session may only:

- Read `output/billing_matched.md` to identify which top-level categories are non-empty and extract their exact tables
- Instantiate the required child-agent prompt for each non-empty category
- Spawn and coordinate the child sessions
- Check that each expected category output exists and follows the required structure
- Merge the completed child outputs into `output/billing_with_specs.md` without adding, rewriting, or resolving recommendations

Every non-empty top-level category must have its own child session. Do not combine multiple categories in one child session, omit a non-empty category, or let the parent session act as the child for a category. If no child-agent tool is available or a required category child cannot be created, stop Step 5 and report the blocker; the parent must not perform that category's recommendation work as a fallback.

Determine whether to spawn category sub-agents solely from whether each category is non-empty, never from how easy, short, repetitive, or self-evident its recommendation work appears.

#### 5.0.2 Instantiate the Child-Agent Prompt Template

Use `references/child-agent-prompt-template.md` as the required prompt skeleton for each Step 5 child session. Do not write ad hoc child prompts when delegating category work.

Before spawning a child session, the parent must replace every placeholder in the template with concrete values:

- `{{CATEGORY_NAME}}`: one of `Compute`, `Storage`, `Network`, `Database`, `Other`
- `{{USER_LANGUAGE}}`: same language as the user
- `{{INPUT_FILE}}`: usually `output/billing_matched.md`
- `{{CATEGORY_TABLE_MARKDOWN}}`: the exact category section or table assigned to that child
- `{{DOC_REFERENCE_FILE}}`: `skills/migration-to-huawei-billing-mapper/references/product-docs.md`
- `{{CATEGORY_OUTPUT_FILE}}`: recommended category result path such as `output/spec-results/compute.md`

Parent-session rules for template usage:

- Pass only one top-level category per instantiated prompt
- Inline the exact category table content in `{{CATEGORY_TABLE_MARKDOWN}}` so the child scope is explicit
- Require the child to fetch and review official docs before making recommendations
- Require the child to write only its category result file, not the final merged document
- Keep a predictable per-category result layout such as:

```text
output/spec-results/
  compute.md
  storage.md
  network.md
  database.md
  other.md
```

Child-session workflow requirements:

- Each spawned child session is responsible only for one category table
- Each non-empty top-level category gets exactly one child session
- Each child session must first collect the required official Huawei Cloud documentation pages for the products in its category
- Use `WebFetch` or an equivalent page-fetching tool to retrieve the documentation content
- Do not save fetched product documentation to local files during this step
- Record the official documentation URLs and summarize the relevant evidence in the category result
- After documentation is fetched and reviewed, the child session continues with Step 5.2 for only that category
- The parent session remains responsible for combining all category outputs back into one final `output/billing_with_specs.md`, but must preserve the child-authored recommendation content unchanged

#### 5.1 Look Up Documentation

Before looking up documentation or recommending a spec, perform the mandatory service-region precheck for every row with a non-empty `Huawei Cloud Product` and `HWC Target Region`.

Run:

```bash
uv run skills/migration-to-huawei-billing-mapper/scripts/check_service_region.py \
  --product "<Huawei Cloud Product>" \
  --region "<HWC Target Region>" \
  --json
```

The script reads `data/code.json`, resolves the Huawei Cloud product name to its service code, and applies these checks in order:

1. If the code entry has `"global": true`, treat the service as available in every region without making an API request.
2. If the code exists as a key in `data/product-regions.json`, use that list as the authoritative supported-region list without making an API request. The special region value `all` matches every target region.
3. Otherwise, call:

```text
https://console-intl.huaweicloud.com/apiexplorer/new/v1/endpoints/{code}/search?offset=0&limit=50
```

For API-backed services, it considers the service available only when a successful response contains the target region in `endpoints[].region`. If the API request fails, times out, returns invalid JSON, or otherwise cannot be parsed, treat the service as available and record that the API check failed. This fallback is required because the service may not yet be registered in API Explorer. If the product name cannot be resolved from `data/code.json`, skip this API check for that row and record that it was skipped; do not invent a service code.

If the service-region result is `Unavailable`, do not recommend a spec for that row unless official documentation identifies a supported alternative in the same target region. Include the service code and region-check result in `Recommendation Notes`. `Skipped` and API-failure fallback results must also be recorded in the notes so later review can distinguish them from a confirmed regional match.

After this precheck, read `references/product-docs.md` for official Huawei Cloud documentation URLs. For each category child session:

- Identify all distinct Huawei Cloud products that appear in that category table
- Fetch and review the official documentation pages needed for those products
- Use the fetched documentation as the working reference set for the rest of Step 5; do not save product documentation locally

Use the official docs to verify:

- Instance types and flavors
- Storage tiers and performance levels
- Network or gateway bandwidth models
- Database engine versions and classes
- Region support and regional limitations

If the product is not listed in `product-docs.md`, search Huawei Cloud official documentation, fetch the relevant page, and cite the URL and limitation in the notes.

**Mandatory region support check:** the service-region precheck above is required before recommending any Huawei Cloud product or spec. Use official product documentation as the second source of evidence for product-specific regional limitations.

#### 5.2 Recommend Spec

Only start this step after the category child session has finished fetching and reviewing the required documentation pages.

Match `Source Spec` to the closest Huawei Cloud spec by comparing:

- vCPU count and RAM
- Storage capacity, IOPS, and throughput
- Bandwidth and connections
- DB engine, class, and edition
- Runtime model differences for serverless, managed messaging, analytics, and application-platform services

Add two columns:

- `Recommended Spec`
- `Recommendation Notes`

Rules:

- If exact equivalent exists, recommend it directly
- If only approximate, still fill `Recommended Spec` and explain the difference in `Recommendation Notes`
- If no match is possible, leave `Recommended Spec` empty and explain why
- If the product is unsupported in the target region, leave the spec empty or pick a documented alternative and state the limitation clearly
- Keep `Recommended Spec` concise and machine-readable; put explanatory prose in `Recommendation Notes`, not in the spec cell

**Mandatory clarity rule for non-1:1 mappings:** `Recommendation Notes` must explicitly state the migration signal using one of these labels:

- 🟢
- 🟡
- 🔴

Label semantics:

- 🟢: near like-for-like mapping; no major product-form mismatch is known from the reviewed docs
- 🟡: workable substitute exists, but there are product-model, feature, runtime, or operational differences that must be called out. For example, when one side is serverless and the other uses a fixed or provisioned specification, classify the mapping as 🟡 rather than 🟢, even if their functional scope or estimated capacity is otherwise close
- 🔴: no defensible native equivalent, or the region/support limitation is severe enough that redesign, self-managed deployment, or manual architecture change is required

For 🟡 or 🔴, explicitly describe what differs: service model, serverless semantics, autoscaling behavior, operations ownership, feature gaps, or required redesign.

At the bottom of each category table, add:

```markdown
**Recommendation rationale:** <2-3 sentences in the user's language explaining why these Huawei Cloud products were chosen and which rows need adaptation.>
```

Suggested wording patterns:

```markdown
Migration Signal: 🟡. Huawei Cloud <product> covers <core capability>, but does not provide a fully equivalent <source-cloud capability>. Key differences: <difference 1>; <difference 2>. Migration impact: <required change>.
```

```markdown
Migration Signal: 🔴. Huawei Cloud has no directly equivalent managed product for this source service in the reviewed scope, or the target region support is insufficient. Suggested path: deploy on ECS/CCE/self-managed components or redesign the architecture. Migration impact: additional implementation and operations effort are required.
```

**Output:** `output/billing_with_specs.md`

---

### Step 6: Check Availability

**Goal:** Verify that recommended specs are available in the target Huawei Cloud region and AZ before the final replacement pass.

**Script:** `uv run skills/migration-to-huawei-billing-mapper/scripts/check_availability.py`

**Command:**

```bash
uv run skills/migration-to-huawei-billing-mapper/scripts/check_availability.py \
  --input output/billing_with_specs.md \
  --output output/billing_with_availability.md
```

**Script behavior:**

- Parses tables and extracts non-empty `Recommended Spec` rows
- Requires the fixed English table schema from this skill
- Maps Huawei Cloud product types to the appropriate `hcloud` commands
- Queries spec availability using the row's `HWC Target Region`
- Only performs flavor/spec-level checks when `Recommended Spec` contains a machine-queryable exact code such as `s6.large.2`, `rds.mysql.*`, `gaussdb.*`, or `redis.*`
- For documentation-backed but non-queryable labels such as generic serverless, I/O, backup, storage, or placeholder bundle descriptions, marks `Availability = N/A` instead of forcing a `Flavor Not Found`
- For DCS Redis specs, uses `hcloud DCS ListFlavors --cli-region=<region> --spec_code=<redis.*>` rather than the older region-only `ListAvailableZones` fallback
- Marks `Available`, `Sold Out`, `Flavor Not Found`, `Unavailable`, `Not Detected`, or `N/A`
- Preserves the source-cloud columns and recommendation notes in the output

**Input:** `output/billing_with_specs.md`

**Output:** `output/billing_with_availability.md`

---

### Step 7: Review and Replace Unavailable Specs

**Goal:** Review `output/billing_with_availability.md`, confirm which rows truly need replacement, and only for non-sellable unresolved flavors find the closest defensible sellable substitute in the same Huawei Cloud product family and target region.

Read `output/billing_with_availability.md` in full. For every row with a non-empty `Huawei Cloud Product` or `Recommended Spec`, verify:

- The selected Huawei Cloud product family is correct for the source row
- The `Recommended Spec` actually exists in official documentation, or the label is a defensible documentation-backed recommendation
- The recommendation matches source-cloud resource characteristics closely enough for the stated mapping type
- The target region support statement is accurate
- `Recommendation Notes` use the correct `🟢` / `🟡` / `🔴` signal and do not overstate equivalence
- Language consistency is preserved: fixed schema headers remain English, while `Recommendation Notes`, replacement explanations, rationale text, and any newly added prose stay in the same language as the user
- The bottom-of-table rationale remains consistent with the reviewed rows

For rows whose `Availability` is `Sold Out`:

- Do not automatically replace the flavor
- Treat `Sold Out` as a state that may require capacity replenishment or a second confirmation rather than an immediate spec change
- Keep the current `Recommended Spec` unless documentation review makes it indefensible for another reason
- Add a note that the flavor was reported as `Sold Out` and requires manual recheck or secondary confirmation before replacement is considered

#### 7.1 Mandatory Replacement Search Protocol

For any row that truly needs a substitute, do not jump directly to a guessed replacement. First build a candidate pool, then rank it.

Candidate-pool rules:

- Reuse the official documentation URLs and evidence recorded in the Step 5 category result before searching again
- Extract the row's baseline attributes from `Source Spec`, `Recommended Spec`, and `Recommendation Notes`: topology, vCPU, RAM, capacity, storage class, engine, edition, bandwidth class, cache mode, and whether the service is serverless or provisioned
- Query the same Huawei Cloud product family for sellable candidates in the exact `HWC Target Region`
- Prefer machine-queryable product-family APIs when available, then use official documentation to confirm semantics
- Typical candidate queries in the current workflow:
  - ECS / BMS: list flavors in-region and filter by flavor code or family
  - RDS / TaurusDB / GaussDB: query in-region flavors by `spec_code`, engine, and edition
  - DCS Redis: use `hcloud DCS ListFlavors --cli-region=<region> --spec_code=<redis.*>` and related engine/mode filters when broadening the search
- Keep a short explicit shortlist of 2-5 candidates in working notes before choosing one

Ranking rules for the shortlist:

- Preserve product family first; do not switch Huawei Cloud products unless the current family is proven indefensible
- Preserve deployment topology before raw size similarity: single vs HA, cluster vs proxy, serverless vs provisioned, shared-storage vs local-storage, etc.
- Preserve engine / edition / cache mode before capacity tuning
- Prefer exact or minimally larger CPU, RAM, and capacity matches; do not silently downsize a workload-critical dimension
- When no exact or upward-close candidate exists, pick the least-risk substitute and explicitly state the downgrade or model mismatch
- Prefer candidates that remain machine-queryable and can be rechecked by Step 6

Mandatory replacement discipline:

- Do not use a generic placeholder such as `DCS 固定规格实例`, `TaurusDB 共享存储 (按量)`, or similarly non-specific labels as if it were a sellable substitute
- If the only defensible recommendation is a service-model statement rather than a concrete sellable flavor, leave the row unresolved or `N/A` instead of pretending a replacement was found
- If the source service is serverless and Huawei Cloud only offers provisioned capacity, estimate a conservative floor from the observed billed capacity first; if that floor still cannot support a concrete substitute, keep the row unresolved with a `🟡` or `🔴` note
- Do not mark the step complete immediately after editing one row; finish the full unresolved set, then rerun Step 6 as required

For rows whose `Availability` is `Flavor Not Found` or `Unavailable`:

- Search the same product family's official documentation for the closest sellable substitute in the same `HWC Target Region`
- Prefer the nearest flavor by vCPU, RAM, storage class, bandwidth class, engine class, edition, and deployment topology
- Keep the substitute within the same product family whenever possible; do not switch Huawei Cloud products casually
- Update `Recommended Spec` and `Recommendation Notes` to explain that the original flavor was not sellable and why the replacement was chosen
- The replacement note is mandatory and must explicitly mention the original spec, the replacement spec, the reason for replacement, and the fact that the replacement was rechecked to `Available`
- Re-run Step 6 after replacement until the revised row is confirmed `Available`, or until no defensible sellable substitute can be found

For rows whose `Availability` is `Not Detected`:

- Do not claim sellability
- Keep the recommendation only if it remains documentation-backed
- Add a note that availability could not be verified in the current environment

For rows whose `Availability` is `N/A`:

- Treat the row as documentation-backed but not machine-verifiable in the current Step 6 checker
- Do not rewrite `N/A` to `Available`, `Sold Out`, or `Flavor Not Found` manually unless you have a product-specific API or an explicit documented sellability source
- Keep the recommendation only if it remains documentation-backed, and explain any limitation in `Recommendation Notes` when needed

If no defensible sellable substitute exists:

- Leave the best documentation-backed recommendation in place or clear `Recommended Spec` if the recommendation is no longer defensible
- State clearly in `Recommendation Notes` that no sellable substitute was confirmed for the target region

If `hcloud` is unavailable in the current environment:

- Step 6 and Step 7 may both be skipped
- Do not claim sellability or availability-based replacement
- Keep only documentation-backed recommendations and note that availability was not verified

This step is complete only when:

- All `Available` rows remain justified
- Every `Flavor Not Found` or `Unavailable` row has either been replaced with an `Available` substitute or explicitly documented as unresolved
- Every `Sold Out` row is explicitly documented for second confirmation instead of being auto-replaced
- All Step 7-added notes, replacement explanations, and rationale text remain language-consistent with the user-facing output rules of this skill
- The final file reflects the post-replacement availability result

If anything is unsupported, overstated, region-incompatible, or unclear, modify the working file in place and rerun Step 6 as needed. The final reviewed result must be written to `output/billing_final.md`.

**Input:** `output/billing_with_availability.md`

**Output:** `output/billing_final.md`

---

### Step 8: Review Alternative Solutions

**Goal:** After the direct product/spec recommendation and availability review are complete, identify resources whose direct migration is too different, unavailable, or uneconomical at the observed usage level, and add evidence-backed alternative paths to the final Markdown report.

**Reference guide:** `skills/migration-to-huawei-billing-mapper/references/alternative-solutions.md`

This is an agent-driven review step. Read the full `output/billing_final.md` and the reference guide before editing. Review every row with one or more of the following signals:

- `Recommendation Notes` begins with `🟡` or `🔴`
- `Availability` is `Unavailable`, `Flavor Not Found`, or `Not Detected`, or service-region support could not be confirmed
- The source service is serverless but the direct target is fixed/provisioned, or the reverse
- The direct target requires self-managed deployment, significant data-model/application changes, or a large operational burden
- The observed usage is small enough that a lower-cost or simpler Huawei Cloud service may satisfy the stated business need

Do not generate an alternative for every row. A `🟢` near like-for-like mapping normally needs no alternative. Do not infer “high cost” from the source product name alone: use `Monthly (USD)`, `Qty`, resource count, source spec, observed capacity, and the direct recommendation notes. If utilization, retention, throughput, RTO/RPO, or compliance requirements are missing, record the missing business input as a validation item instead of claiming a cost saving.

#### 8.1 Review and Evidence Rules

For each candidate:

1. Extract the required business capability from the source row: throughput, latency, persistence, ordering, retry/dead-letter behavior, HA, elasticity, data volume, connections, compliance, and operations ownership.
2. Compare the direct recommendation with the source service model and actual scale. Include “keep the direct recommendation” as one candidate path.
3. Use only patterns supported by `references/alternative-solutions.md` and official Huawei Cloud documentation. Fetch any missing official pages before writing the recommendation, but do not save product documentation locally.
4. Prefer the smallest architecture that preserves the required capability. Record at least the key migration impact, function gap, application changes, operations changes, cost dimensions to recalculate, and validation work.
5. Mark the alternative `🟡` when it is workable but needs application or operations adaptation; mark it `🔴` when no defensible managed equivalent exists or redesign/self-management is required.

The guide's example is mandatory to apply carefully: low-volume serverless messaging may use DCS Redis as a lightweight buffer only when short retention and application-managed acknowledgement/retry are acceptable. DCS Redis must not be described as a serverless MQ or full MQ equivalent. When durable retention, strict ordering, consumer groups, dead-lettering, audit replay, or high throughput is required, evaluate DMS for Kafka/RabbitMQ or leave the resource unresolved for specialist review.

#### 8.2 Required Report Section

Append the alternatives after all category tables and their recommendation rationales in `output/billing_final.md` under exactly one independent section:

```markdown
## 替代方案参考

### 方案 1：<源产品/资源> 的替代路径

- **触发资源**：<Category / # / Source Product / Source Spec / Region>
- **触发原因**：<差异过大、目标区域不可用、成本过高或其他可核验原因>
- **直接迁移结论**：<保留推荐 / 不建议直接迁移 / 待确认>
- **建议方案**：<Huawei Cloud 产品或组合，以及核心架构变化>
- **适用前提**：<吞吐、数据量、持久性、HA、延迟、合规等前提>
- **主要差异与改造**：<服务模型、功能缺口、应用改造、运维责任>
- **成本判断**：<成本方向和需重新测算的计费项，不虚构价格>
- **风险与验证**：<PoC、压测、故障演练、数据校验或业务确认项>
- **证据**：<官方文档 URL>
- **迁移信号**：🟡 / 🔴
```

Use the user's language for all prose in this section. Keep the fixed inventory table headers unchanged. Preserve the original resource row and `Monthly (USD)` values; an alternative is an additional decision aid, not a replacement of billing data. A single subsection may group rows from the same migration pattern, but must list every triggering row number and region. Give at most one recommended alternative and two brief fallback directions per subsection. If no defensible alternative exists, add a subsection stating that the resource remains unresolved and why.

The final Markdown report must contain the section even when no row qualifies, using:

```markdown
## 替代方案参考

暂无需要单独设计替代方案的资源。现有直接迁移建议均已完成可用性复核，或缺少足够的业务容量/合规信息进行安全替代判断。
```

**Input:** `output/billing_final.md` after Step 7 review

**Output:** `output/billing_final.md` with the appended `## 替代方案参考` section

### Step 9: Export Excel

**Goal:** Export the final Markdown inventory, including its alternative-solution section, to a single-sheet Excel workbook.

Excel layout requirements:

- The workbook stays single-sheet
- The file title should be written as a merged row spanning the effective table width
- Metadata blockquote lines near the top of the Markdown should be exported as merged full-width rows so `Source Cloud`, `Total Monthly`, and similar summary fields are easy to read and edit
- Each category's `**Recommendation rationale:** ...` paragraph should be exported immediately after that category table as a merged full-width row
- The `## 替代方案参考` section and its bullet paragraphs should be exported after the category tables as merged full-width rows; the section is report content, not an inventory table
- Table headers and resource rows remain unmerged regular cells
- Column widths should adapt to their contents within a readable minimum and maximum; long values should wrap instead of creating excessively wide columns
- Every content row, including merged metadata and rationale rows, should adapt its height to the wrapped content
- Table header rows should retain enough minimum height for wrapped multi-line labels to remain fully visible
- Mixed Chinese/English recommendation text should use its displayed character width when calculating wrapped lines so the resulting row height does not clip content

**Script:** `uv run skills/migration-to-huawei-billing-mapper/scripts/export_excel.py`

**Command:**

```bash
uv run skills/migration-to-huawei-billing-mapper/scripts/export_excel.py \
  --input output/billing_final.md \
  --output output/billing_final.xlsx
```

**Output:** `output/billing_final.xlsx`

## Region Handling

- Extract the source region per billing row from the row itself or its immediate billing context
- Normalize the value with the selected source module before comparing geography; for Azure, use the preprocessed `Region` value and `data/source-clouds/azure-regions.csv` to resolve both display and programmatic names
- Map that row to the nearest Huawei Cloud region using `references/regions.md`
- If a specific row has no determinable region, default to `ap-southeast-3` with an explicit note
- Do not collapse multiple source regions into a single row; apply the Data Transfer consolidation rule independently within each source region

## Error Handling

- After Azure is positively identified, require a `.xlsx` workbook and a successful `scripts/summarize_azure_billing.py` run before Step 2; any Azure preprocessing failure is terminal
- Do not reject an ordinary spreadsheet solely because it is not an Azure billing workbook; route it through the general supported-input conversion path
- If `markitdown` fails or produces incomplete output for non-Azure input, first distinguish PDF inputs from other supported formats
- For non-Azure PDF inputs only, switch to the searchable-PDF OCR path in Step 1; for other non-Azure inputs, use format-appropriate structured normalization or request another supported export
- If non-Azure PDF OCR plus `markitdown` still fails, ask for a structured export instead
- If Step 3 or Step 7 finds inconsistencies, correct the file in place before continuing
- If Step 8 finds a high-risk or high-cost direct mapping, append the evidence-backed alternative section to `billing_final.md`; do not overwrite the original inventory row or fabricate a cost comparison
- If CSV matching returns many blanks, continue with those rows left blank; do not manually invent Huawei Cloud product mappings in Step 4
- If `hcloud` is not available, Step 6 and Step 7 may both be skipped; keep only documentation-backed recommendations and note that availability was not verified
- If `hcloud` is installed but `cli-lang` is not `cn`, switch it to Chinese before Step 6 so DCS flavor checks and other current CLI behaviors stay consistent with this skill
- If Excel export fails, stop at `billing_final.md` and report the export issue

## Output Files

```text
output/
├── azure_billing_summary/  # Azure only: one preprocessed CSV per worksheet
├── billing_raw.md
├── billing_categorized.md
├── billing_matched.md
├── billing_with_specs.md
├── billing_with_availability.md
├── billing_final.md
└── billing_final.xlsx
```

## Common Pitfalls

1. Choose the correct source-cloud module before matching products. The wrong CSV will produce convincing but incorrect mappings.
2. Parse Markdown tables with a real CSV/pipe-aware approach. Do not split mapping CSV rows manually.
3. Keep fixed schema headers in English even when the user speaks another language.
4. Do not overstate non-1:1 mappings as direct replacements.
5. Use the alternative-solution guide only for material mismatches, unavailable targets, or evidence-backed cost/model concerns; do not create alternatives mechanically for every row.
6. For Azure, distinguish the canonical service family from SKU and meter text, and normalize the preprocessed `Region` before selecting the Huawei Cloud target region.
7. Never relabel a non-USD Azure `CostInBillingCurrency` value as `Monthly (USD)` without an explicit conversion basis.
