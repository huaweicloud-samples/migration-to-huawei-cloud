# Migration to Huawei Cloud

A collection of reusable agent skills for Huawei Cloud migration planning, assessment, and implementation workflows.

[中文文档](README_CN.md)

## Skills

| Skill | Function | Best for |
| --- | --- | --- |
| [`migration-to-huawei-billing-mapper`](skills/migration-to-huawei-billing-mapper/SKILL.md) | Converts AWS or Microsoft Azure billing exports and resource inventories into a reviewed Huawei Cloud migration inventory. It categorizes resources, maps products and regions, recommends target specifications, checks availability when the Huawei Cloud CLI is configured, records alternative solutions, and exports the final inventory to Excel. | Cloud migration assessment, bill analysis, product mapping, region mapping, and migration sizing |
| [`query-huawei-cloud-prices`](skills/query-huawei-cloud-prices/SKILL.md) | Queries live Huawei Cloud product prices by product, region, and resource specification. Supports international and China calculator sites, on-demand, monthly, yearly, and tiered prices, mapped billing units. | Price lookup, regional cost comparison, ECS/EVS/EIP/NAT/APIG pricing, and specification verification |

Each skill has its own `SKILL.md` and may include dedicated scripts, data, references, and tests. Use the linked skill documentation for its exact inputs, outputs, prerequisites, and workflow.

## Installation

### Recommended: `npx skills`

Node.js is required for this method. Run the following command to discover and install the skills in this repository:

```bash
npx skills add huaweicloud-samples/migration-to-huawei-cloud
```

To inspect the installed skills:

```bash
npx skills list
```

When the skills CLI or agent supports selecting individual skills, choose the skill by its name from the table above.

### Clone with Git

If Node.js or `npx` is unavailable, clone the repository directly and point your agent to the required skill directory:

```bash
git clone https://github.com/huaweicloud-samples/migration-to-huawei-cloud.git
cd migration-to-huawei-cloud
```

Skill definitions are located under:

```text
skills/<skill-name>/SKILL.md
```

For an agent that uses a local skills directory, copy or symlink the selected `skills/<skill-name>` directory into that directory. Keep the skill's scripts, data, references, and other files available relative to `SKILL.md`.

## Usage

Choose a skill from the table above and mention its exact name in the prompt. Then provide the input files and desired output location described by that skill's `SKILL.md`.

The current repository includes the following skill-specific usage details.

### `query-huawei-cloud-prices`

#### Prompt example

```text
Check the ECS x1.2u.4g price in Huawei Cloud Singapore.
```

The skill queries the international Huawei Cloud calculator by default and returns compact JSON with the product, region, currency, specifications, and mapped price units.

Use `--site china` for China site pricing. The China site uses `portal.huaweicloud.com`, defaults to `zh-cn`, and returns `CNY`.

### `migration-to-huawei-billing-mapper`

#### Prompt example

```text
Use skills to generate a Huawei Cloud migration inventory from the PDF/Excel billing file in this directory.
```

Provide a billing report, Cost Management export, or resource inventory. The workflow writes intermediate and final files to `output/`:

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

The bundled source-cloud modules currently support:

- AWS billing and resource exports
- Microsoft Azure billing analysis from preprocessable `.xlsx` workbooks only

For Azure, the workbook is validated and summarized before categorization. Do not provide an Azure PDF, CSV, or other format when requesting Azure billing analysis. Unsupported source clouds must be identified explicitly and must not silently use the AWS or Azure mapping data.

The full workflow includes:

1. Source-file conversion and source-cloud detection
2. Resource categorization and region normalization
3. Categorization validation and review
4. Huawei Cloud product matching
5. Target specification recommendations backed by Huawei Cloud documentation
6. Target-region availability checks when `hcloud` is installed and configured
7. Review and replacement of unavailable specifications
8. Evidence-backed alternative-solution review
9. Single-sheet Excel export

#### Prerequisites

This skill checks dependencies at runtime as needed:

- `markitdown` for converting supported non-Azure inputs
- `uv` for Python tooling and isolated dependencies
- `hcloud` CLI for availability checks; configure it with `cli-lang=cn`
- OCR tools (`ocrmypdf`, `tesseract`, and Ghostscript) only for incomplete non-Azure PDF extraction
- `pandas` and `openpyxl` for Azure workbook preprocessing
- `aspose-cells-python`, installed through `uv` during Excel export

If `hcloud` is unavailable or not configured, the workflow can still produce documentation-backed recommendations, but target availability is not verified. See the [skill definition](skills/migration-to-huawei-billing-mapper/SKILL.md) for prerequisite checks and the complete workflow.

## Adding a skill

To add another skill to this repository:

1. Create `skills/<skill-name>/SKILL.md` with the skill's name, description, supported inputs, workflow, and constraints.
2. Keep skill-specific scripts, data, references, and tests inside that directory when practical.
3. Add a row to the Skills table in both `README.md` and `README_CN.md`.
4. Add one concise prompt example for the new skill to its own section in both README files.
5. Verify that the installation command still discovers the new skill and that all paths in `SKILL.md` are relative to the skill directory.

New skills should not require changes to the installation commands. Their directories should be independently usable after discovery or local cloning.

## License

This project is licensed under the [Apache License 2.0](LICENSE).
