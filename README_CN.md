# 迁移到华为云

用于华为云迁移规划、评估和实施流程的一组可复用 agent skills。

[English](README.md)

## Skills 清单

| Skill | 功能 | 适用场景 |
| --- | --- | --- |
| [`migration-to-huawei-billing-mapper`](skills/migration-to-huawei-billing-mapper/SKILL.md) | 将 AWS 或 Microsoft Azure 的账单导出文件、Cost Management 导出文件和资源清单转换为经过审核的华为云迁移清单。支持资源分类、产品匹配、地域映射、目标规格推荐、华为云 CLI 可用性检查、替代方案记录，以及最终 Excel 导出。 | 云迁移评估、账单分析、产品映射、地域映射和迁移规格评估 |
| [`query-huawei-cloud-prices`](skills/query-huawei-cloud-prices/SKILL.md) | 按产品、地域和规格实时查询华为云价格。支持国际站和中国站、按需/包月/包年/阶梯价格、计费单位映射。 | 价格查询、地域价格对比、ECS/EVS/EIP/NAT/APIG 价格和规格确认 |

每个 skill 都有自己的 `SKILL.md`，并可以包含专用脚本、数据、references 和测试。具体的输入、输出、前置依赖和工作流请以对应 skill 的文档为准。

## 安装

### 推荐方式：`npx skills`

该方式需要 Node.js。执行以下命令来发现并安装本仓库中的 skills：

```bash
npx skills add huaweicloud-samples/migration-to-huawei-cloud
```

查看已安装的 skills：

```bash
npx skills list
```

如果 skills CLI 或 agent 支持选择单个 skill，可以根据上方清单中的名称进行选择。

### 使用 Git 克隆到本地

如果环境中没有 Node.js 或 `npx`，直接从 GitHub 克隆仓库，并将 agent 指向需要使用的 skill 目录：

```bash
git clone https://github.com/huaweicloud-samples/migration-to-huawei-cloud.git
cd migration-to-huawei-cloud
```

各 skill 的定义文件位于：

```text
skills/<skill-name>/SKILL.md
```

如果 agent 使用本地 skills 目录，可以将选中的 `skills/<skill-name>` 目录复制或软链接到该目录。请保留 skill 相对于 `SKILL.md` 的脚本、数据、references 和其他文件。

## 使用方式

从上方清单中选择一个 skill，并在 prompt 中使用它的准确名称。然后按照对应 `SKILL.md` 中的说明提供输入文件和目标输出位置。

当前仓库包含以下 skill 的专用使用说明。

### `query-huawei-cloud-prices`

#### Prompt 示例

```text
查询华为云北京四区域 ECS x1.2u.4g 的价格。
```

该 skill 默认查询华为云国际站价格，返回包含产品、地域、货币、规格和映射后计费单位的精简 JSON

查询中国站价格时使用 `--site china`。中国站使用 `portal.huaweicloud.com`，默认语言为 `zh-cn`，返回货币 `CNY`


### `migration-to-huawei-billing-mapper`

#### Prompt 示例

```text
使用技能，根据当前目录下的 PDF 或 Excel 账单生成华为云迁移清单。
```

提供账单报告、Cost Management 导出文件或资源清单。工作流会将中间文件和最终文件写入 `output/`：

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

当前内置的源云模块包括：

- AWS 账单和资源导出文件
- Microsoft Azure 账单，且只接受可预处理的 `.xlsx` 工作簿

对于 Azure，必须先校验并汇总工作簿中的每个 worksheet，再进入分类流程。请求 Azure 账单分析时不要提供 PDF、CSV 或其他格式。如果源云不受支持，必须明确标记，不得静默使用 AWS 或 Azure 的映射数据。

完整流程包括：

1. 源文件转换和源云识别
2. 资源分类和地域标准化
3. 分类结果校验与审核
4. 华为云产品匹配
5. 基于华为云官方文档的目标规格推荐
6. 在安装并配置 `hcloud` 时检查目标地域可用性
7. 审核并替换不可用规格
8. 基于证据评估替代方案
9. 导出单工作表 Excel

#### 前置依赖

该 skill 会根据工作流需要在运行时检查依赖：

- `markitdown`：转换支持的非 Azure 输入文件
- `uv`：运行 Python 工具和隔离依赖
- `hcloud` CLI：检查资源可用性，并需要配置 `cli-lang=cn`
- OCR 工具（`ocrmypdf`、`tesseract` 和 Ghostscript）：仅在非 Azure PDF 提取不完整时使用
- `pandas` 和 `openpyxl`：预处理 Azure 工作簿
- `aspose-cells-python`：导出 Excel 时通过 `uv` 安装

如果没有 `hcloud`，或 CLI 未完成配置，工作流仍可生成有官方文档依据的规格推荐，但不会验证目标资源可用性。详细依赖检查和完整流程请参阅 [skill 定义](skills/migration-to-huawei-billing-mapper/SKILL.md)。

## 新增 Skill

向本仓库新增 skill 时：

1. 创建 `skills/<skill-name>/SKILL.md`，写明 skill 名称、描述、支持的输入、工作流和约束。
2. 尽量将 skill 专用的脚本、数据、references 和测试放在该目录内。
3. 在 `README.md` 和 `README_CN.md` 的 Skills 清单中各增加一行。
4. 在两份 README 中为新 skill 自己的章节增加一个简洁的 prompt 示例。
5. 验证安装命令可以发现新 skill，并确认 `SKILL.md` 中的路径均以 skill 目录为相对基准。

新增 skill 不应要求修改安装命令。通过发现机制或本地克隆后，每个 skill 都应能独立使用。

## 开源协议

本项目采用 [Apache License 2.0](LICENSE) 协议。
