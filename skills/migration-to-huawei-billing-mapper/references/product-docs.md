# Huawei Cloud Product Documentation Reference

> **Note:** This file is reserved for common spec quick-reference tables. Primary documentation lookup uses real-time WebFetch from Huawei Cloud official docs. Add curated reference data here as migration patterns emerge.
> `Notes` is a curated migration hint. Use it to record important capability caveats that must be reflected in recommendation notes. `—` means no curated note is recorded here and the official docs should still be checked when relevant.

## Documentation URLs

| Product Category | Official Doc URL | Notes |
|-----------------|------------------|-------|
| ECS (Elastic Cloud Server) | https://support.huaweicloud.com/intl/en-us/productdesc-ecs/ecs_01_0014.html | — |
| EVS | https://support.huaweicloud.com/intl/en-us/productdesc-evs/en-us_topic_0014580744.html | — |
| RDS | [PostgreSQL](https://support.huaweicloud.com/intl/en-us/productdesc-rds-pg/rds_01_0035.html) [MySQL](https://support.huaweicloud.com/intl/en-us/productdesc-rds-mysql/rds_01_0034.html) [DB storage](https://support.huaweicloud.com/intl/en-us/productdesc-rds-mysql/rds_01_0020.html) [MariaDB](https://support.huaweicloud.com/intl/en-us/productdesc-rds-mariadb/rds_01_0070.html) [SQL Server](https://support.huaweicloud.com/intl/zh-cn/productdesc-rds-mssql/rds_01_0036.html) | SQL Serever in the the international site are only available for whitelisting users. |
| TaurusDB | https://support.huaweicloud.com/intl/en-us/productdesc-taurusdb/taurusdb_01_0004.html [DB storage](https://support.huaweicloud.com/intl/en-us/productdesc-taurusdb/taurusdb_01_1000.html) [Serverless](https://support.huaweicloud.com/intl/en-us/price-taurusdb/taurusdb_00_0024.html) | Region support may be limited. Check the [official docs](https://support.huaweicloud.com/intl/en-us/usermanual-taurusdb/taurusdb_02_0210.html) for supported regions before recommending. Do not recommend TaurusDB if the target migration region is not listed as supported. |
| DCS | https://support.huaweicloud.com/intl/en-us/productdesc-dcs/dcs-pd-0522002.html | Does not support serverless. Do not present as a serverless equivalent in recommendation notes. |
| DMS for Kafka | [Single node](https://support.huaweicloud.com/intl/en-us/productdesc-kafka/kafka-pd-0056.html) [Cluster](https://support.huaweicloud.com/intl/en-us/productdesc-kafka/Kafka-specification.html) | Does not support serverless. Do not present as a serverless equivalent in recommendation notes. |
| DMS for RabbitMQ | https://support.huaweicloud.com/intl/en-us/productdesc-rabbitmq/rabbitmq-pd-190828004.html | Does not support serverless. Do not present as a serverless equivalent in recommendation notes. |
| ELB | https://support.huaweicloud.com/intl/en-us/price-elb/elb_billing_0003.html | — |
| NAT | https://support.huaweicloud.com/intl/en-us/productdesc-natgateway/en-us_topic_0086739763.html | — |
| APIG | https://support.huaweicloud.com/intl/en-us/productdesc-apig/apig-specifications.html | Does not support serverless. Do not present as a serverless equivalent in recommendation notes. |
| FunctionGraph | https://support.huaweicloud.com/intl/en-us/price-functiongraph/functiongraph_00_0012.html | - |
| GeminiDB | [Influx](https://support.huaweicloud.com/intl/en-us/influxug-nosql/nosql_05_0045.html) [Cassandra](https://support.huaweicloud.com/intl/en-us/cassandraug-nosql/nosql_05_0017.html) [Dynamo](https://support.huaweicloud.com/intl/en-us/dynamodbug-nosql/nosql_dynamodb_0005.html) | - |
| GaussDB | https://support.huaweicloud.com/intl/en-us/productdesc-gaussdb/gaussdb_01_010.html | Migration is usually complex. Do not assume it is a straightforward target replacement. Ask product specialists to assess feasibility before recommending or confirming a migration plan. |
| CAE | https://support.huaweicloud.com/intl/en-us/productdesc-cae/cae_01_0007.html | - |
| EIP | https://support.huaweicloud.com/intl/en-us/price-eip/eip_billing_0005.html | - |
| LTS | https://support.huaweicloud.com/intl/en-us/price-lts/lts_001_05.html | - |
| AOM | https://support.huaweicloud.com/intl/en-us/price-aom2/aom_07_0005.html | - |
| SFS Turbo | https://support.huaweicloud.com/intl/en-us/productdesc-sfsturbo/sfsturbo_01_0005.html | - |
| OBS | https://support.huaweicloud.com/intl/en-us/price-obs/obs_42_0001.html | - |
| CBR | https://support.huaweicloud.com/intl/en-us/price-cbr/cbr_07_0011.html | - |
| WAF | https://support.huaweicloud.com/intl/en-us/productdesc-waf/waf_01_0106.html | - |
| CFW | https://support.huaweicloud.com/intl/en-us/productdesc-cfw/cfw_01_0034.html | - |
| HSS | https://support.huaweicloud.com/intl/en-us/productdesc-hss2.0/hss_01_0136.html | - |
| DEW | https://support.huaweicloud.com/intl/en-us/price-dew/dew_03_0006.html | Includes KMS, CSMS sub-products |
| CBH | https://support.huaweicloud.com/intl/en-us/productdesc-cbh/cbh_01_0010.html | - |
| DBSS | https://support.huaweicloud.com/intl/en-us/productdesc-dbss/dbss_01_0268.html | - |
| SecMaster | https://support.huaweicloud.com/intl/en-us/productdesc-secmaster/secmaster_01_0111.html | - |
| MRS | [MRS Components](https://support.huaweicloud.com/intl/en-us/productdesc-mrs/mrs_08_0005.html) [Billing items](https://support.huaweicloud.com/intl/en-us/price-mrs/mrs_12_000006.html) | - |
| DLI | https://support.huaweicloud.com/intl/en-us/productdesc-dli/dli_07_0027.html | - |
| DWS | https://support.huaweicloud.com/intl/en-us/productdesc-dws/dws_01_00018.html | - |
| CSS | https://support.huaweicloud.com/intl/en-us/price-css/css_01_0228.html | - |
| DataArts Studio | https://support.huaweicloud.com/intl/en-us/productdesc-dataartsstudio/dataartsstudio_07_009.html | - |

## Usually Non-Billable Huawei Cloud Services

These services are often mapped during migration but typically do not need a flavor-style spec recommendation.

- DNS
- SWR
- CES
- COC
