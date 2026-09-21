---
name: migration-to-huawei-billing-mapper
description: Use when users provide billing reports, Cost Management exports, or resource inventories from AWS, Microsoft Azure, or another source cloud and need to migrate to Huawei Cloud, including product matching, regional mapping, per-category sub-agent spec recommendation, and exportable migration inventory generation. Azure billing analysis in this skill accepts only preprocessable `.xlsx` workbooks.
---

# Source Cloud to Huawei Cloud Billing Migration

## Overview

A 9-step pipeline converting source-cloud billing or resource exports into a categorized, reviewed, Huawei-Cloud-matched inventory with alternative solutions and an Excel export.

```text
Input: source-cloud billing file / resource inventory
  -> Step 1: Billing Source to Raw Markdown & Detect Source Cloud/Module
  -> Step 2: Categorize & Tabulate (agent analysis)
  -> Step 3: Review Categorized Output (validate_categorized.py + agent review)
  -> Step 4: Product Matching (match_products.py + CSV)
  -> Step 5: Spec Recommendation (child agents + product-docs.md)
  -> Step 6: Availability Check (check_availability.py)
  -> Step 7: Review & Replace Unavailable Specs (agent review + spec-replacement-guide.md)
  -> Step 8: Alternative Solution Review (alternative-solutions.md)
  -> Step 9: Excel Export (export_excel.py)
Output: Final inventory MD + single-sheet Excel
```

### Supported Source-Cloud Modules

Detect the source cloud in Step 1 and maintain the module consistently throughout the run:

| Source Cloud    | Module Notes                        | Mapping CSV                              | Region Catalog                                                                        |
| --------------- | ----------------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------------- |
| AWS             | `references/source-clouds/aws.md`   | `data/source-clouds/aws-hwc-product.csv` | Region IDs described in module; normalized against `references/regions.md`            |
| Microsoft Azure | `references/source-clouds/azure.md` | `data/source-clouds/azure-hwc.csv`       | `data/source-clouds/azure-regions.csv`                                                |

If the source cloud is unsupported, do not silently select either CSV. Add provisional mapping rows only when the user requests skill extension, marking assumptions as review-required migration hints.

### Language Policy

- **Table schema headers**: Strictly English (fixed schema required by downstream scripts).
- **User-facing prose**: Titles, category labels, notes, rationale, and alternative solutions must follow the user's language.

Required fixed headers: `#`, `Category`, `Source Product`, `Source Spec`, `Monthly (USD)`, `Qty`, `Source Est. Resource Count`, `Region`, `HWC Target Region`, `Notes`.

## Prerequisites

Detect and handle at runtime:

- `markitdown`: Check with `pip show markitdown`; install via `pip install markitdown`.
- `uv`: Check with `which uv`; install via `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- `hcloud CLI`: Check with `which hcloud`. If unavailable, skip Step 6 and Step 7. If available, ensure Chinese CLI surface: `hcloud configure set --cli-lang=cn`.
- OCR stack: Needed only when PDF extraction fails. See `references/ocr-billing-pdf.md`.
- `aspose-cells-python`: Auto-installed by `uv run` in Step 9.
- Azure preprocessing dependencies: `uv run --with pandas --with openpyxl python -c "import pandas, openpyxl"`. Mandatory for Azure `.xlsx`.

## Workflow

> IMPORTANT: Run steps sequentially. Each step's output feeds the next step. All outputs go to `output/`.

### Step 1: Billing Source to Raw Markdown

**Goal:** Convert source-cloud billing or inventory into raw Markdown (`output/billing_raw.md`), identify source cloud, and select module.

**Detection signals:** Product SKUs (`Amazon EC2`, `Virtual Machines`), region formats (`us-east-1`, `southeastasia`), or export headers (CUR, Cost Management fields).

#### Azure Input Gate (Mandatory for Azure)
Inspect file headers/content. Do not classify a file as Azure merely because it is a generic spreadsheet. Once confirmed as Azure:
1. The input **must** be an `.xlsx` workbook. No `markitdown`, CSV, or PDF OCR alternatives are accepted.
2. Run the preprocessor:
   ```bash
   mkdir -p output/azure_billing_summary
   uv run skills/migration-to-huawei-billing-mapper/scripts/summarize_azure_billing.py \
     <azure-billing.xlsx> --output-dir output/azure_billing_summary
   ```
3. Preprocessing failure is terminal: do not proceed to Step 2; report the concrete error.
4. On success, combine all summarized CSVs from `output/azure_billing_summary/` into `output/billing_raw.md`.

#### Non-Azure Conversion
For non-Azure inputs, convert via `markitdown`:
```bash
mkdir -p output
markitdown <user-provided-billing-file> > output/billing_raw.md
```
**OCR Fallback:** If `markitdown` produces empty/partial output on a PDF, run forced OCR:
```bash
ocrmypdf --force-ocr --deskew --rotate-pages -l chi_sim+eng input.pdf output/billing_searchable.pdf
markitdown output/billing_searchable.pdf > output/billing_raw.md
```
See `references/ocr-billing-pdf.md` for tool installation and advanced fallback.

**Output:** `output/billing_raw.md`

---

### Step 2: Categorize and Tabulate

**Goal:** Parse line items, assign regions, merge duplicate tuples, and organize into 5 category tables.

1. **Region Assignment**: Extract source region from row or surrounding context. If indeterminable, leave source region unknown, default `HWC Target Region` to `ap-southeast-3`, and add an explanatory note. Map resolved regions to the nearest Huawei Cloud region using `references/regions.md`.
2. **Categorization**: Classify by service primary function:

| Category     | Criterion                                                                         | Examples                                                           |
| ------------ | --------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| **Compute**  | CPU/memory compute capacity, VMs, containers, serverless runtimes                 | EC2, EKS, Lambda, Azure Virtual Machines, AKS, Functions          |
| **Storage**  | Persistent data storage, object, block, file, archive, backup                     | S3, EBS, Azure Blob, Disk Storage, Azure Files                     |
| **Network**  | Connectivity, traffic distribution, DNS, CDN, private link, egress/transfer       | ELB, NAT Gateway, CloudFront, Azure Load Balancer, Private Link    |
| **Database** | Managed databases, caches, warehouses, migration tooling                          | RDS, Aurora, ElastiCache, Azure SQL, Cosmos DB, Azure Redis        |
| **Other**    | Security, observability, messaging, analytics, governance, identity, devtools, AI | IAM, CloudWatch, SNS, Entra ID, Azure Monitor, Service Bus         |

3. **Tabulation & Normalization Rules**:
   - **Merge rule**: Combine rows with identical `Source Product + Source Spec + Region`. Sum quantities and monthly cost. Never merge across different regions.
   - **Traffic normalization**: Within each `Region`, consolidate all non-NAT transfer components into exactly one ordinary row with `Source Product = Data Transfer` (outbound/egress breakdowns belong in `Notes`). If NAT is present in that region, keep its processed traffic as one additional `Source Product = Data Transfer` row. Gateway/load balancer runtime hours remain standalone resources.
   - **Source Est. Resource Count**: Estimate only for countable runtime-hour resources; otherwise use `—`.
   - Category labels and section titles follow the user's language; table headers remain fixed English.

**Output:** `output/billing_categorized.md`

---

### Step 3: Review Categorized Output

**Goal:** Ensure `output/billing_categorized.md` satisfies all schema and normalization rules before product matching. This step is a blocking gate.

#### 3.1 Run Blocking Validator
```bash
uv run skills/migration-to-huawei-billing-mapper/scripts/validate_categorized.py \
  --input output/billing_categorized.md
```
The validator enforces fixed English headers, single region mappings, duplicate tuple elimination, required fields, and traffic normalization counts. Any `FAIL` must be fixed in place.

#### 3.2 Manual Review
Review judgment-based items that the script cannot verify:
- Semantic merge correctness (no improper cross-region or unlike merges).
- Traffic normalization compliance with Step 2 rules (non-NAT consolidated per region, NAT traffic separated, CDN/bandwidth not improperly folded).
- Runtime-hour gateway/LB rows preserved as standalone resources.
- Resource counts used only for clear runtime-hour resources.
- Correct source-cloud module used consistently.

#### 3.3 Review Discipline
Every review item must evaluate to explicit `PASS` or `FAIL` (with row references). Any `FAIL` requires in-place edits and a rerun of the validator until all pass.

**Output:** `output/billing_categorized.md`

---

### Step 4: Match Huawei Cloud Products

**Goal:** Map each source product to its corresponding Huawei Cloud product using the module's CSV mapping.

```bash
uv run skills/migration-to-huawei-billing-mapper/scripts/match_products.py \
  --input output/billing_categorized.md \
  --csv <selected-source-mapping.csv> \
  --output output/billing_matched.md
```
- For AWS: `data/source-clouds/aws-hwc-product.csv`.
- For Azure: `data/source-clouds/azure-hwc.csv`.

**Mandatory restriction:** Do not guess, invent, or hallucinate Huawei Cloud product names. Only mappings from the verified CSV may be populated. Unmatched rows must remain blank.

**Output:** `output/billing_matched.md`

---

### Step 5: Recommend Specifications

**Goal:** Recommend equivalent Huawei Cloud specifications for matched products using official documentation.

> **Non-negotiable Sub-Agent Rule:** The parent session **must** spawn one child agent per non-empty category table (`Compute`, `Storage`, `Network`, `Database`, `Other`). Task simplicity or familiarity is never a reason to bypass sub-agents. The parent coordinates, extracts tables, and merges outputs into `output/billing_with_specs.md`, but must not perform spec lookups or author recommendations itself.

#### 5.1 Prompt Instantiation & Execution
For each non-empty category, instantiate `references/child-agent-prompt-template.md` by filling placeholders (`{{CATEGORY_NAME}}`, `{{USER_LANGUAGE}}`, `{{CATEGORY_TABLE_MARKDOWN}}`, etc.).

Each child session executes:
1. **Service-Region Precheck**: For every non-empty product row:
   ```bash
   uv run skills/migration-to-huawei-billing-mapper/scripts/check_service_region.py \
     --product "<Huawei Cloud Product>" \
     --region "<HWC Target Region>" \
     --json
   ```
   - If `Unavailable`, leave spec empty unless a documented in-region alternative exists.
   - Record status (`Available`, `Unavailable`, `Pending Confirmation`, `Skipped`) and service code in `Recommendation Notes`. Do not treat `Pending Confirmation` as available.
2. **Documentation Review**: Consult `references/product-docs.md` and fetch official documentation to verify instance flavors, storage tiers, database classes, and regional limitations. Do not save docs locally.
3. **Spec Recommendation**: Add `Recommended Spec` and `Recommendation Notes`.
   - Compare vCPU, RAM, storage, IOPS, throughput, bandwidth, and runtime models.
   - Prepend one migration signal label to `Recommendation Notes`:
     - 🟢: Near like-for-like mapping.
     - 🟡: Workable substitute with differences (e.g., serverless vs. provisioned, feature gaps). Explicitly describe differences.
     - 🔴: No direct native equivalent; redesign or self-managed deployment required.
4. **Rationale**: Append a 2–3 sentence category rationale paragraph in the user's language at the bottom of the table.

The parent merges completed category outputs into `output/billing_with_specs.md`.

**Output:** `output/billing_with_specs.md`

---

### Step 6: Check Availability

**Goal:** Verify in-region availability of recommended machine-queryable specs via `hcloud CLI`.

```bash
uv run skills/migration-to-huawei-billing-mapper/scripts/check_availability.py \
  --input output/billing_with_specs.md \
  --output output/billing_with_availability.md
```
- Checks queryable spec codes (e.g., `s6.large.2`, `rds.mysql.*`, `redis.*`).
- Assigns status: `Available`, `Sold Out`, `Flavor Not Found`, `Unavailable`, `Not Detected`, or `N/A`.
- If `hcloud` is missing, skip Steps 6 and 7.

**Output:** `output/billing_with_availability.md`

---

### Step 7: Review and Replace Unavailable Specs

**Goal:** Resolve unavailable specs to defensible sellable substitutes in the same product family and region.

Review `output/billing_with_availability.md` and apply these actions per status:

| Availability Status | Action |
| --- | --- |
| `Available` | Retain and verify justification. |
| `Sold Out` | **Do not auto-replace.** Retain spec; record note that flavor is sold out and requires secondary confirmation or replenishment. |
| `Flavor Not Found` / `Unavailable` | Follow `references/spec-replacement-guide.md` to search in-region candidates. Select nearest sellable substitute in the same family. Update `Recommended Spec` and `Recommendation Notes` (mandatory note detailing original spec, replacement, reason, and rechecked status). Rerun Step 6 until verified `Available` or confirmed unresolved. |
| `Not Detected` / `N/A` | Retain documentation-backed spec; note that availability was not machine-verifiable in current environment. |

When no sellable substitute exists, leave `Recommended Spec` empty or unresolved with a `🟡`/`🔴` note.

**Output:** `output/billing_final.md`

---

### Step 8: Review Alternative Solutions

**Goal:** Provide architectural alternatives for resources with material mismatches (`🟡`/`🔴`), unavailable targets, or significant cost/model discrepancies (e.g., serverless to fixed capacity).

1. Follow `references/alternative-solutions.md` for evaluation sequences, candidate patterns (such as lightweight buffer on DCS Redis vs. DMS), and prohibited practices.
2. Append a standalone section to `output/billing_final.md`:

```markdown
## Alternative Solutions

### Solution 1: Alternative path for <Source Product/Resource>
- **Triggering resource**: <Category / # / Source Product / Source Spec / Region>
- **Triggering reason**: <Reason for alternative>
- **Direct migration conclusion**: <Retain recommendation / Direct migration not recommended / Pending confirmation>
- **Recommended solution**: <Huawei Cloud product and architecture changes>
- **Prerequisites**: <Throughput, persistence, HA, compliance prerequisites>
- **Key differences and required changes**: <Service model, gaps, operational changes>
- **Cost assessment**: <Cost direction and items to recalculate; do not invent prices>
- **Risks and validation**: <PoC, load testing, validation items>
- **Evidence**: <Official documentation URLs>
- **Migration signal**: 🟡 / 🔴
```

If no resources qualify, append the standard notice as specified in `references/alternative-solutions.md`.

**Output:** `output/billing_final.md` (with Alternative Solutions appended)

---

### Step 9: Export Excel

**Goal:** Export the final Markdown inventory and alternative solutions to a single-sheet Excel workbook.

```bash
uv run skills/migration-to-huawei-billing-mapper/scripts/export_excel.py \
  --input output/billing_final.md \
  --output output/billing_final.xlsx
```

**Layout rules:** Single-sheet workbook; title, metadata, category rationales, and alternative solutions exported as merged full-width rows; inventory tables remain unmerged; columns and row heights dynamically adapt with text wrapping.

**Output:** `output/billing_final.xlsx`

---

## Region & Error Handling Summary

- **Region Resolution**: Resolve region per row. Default indeterminable regions to `ap-southeast-3` with a note. Never collapse multiple source regions into one.
- **Azure Preprocessing Failure**: Terminal. Require `.xlsx` and successful preprocessing; do not fall back to OCR or raw Markdown parsing.
- **Missing `hcloud`**: Skip Steps 6 and 7; retain documentation-backed recommendations and note unverified availability.
- **In-place Edits**: If validation or review checks fail in Steps 3 or 7, edit the working Markdown file in place and rerun the corresponding checker.

## Output Files

```text
output/
├── azure_billing_summary/  # Azure only: summarized CSVs
├── billing_raw.md
├── billing_categorized.md
├── billing_matched.md
├── billing_with_specs.md
├── billing_with_availability.md
├── billing_final.md
└── billing_final.xlsx
```

## Common Pitfalls

1. **Wrong module selection**: Using the wrong source-cloud CSV produces false matches.
2. **Inventing mappings**: Leaving unmatched products blank in Step 4 is expected; never guess product names.
3. **Skipping sub-agents**: Step 5 sub-agents are mandatory for every non-empty category.
4. **Header translation**: Keep fixed table schema headers in English; localize only prose, notes, and section titles.
5. **Overbroad alternatives**: Only generate alternative solutions for clear mismatches, unavailable targets, or scale discrepancies.
