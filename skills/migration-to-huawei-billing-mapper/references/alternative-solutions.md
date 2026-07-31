# Migration Alternative Solutions Reference Guide

This guide is for resources in the migration inventory that cannot be implemented through a one-to-one product mapping. It is not a product matching table and does not replace official product documentation, service-region checks, or capacity testing. The `Huawei Cloud Product` in Step 4 must still come from a validated mapping; this guide only supplements Step 8 with alternative architecture paths for resources with clear migration risks.

## Scope

Generate an alternative solution only when at least one of the following conditions applies:

- `Recommendation Notes` is `🟡` or `🔴`, and there is a clear difference in the service model, runtime, functionality, or operational boundary;
- The recommended product is `Unavailable`, cannot be confirmed, or has no justifiable sellable specifications in the target region;
- The source resource is serverless, a managed platform, or a proprietary service, and direct migration would introduce long-term fixed capacity, complex operations, or a significant change in the cost model;
- The estimated post-migration fixed, modernization, or operational costs are significantly higher than the source resource's actual usage scale;
- The source has a very small resource volume and an obvious low-usage baseline, while a lighter Huawei Cloud service can cover the core business objectives.

Do not generate an alternative solution for an approximately one-to-one `🟢` mapping merely to make the report look complete. Generate an alternative architecture only when changing products alone is insufficient to address the differences. An alternative solution may also be to retain the original recommendation, split components, reduce the specification, switch to self-hosting, or defer migration.

## Evaluation Sequence

Evaluate each candidate resource in the following order and record the evidence:

1. Confirm the capabilities the source resource actually requires: throughput, latency, persistence, ordering, retries, HA, elasticity, data volume, connection count, compliance, and operational responsibility.
2. Read `Source Spec`, `Qty`, `Source Est. Resource Count`, `Monthly (USD)`, `Recommendation Notes`, and `Availability`. Do not judge cost or capacity based only on the product name.
3. Assess whether the direct recommendation changes the service model or introduces fixed costs that did not exist on the source side. Serverless to provisioned instances, managed services to self-hosting, and a single AZ to an HA cluster should all be rated at least `🟡`.
4. Find candidate paths in this guide's pattern table and use official product documentation to confirm capabilities, regions, and specifications. Mark paths without official evidence as pending verification; do not present them as confirmed solutions.
5. Compare at least two reasonable paths, including retaining the direct recommendation, and rank them by migration effort, operating cost, reliability, operational burden, and functionality loss.
6. Select a path for the report only when it meets the core business capabilities. If this cannot be determined, output "Pending business confirmation" rather than forcing a product replacement.

## Alternative Solution Patterns

### 1. Low-Volume Serverless Messaging -> DCS Redis

**Applicable conditions**: Message throughput and backlog are both small, short-term message retention is acceptable, and the business can implement acknowledgements, retries, and consumer cursors in the application layer. The workload must not depend on full MQ capabilities such as consumer groups, dead-letter queues, strict persistence, or complex routing.

**Recommended path**: Use a List or Stream in DCS Redis as a lightweight message buffer. The producer and consumer implement message enqueueing, consumption acknowledgement, timeout retries, idempotency, and expiration cleanup. The report must state that this is a "lightweight message buffer alternative," not a functional equivalent of serverless MQ.

**Do not use when**: Long-term reliable retention, cross-AZ disaster recovery, strict ordering, native dead-letter/retry policies, large-scale consumer groups, audit replay, or high-throughput scaling is required. Evaluate DMS for Kafka or DMS for RabbitMQ first. If the target region or specifications are unavailable, retain this as a pending-confirmation option.

**Differences that must be disclosed**: DCS does not provide serverless billing semantics or automatically provide the acknowledgement, dead-letter, routing, and consumer-group capabilities of a full MQ service. Confirm Redis data persistence, maximum message size, memory capacity, failure recovery, application changes, and expiration policies. See the official documentation for DCS, DMS for Kafka, and DMS for RabbitMQ in `references/product-docs.md`.

## Solution Selection and Report Format

Alternative solutions must appear in a separate section of the final report after all resource tables, using the standalone second-level heading `## Alternative Solutions Reference`. Each solution must be an independent third-level subsection. Do not put it in `Recommended Spec` or `Recommendation Notes`, and do not modify the original monthly cost figures.

Each subsection must contain at least the following fields. Use the user's language for the field names and descriptions:

```markdown
### <Solution Number>: Alternative path for <Source Product/Resource>

- **Triggering resource**: <Category / # / Source Product / Source Spec / Region>
- **Triggering reason**: <Significant differences, target-region unavailability, excessive cost, or another verifiable reason>
- **Direct migration conclusion**: <Retain recommendation / Direct migration not recommended / Pending confirmation>
- **Recommended solution**: <Huawei Cloud product or combination, and the core architecture changes>
- **Prerequisites**: <Prerequisites for throughput, data volume, persistence, HA, latency, compliance, and so on>
- **Key differences and required changes**: <Service model, functionality gaps, application changes, and operational responsibility>
- **Cost assessment**: <Describe only the cost direction and billing items that need to be recalculated; do not invent prices>
- **Risks and validation**: <PoC, load testing, failure drills, data validation, or business confirmation items>
- **Evidence**: <Local cache files and/or official documentation URLs>

A resource may have multiple candidate solutions, but the report should provide no more than one "recommended solution" and two alternative directions, to avoid presenting users with a collection of unverified architectures. If multiple resources belong to the same migration pattern, they may be combined into one subsection, but all triggering resource numbers and regions must be listed.

## Prohibited Practices

- Do not describe DCS Redis as serverless MQ or as an equivalent replacement for a full MQ service;
- Do not remove persistence, HA, auditing, compliance, or security capabilities merely because the monthly cost is low;
- Do not fabricate specifications, regional availability, prices, performance, or product capabilities based on experience;
- Do not write a self-hosted component that has not completed a PoC as a confirmed migration target;
- Do not overwrite or rewrite the `Monthly (USD)`, source product, source specification, or direct recommendation fields in the original inventory;
- If throughput, peak load, data retention, RTO/RPO, or compliance requirements are missing, list them as business confirmation items under "Risks and validation".
