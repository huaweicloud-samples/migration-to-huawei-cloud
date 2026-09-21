# Specification Replacement Guide

## Purpose

Use this guide during Step 7 when reviewing and replacing unavailable or unsellable Huawei Cloud specifications in `output/billing_with_availability.md`. It provides the protocol for building candidate pools, ranking substitutes, and documenting replacement rationale.

## Candidate-Pool Protocol

When a row requires replacement (`Flavor Not Found` or `Unavailable`), build a candidate pool before choosing a substitute:

1. **Extract Baseline Attributes**:
   - Extract core attributes from `Source Spec`, `Recommended Spec`, and `Recommendation Notes`: topology, vCPU, RAM, storage capacity, media type, engine, edition, bandwidth class, cache mode, and service model (serverless vs. provisioned).
2. **Reuse Prior Evidence**:
   - Check the official documentation URLs and evidence recorded during the Step 5 category result before running new searches.
3. **In-Region Candidate Queries**:
   - Query the same Huawei Cloud product family for sellable candidates in the exact `HWC Target Region`.
   - Prefer machine-queryable product-family APIs when available, then confirm semantics via official documentation:
     - **ECS / BMS**: List flavors in-region and filter by flavor code or family.
     - **RDS / TaurusDB / GaussDB**: Query in-region flavors by `spec_code`, engine, and edition.
     - **DCS Redis**: Run `hcloud DCS ListFlavors --cli-region=<region> --spec_code=<redis.*>` and engine/mode filters.
4. **Shortlist**:
   - Maintain a shortlist of 2–5 candidates in working notes before making a final selection.

## Ranking Rules for Candidates

Rank candidates using the following priority order:

1. **Preserve Product Family**: Do not switch Huawei Cloud products unless the current family is proven indefensible.
2. **Preserve Deployment Topology**: Prioritize matching topology before raw size similarity (e.g., single vs. HA, cluster vs. proxy, serverless vs. provisioned, shared-storage vs. local-storage).
3. **Preserve Engine, Edition & Mode**: Match engine version, edition, and cache mode before tuning capacity.
4. **Capacity Sizing**: Prefer exact or minimally larger CPU, RAM, and capacity matches. Never silently downsize a workload-critical dimension.
5. **Least-Risk Fallback**: When no exact or upward-close candidate exists, choose the least-risk substitute and explicitly document the downgrade or model mismatch in `Recommendation Notes`.
6. **Machine Queryability**: Prefer candidates that remain machine-queryable so they can be re-verified by Step 6.

## Replacement Discipline

- **No Generic Placeholders**: Do not use non-specific labels (e.g., `DCS 固定规格实例` or `TaurusDB 共享存储 (按量)`) as substitutes.
- **Unresolved Rows**: If the only defensible recommendation is a service-model statement rather than a concrete sellable flavor, leave the row unresolved or `N/A`.
- **Serverless-to-Provisioned Floor**: If the source service is serverless and Huawei Cloud offers only provisioned capacity, estimate a conservative floor from observed billed capacity. If a concrete substitute still cannot be determined, keep the row unresolved with a `🟡` or `🔴` note.
- **Batch Recheck**: Resolve all candidate rows before rerunning Step 6 availability verification.
