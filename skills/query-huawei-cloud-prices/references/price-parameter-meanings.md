# Price Parameter Meanings

Use this reference when explaining mapped fields in the compact price JSON. It summarizes the official Huawei Cloud API documentation; it does not contain a static price table. The query site determines the currency: the international portal uses USD and the China portal uses CNY.

## JSON Mappings

The query helper emits these stable English values:

## Region Names

`menuInfo.global` maps region codes to site-specific display names. The original `query_prices.py` accepts region IDs only. The separate `find_region_id_by_name.py` script only resolves a region ID from a region ID or display name using exact/contains fuzzy matching; it does not query product prices. It rejects ambiguous matches instead of guessing. International and China sites may have different display languages for the same region code.

| Source value | JSON value | Meaning |
| --- | --- | --- |
| `ONDEMAND` | `on-demand` | Pay-per-use price |
| `MONTHLY` | `monthly` | One-month subscription price |
| `YEARLY` | `yearly` | One-year subscription price when the source period is one year |
| `Duration` | `duration` | Usage by time duration |
| `upflow` | `upstream-traffic` | Upstream traffic usage |
| `downflow` | `downstream-traffic` | Downstream traffic usage |
| measurement ID `0` | `day` | Day |
| measurement ID `1` | `USD` | Currency |
| measurement ID `4` | `hour` | Hour |
| measurement ID `10` | `GB` | Gigabyte |
| measurement ID `14` | `count` | Quantity/count |
| measurement ID `15` | `Mbit/s` | Bandwidth capacity |
| measurement ID `17` | `GB` | EVS capacity |

The helper preserves an unknown source value rather than inferring it. `measureUnitStep` remains numeric because it is a step value, not a measurement-unit identifier.

For an EVS or bandwidth tier, `beginUnit` and `endUnit` are mapped to `unit` when both resolve to the same value. If they differ, the compact JSON keeps separate mapped `beginUnit` and `endUnit` fields.

## Usage Factors

The official price API documents these usage-factor meanings:

- Cloud servers, cloud disks, EIP, and KooGallery images use `Duration`.
- Bandwidth can use `Duration` or `upflow`.
- The portal may also expose `downflow`; the helper maps it to `downstream-traffic` when present.

An on-demand `amount` is a unit price according to the returned usage factor and measurement unit. It is not automatically a monthly total.

## Resource Specification Codes

The official documentation describes these codes:

| Resource type | Code | Meaning |
| --- | --- | --- |
| Bandwidth | `12_bgp` | Dynamic BGP bandwidth billed by traffic |
| Bandwidth | `12_sbgp` | Static BGP bandwidth billed by traffic |
| Bandwidth | `19_bgp` | Dynamic BGP bandwidth billed by bandwidth |
| Bandwidth | `19_sbgp` | Static BGP bandwidth billed by bandwidth |
| Bandwidth | `19_share` | Shared bandwidth billed by bandwidth |
| EIP | `5_bgp` | Dynamic BGP public IP address |
| EIP | `5_sbgp` | Static BGP public IP address |
| EVS | `SATA` | Common I/O EVS disk |
| EVS | `SAS` | High I/O EVS disk |
| EVS | `GPSSD` | General-purpose SSD EVS disk |
| EVS | `SSD` | Ultra-high I/O EVS disk |
| EVS | `ESSD` | Extreme SSD |
| EVS | `GPSSD2.storage` | General-purpose SSD V2 storage |
| EVS | `GPSSD2.iops` | General-purpose SSD V2 IOPS |
| EVS | `GPSSD2.throughput` | General-purpose SSD V2 throughput |

Keep the code itself in `resourceSpecCode` so it can be passed back to the calculator for exact filtering.

## Period and Capacity Semantics

The related Huawei Cloud pricing documentation defines:

- `period_type=0`: day
- `period_type=2`: month
- `period_type=3`: year
- `period_type=4`: hour
- `period_num`: number of periods; `period_type=3` and `period_num=1` means one year
- `resource_size`: subscribed capacity for a linear product such as an EVS disk or bandwidth
- `size_measure_id=15`: Mbit/s
- `size_measure_id=17`: GB
- `size_measure_id=14`: amount/count

These period and capacity definitions explain the portal response and must not be used to calculate a missing plan.

## Sources

- [Querying the Price of a Pay-Per-Use Product](https://support.huaweicloud.com/intl/en-us/api-oce/bcloud_01001.html)
- [Querying Measurement Units](https://support.huaweicloud.com/intl/en-us/api-oce/qct_00006.html)
- [Querying the Price of a Yearly/Monthly Product](https://support.huaweicloud.com/intl/en-us/api-oce/bcloud_01002.html)
