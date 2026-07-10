# AWS Source Module

## Purpose

Use this module when the source billing data clearly comes from AWS.

## Recognition Signals

- Product names such as `Amazon EC2`, `Amazon RDS`, `Amazon S3`, `AWS Lambda`
- Region IDs such as `us-east-1`, `ap-southeast-1`, `eu-west-1`
- Export names such as CUR, Cost Explorer, or AWS invoice CSV/PDF labels

## Parsing Hints

- Many line items embed region directly in the row
- Some rows inherit region from a nearby section header or grouped subtotal
- Traffic rows are often fragmented into `Data Transfer`, `NAT Gateway Data Processed`, `Regional Data Transfer`, `Elastic IP`, and ELB transfer labels

## Category Alias Hints

- Compute: EC2, ECS, EKS, Fargate, Lambda, Lightsail
- Storage: S3, EBS, EFS, Glacier, Backup, FSx
- Network: VPC, Route 53, ELB, NAT Gateway, CloudFront, Direct Connect, Transit Gateway
- Database: RDS, Aurora, DynamoDB, ElastiCache, Redshift, DMS
- Other: CloudWatch, IAM, KMS, SNS, SQS, SageMaker, CodePipeline

## Mapping Dataset

- Use `data/source-clouds/aws-hwc-product.csv`
- This is the most complete source module in the current skill

## Notes

- AWS traffic cost labels are especially fragmented. Normalize aggressively before merging.
- Aurora, Lambda, and some AWS-native platform services frequently require `🟡` or `🔴` notes rather than `🟢`.
