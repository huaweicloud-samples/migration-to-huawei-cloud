---
name: migration-to-huawei-billing-mapper
description: Use when users provide billing reports or resource inventories from AWS, GCP, Oracle Cloud Infrastructure (OCI), or similar source clouds and need to migrate to Huawei Cloud, including product matching, regional mapping, per-category sub-agent spec recommendation, and exportable migration inventory generation.
---

# Source Cloud to Huawei Cloud Billing Migration

## Overview

8-step pipeline that converts a source-cloud billing PDF, CSV, or resource export into a categorized, reviewed, Huawei-Cloud-matched inventory plus Excel export.

```text
Input: source-cloud billing PDF / CSV / resource inventory
  -> Step 1: Generate raw Markdown and detect source cloud/module
  -> Step 2: Categorize & Tabulate (agent analysis)
  -> Step 3: Review Categorized Output (agent review)
  -> Step 4: Product Matching (match_products.py + selected mapping CSV)
  -> Step 5: Spec Recommendation (tool discovery + per-category child agents + Huawei docs)
  -> Step 6: Availability Check (check_availability.py)
  -> Step 7: Review and Replace Unavailable Specs (agent review)
  -> Step 8: Excel Export (export_excel.py)
Output: Final inventory MD with availability status + single-sheet Excel
```

### Supported Source-Cloud Modules

During Step 1, detect the source cloud from the raw bill content and select one module. Keep that module consistent throughout the rest of the run:

| Source Cloud | Module Notes | Mapping CSV |
| --- | --- | --- |
| AWS | `references/source-clouds/aws.md` | `data/source-clouds/aws-hwc-product.csv` |
| GCP | `references/source-clouds/gcp.md` | `data/source-clouds/gcp-hwc-product.csv` |
| Oracle Cloud / OCI | `references/source-clouds/oracle.md` | `data/source-clouds/oracle-hwc-product.csv` |

If the source cloud is unsupported, clone the closest module, add provisional mapping rows, and clearly mark any assumptions in the output notes. The GCP and Oracle seed datasets include some starter mappings that should be treated as review-required migration hints, not contractual pricing truth.

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
  Install: auto-installed by `uv run` in Step 8.

Check all prerequisites before starting. If `hcloud` is missing, note that Step 6 and Step 7 may both be skipped. If `hcloud` is present but not configured with `cli-lang=cn`, set it before Step 6 because this workflow depends on the current Chinese KooCLI command surface, including `DCS ListFlavors`.

## Workflow

> IMPORTANT: Run steps sequentially unless noted. Each step's output is the next step's input. All output files go to `output/`.

### Step 1: PDF to Markdown

**Goal:** Convert the user-provided source-cloud bill into raw Markdown text, then use that raw content to detect the source cloud and select the correct source-specific module. If the user already provides CSV, TSV, Markdown, or a structured inventory, skip `markitdown` and normalize directly into Markdown.

After `output/billing_raw.md` is produced, determine whether the input comes from AWS, GCP, Oracle Cloud Infrastructure, or another source cloud, then load the correct source-specific hints and mapping CSV.

Detection signals:

- Product names or SKUs in the bill, such as `Amazon EC2`, `Compute Engine`, `Autonomous Database`
- Region formats, such as `us-east-1`, `us-central1`, `ap-singapore-1`
- Export format names, service namespaces, or invoice branding

Use the selected module only for source-cloud-specific parsing, alias recognition, traffic normalization hints, and product mapping CSV selection. The rest of the pipeline remains shared.

**Try `markitdown` first for PDF inputs:**

```bash
mkdir -p output
markitdown <user-provided-billing.pdf> > output/billing_raw.md
```

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

Use this decision tree for PDF inputs:

1. Run direct `markitdown` on the original PDF.
2. Inspect `output/billing_raw.md`.
3. Treat the direct extraction as `FAIL` and switch to OCR if any of these are true:
   - The file is empty or `markitdown` errors
   - The output is suspiciously short for a multi-page bill, for example only a few KB and mostly summary-page text
   - The output contains branding and totals but not detailed usage rows, service sections, regions, quantities, or SKU-like descriptions
4. Run `ocrmypdf --force-ocr --deskew --rotate-pages -l chi_sim+eng input.pdf output/billing_searchable.pdf`, then rerun `markitdown`.
5. Treat forced OCR as the default OCR mode for this workflow once direct `markitdown` extraction is judged insufficient, because billing PDFs often contain vector pages that otherwise get skipped or only partially extracted.

**Verify output** before proceeding:

- It is non-empty
- It contains recognizable source-cloud product names from the selected module
- It includes detailed line-item content from beyond the first summary page
- It contains enough structure to recover per-service usage, amount, quantity, and region clues

Examples:

- AWS: `EC2`, `S3`, `RDS`, `Lambda`
- GCP: `Compute Engine`, `Cloud Storage`, `Cloud SQL`, `BigQuery`
- OCI: `Compute`, `Block Volume`, `Load Balancer`, `Autonomous Database`

If searchable-PDF generation or `markitdown` still fails, ask the user for a billing export CSV, pricing export, resource inventory, or screenshots.

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

Map each resolved source region to the geographically nearest Huawei Cloud region using `references/regions.md`.

After region assignment, group all line items by **(Source Product, Source Spec, Region)**. Sum quantities and monthly cost. Do not merge resources across different regions.

**Categorization is a hard rule based on service nature, not on the source-cloud brand.**

| Category | Criterion | Cross-cloud examples (non-exhaustive) |
| --- | --- | --- |
| **Compute** | CPU / memory compute capacity, virtual machines, containers, serverless runtimes | EC2, Compute Engine, OCI Compute, GKE node pools, OKE worker nodes, Lambda, Cloud Functions, Functions |
| **Storage** | Persistent data storage, object, block, file, archive, backup | S3, Cloud Storage, OCI Object Storage, EBS, Persistent Disk, Block Volume, EFS, Filestore |
| **Network** | Connectivity, traffic distribution, DNS, CDN, private link, egress / transfer | ELB, Cloud Load Balancing, OCI Load Balancer, NAT Gateway, Cloud NAT, FastConnect, Cloud CDN, Data Transfer |
| **Database** | Managed databases, caches, warehouses, migration tooling | RDS, Cloud SQL, AlloyDB, Autonomous Database, HeatWave-like managed DBs, ElastiCache, Memorystore |
| **Other** | Security, observability, messaging, analytics, governance, identity, devtools, AI | IAM, CloudWatch, Cloud Logging, Pub/Sub, SNS, Oracle Logging, BigQuery, Athena, ModelArts mapping candidates |

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
- Consolidate only `Data Transfer` style rows and `NAT Gateway Data Processed` style rows under `Source Product = Data Transfer` when the billing line is fundamentally traffic-based
- Do not automatically fold CDN, load-balancer, EIP, bandwidth, or other network-product traffic rows into `Data Transfer` unless a later version of this skill explicitly adds that rule
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
- `Monthly (USD)` formatting

If the validator reports any `FAIL`, edit `output/billing_categorized.md` in place and rerun it. Do not proceed while any validator failure remains.

#### 3.2 Perform Manual Review Against Step 2.2

Manual review should focus only on the judgment-based checks that the validator cannot prove. Review each of the following explicitly:

- Semantic merge correctness: rows were not incorrectly merged across different regions or unlike resources even if no exact duplicate tuple remains
- Traffic-cost normalization follows the Step 2.2 rule in full, not just the validator's keyword check
- Only `Data Transfer` style rows and NAT processed traffic were consolidated into `Source Product = Data Transfer`
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

#### 5.0 Find the Sub-Agent Tool First

Before delegating any category work:

- Search the currently available tools for sub-agent or child-session support
- Select the tool that can explicitly create child agents and let the parent coordinate them
- Do not start category recommendation work until the child-session creation tool has been identified

Document the decision briefly in the working notes so it is clear which tool was used for Step 5 delegation.

#### 5.0.1 Instantiate the Child-Agent Prompt Template

Use `references/child-agent-prompt-template.md` as the required prompt skeleton for each Step 5 child session. Do not write ad hoc child prompts when delegating category work.

Before spawning a child session, the parent must replace every placeholder in the template with concrete values:

- `{{CATEGORY_NAME}}`: one of `Compute`, `Storage`, `Network`, `Database`, `Other`
- `{{USER_LANGUAGE}}`: same language as the user
- `{{INPUT_FILE}}`: usually `output/billing_matched.md`
- `{{CATEGORY_TABLE_MARKDOWN}}`: the exact category section or table assigned to that child
- `{{DOC_REFERENCE_FILE}}`: `skills/migration-to-huawei-billing-mapper/references/product-docs.md`
- `{{DOC_CACHE_DIR}}`: category-specific local doc cache such as `output/spec-docs/compute/`
- `{{CATEGORY_OUTPUT_FILE}}`: recommended category result path such as `output/spec-results/compute.md`

Parent-session rules for template usage:

- Pass only one top-level category per instantiated prompt
- Inline the exact category table content in `{{CATEGORY_TABLE_MARKDOWN}}` so the child scope is explicit
- Require the child to save fetched official docs locally before making recommendations
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
- Save the fetched source pages locally before doing any recommendation work
- Recommended local cache layout:

```text
output/spec-docs/
  compute/
  storage/
  network/
  database/
  other/
```

- Save each fetched page as a readable local artifact such as `.md`, `.html`, or `.txt`
- File names should be stable and product-oriented, for example `ecs.md`, `rds-mysql.md`, `evs.md`
- After documentation is fetched and saved locally, the child session continues with Step 5.2 for only that category
- The parent session remains responsible for combining all category outputs back into one final `output/billing_with_specs.md`

#### 5.1 Look Up Documentation

First, read `references/product-docs.md` for official Huawei Cloud documentation URLs. For each category child session:

- Identify all distinct Huawei Cloud products that appear in that category table
- Fetch the official documentation pages needed for those products
- Save the fetched pages to the local `output/spec-docs/<category>/` directory
- Use the saved local copies as the working reference set for the rest of Step 5

Use the official docs to verify:

- Instance types and flavors
- Storage tiers and performance levels
- Network or gateway bandwidth models
- Database engine versions and classes
- Region support and regional limitations

If the product is not listed in `product-docs.md`, search Huawei Cloud official documentation, fetch the relevant page, save it locally, and cite the limitation in the notes.

**Mandatory region support check:** before recommending any Huawei Cloud product or spec, verify whether the product is supported in the row's `HWC Target Region`.

#### 5.2 Recommend Spec

Only start this step after the category child session has finished fetching and saving the required documentation pages locally.

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

- `🟢`
- `🟡`
- `🔴`

Label semantics:

- `🟢`: near like-for-like mapping; no major product-form mismatch is known from the reviewed docs
- `🟡`: workable substitute exists, but there are product-model, feature, runtime, or operational differences that must be called out
- `🔴`: no defensible native equivalent, or the region/support limitation is severe enough that redesign, self-managed deployment, or manual architecture change is required

For `🟡` or `🔴`, explicitly describe what differs: service model, serverless semantics, autoscaling behavior, operations ownership, feature gaps, or required redesign.

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

- Reuse the Step 5 local doc cache under `output/spec-docs/` before searching again
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

### Step 8: Export Excel

**Goal:** Export the final Markdown inventory to a single-sheet Excel workbook.

Excel layout requirements:

- The workbook stays single-sheet
- The file title should be written as a merged row spanning the effective table width
- Metadata blockquote lines near the top of the Markdown should be exported as merged full-width rows so `Source Cloud`, `Total Monthly`, and similar summary fields are easy to read and edit
- Each category's `**Recommendation rationale:** ...` paragraph should be exported immediately after that category table as a merged full-width row
- Table headers and resource rows remain unmerged regular cells

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
- Map that row to the nearest Huawei Cloud region using `references/regions.md`
- If a specific row has no determinable region, default to `ap-southeast-3` with an explicit note
- Do not collapse multiple source regions into a single row

## Error Handling

- If `markitdown` fails on the original PDF, switch to the searchable-PDF OCR path in Step 1
- If OCR plus `markitdown` still fails, ask for a structured export instead
- If Step 3 or Step 7 finds inconsistencies, correct the file in place before continuing
- If CSV matching returns many blanks, continue with those rows left blank; do not manually invent Huawei Cloud product mappings in Step 4
- If `hcloud` is not available, Step 6 and Step 7 may both be skipped; keep only documentation-backed recommendations and note that availability was not verified
- If `hcloud` is installed but `cli-lang` is not `cn`, switch it to Chinese before Step 6 so DCS flavor checks and other current CLI behaviors stay consistent with this skill
- If Excel export fails, stop at `billing_final.md` and report the export issue

## Output Files

```text
output/
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
5. Treat the GCP and Oracle starter mappings as seed data that may need manual review and expansion.
