# Microsoft Azure Source Module

## Purpose

Use this module when the billing data or resource inventory clearly comes from Microsoft Azure.

## Recognition Signals

- Product names such as `Virtual Machines`, `Azure Kubernetes Service (AKS)`, `Azure Blob Storage`, `Azure SQL Database`, and `Azure Functions`
- Azure resource IDs beginning with `/subscriptions/<id>/resourceGroups/<group>/providers/`
- Cost Management or Cost Details fields such as `SubscriptionId`, `ResourceLocation`, `MeterCategory`, `MeterSubCategory`, `MeterName`, `ProductName`, `ConsumedService`, and `CostInBillingCurrency`
- Region display names or programmatic names such as `Southeast Asia` / `southeastasia`, `East US 2` / `eastus2`, and `West Europe` / `westeurope`

Azure billing workbooks must first pass `scripts/summarize_azure_billing.py`. The preprocessed CSVs contain the canonical fields used by the shared workflow: `Meter Category`, `Meter Sub Category`, `Region`, `Resource URI`, `Term And Billing Cycle`, `Usage Quantity`, `Unit`, and a `Total Sales Price (...)` column.

## Parsing Hints

- Prefer the canonical Azure service family in `Meter Category` (and, when needed, `ProductName`, `ServiceName`, or `MeterCategory` from the source workbook) for `Source Product`. Remove plan, tier, and meter detail when it obscures the service name.
- Put SKU, meter, tier, reservation, operating-system, and instance-size detail in `Source Spec`. In preprocessed data, use `Meter Sub Category`, `Term And Billing Cycle`, and the preserved resource context; useful source-workbook fields include `SkuName`, `MeterSubCategory`, `MeterName`, `ProductName`, `PublisherType`, and `PricingModel`.
- Preserve `ResourceId` or resource-group context in `Notes` when it is needed to distinguish resources, but do not expose subscription IDs or other identifiers unnecessarily.
- Use the preprocessed `Region` as the row region. It comes from the workbook's row-level region field; if it is empty, use immediate resource or meter context and do not substitute the subscription's home region.
- Azure exports may contain amortized, actual, reservation, savings-plan, marketplace, tax, or credit rows. State which cost basis is used and avoid adding mutually exclusive cost views together.
- The fixed output column is `Monthly (USD)`. When the export currency is not USD, convert with a user-provided or explicit documented rate and record the rate/date in metadata. Otherwise stop and ask for a USD export or conversion basis instead of relabeling the source currency as USD.

## Region Normalization

- Load `data/source-clouds/azure-regions.csv` to normalize Azure display names and programmatic names before selecting the nearest Huawei Cloud region.
- Match region values case-insensitively after trimming spaces. For programmatic values, compare a lowercase form with spaces removed.
- Treat `global`, `unassigned`, `unknown`, and empty locations as unresolved rather than physical Azure regions. Default their Huawei Cloud target to `ap-southeast-3` only through the shared fallback rule, with an explicit note.
- Use the normalized Azure geography together with `references/regions.md` to choose the geographically nearest appropriate Huawei Cloud region. The Azure region catalog is a normalization source, not evidence that every Huawei Cloud product is available in the selected target region; Step 5 and Step 6 still verify product availability.

## Category Alias Hints

- Compute: Virtual Machines, Azure Dedicated Host, AKS, Container Instances, App Service, Container Apps, Azure Functions, Batch
- Storage: Blob Storage, Data Lake Storage, Disk Storage, Azure Files, NetApp Files, Backup, Site Recovery, Data Box
- Network: Virtual Network, Azure DNS, Traffic Manager, Application Gateway, Load Balancer, NAT Gateway, ExpressRoute, VPN Gateway, Private Link, Front Door, CDN
- Database: Azure Database for MySQL/PostgreSQL, Azure SQL, Cosmos DB, DocumentDB, Managed Instance for Apache Cassandra, Azure Cache for Redis, Azure Managed Redis, Database Migration Service
- Other: Entra ID, Defender for Cloud, Sentinel, Azure Monitor, Log Analytics, Service Bus, Event Hubs, Data Factory, Synapse Analytics, Machine Learning, Azure DevOps, IoT Hub

## Traffic Normalization

- Azure bandwidth charges may appear under `Bandwidth`, `Data Transfer`, `Inter-Region`, `Zone-to-Zone`, `Egress`, or product-specific meters. Apply the shared per-region Data Transfer consolidation rule to transfer charges, while preserving the original meter breakdown in `Notes`.
- Keep NAT Gateway resource-hour charges separate from NAT data-processed charges.
- Keep Front Door/CDN, Application Gateway, Load Balancer, ExpressRoute, VPN Gateway, and provisioned bandwidth charges as their own products unless the billed meter is specifically an outbound/egress or cross-region transfer component covered by the shared rule.

## Mapping Dataset

- Use `data/source-clouds/azure-hwc.csv`.
- Rows with an empty `Huawei Cloud Product` intentionally remain unmatched in Step 4 and require later review; do not infer a product merely because a neighboring Azure service has a mapping.

## Notes

- Azure product names often contain the word `Azure` or `Microsoft`; treat those as vendor branding rather than product-identifying matching terms.
- Azure SQL variants, serverless offerings, and globally distributed services commonly require `🟡` or `🔴` notes rather than `🟢`.
