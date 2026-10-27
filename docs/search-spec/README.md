# Exact ingredient product search specification

**Version 2.0 · 2026-10-26 · Implementation in progress**

Implement indexed exact ingredient matching with hard eligibility filters and
ranking by the number of distinct preferred ingredients present. OpenSearch is
the selected search implementation; DynamoDB remains the authoritative catalog.
This package replaces the earlier hybrid-search proposal.

The ingredient agent decides which ingredients to prefer for a step. Search
finds products containing those exact identities. The product agent explains the
server's selected products. Each responsibility has a separate contract.

## Product behavior

For preferred ingredients A, B and C, and an explicit must-have A:

| Product ingredients | Result |
|---|---|
| A, B, C | Eligible; score 3 |
| A, B | Eligible; score 2 |
| A only | Eligible; score 1 |
| B, C | Ineligible: missing must-have A |
| A, B, C plus an explicitly excluded ingredient | Ineligible |

Return up to three products in descending match-count order, with stable product
ID ties. Return fewer when fewer qualify. Show “Matches 2 of 3 selected
ingredients”; this is ingredient coverage, not an effectiveness or suitability
probability.

Explicit must-haves are scoped to a named category/step. Explicit exclusions
apply to every product in the routine. A must-have for a serum does not become
a requirement for the cleanser. The server preserves these constraints throughout
planning and finalization.

The matching path contains no embeddings, product-description scoring, substring
substitution, position weighting, ingredient-family substitution, or model
reranking. A reviewed alias may resolve two names for the same ingredient to the
same ID. A related ingredient remains a different ID.

## Scope and boundaries

| Item | Specification |
|---|---|
| Catalog scale | Up to 1,000,000 active products; checkpoints at 1k, 10k and 100k |
| Traffic | 20 incoming routines/second; six typical and eight maximum steps |
| Search traffic | 120 typical / 160 maximum logical product searches/second, before retries |
| Deployment | One catalog/customer deployment in one AWS Region |
| Search | One exact-count query per step; at most 100 returned candidate IDs |
| Authoritative reads | Initially 10 candidates; one refill up to the 100-candidate total |
| Result | Up to three products per step, or an explicit no-match |
| Data updates | Durable publication, ordered revisions, tombstones and reconciliation |
| Application | Ingredient tools, selection, binding, compiler, versioned API and browser |
| Production evidence | Actual deployed search and full-routine load, update/failure tests and cost |

Availability is a declared deployment policy. `catalog` mode permits products
whose stock is unknown and makes no stock claim. `purchasable` mode requires
verified stock, market and currency. Unknown facts fail any constraint that
depends on them. The public research data did not establish purchase availability.

The proposed latency, update and cost gates are in
[acceptance-targets.yaml](acceptance-targets.yaml). They are implementation
targets; the local benchmark did not pass the production gates.

## Specification package

| Document | Purpose |
|---|---|
| [Technical specification](technical.md) | Data and API contracts, exact algorithm, consistency, ingestion, private access and failure behavior |
| [Verification strategy](verification.md) | Requirement traceability, exact oracles, integration, deployed capacity and release evidence |
| [Delivery plan](delivery.md) | Work packages, repository file changes, estimates, migration and rollback |
| [Acceptance targets](acceptance-targets.yaml) | Machine-readable limits and proposed release thresholds |
| [Index mapping](examples/index-mapping.json) | Explicit mapping for the selected product-search projection |
| [Search query](examples/search-query.json) | Concrete exact-count query with mandatory and exclusion filters |
| [Contract examples](examples/contracts.json) | Preference fragment, internal request and public step outcomes |

The exact search path is connected to the application. See
[implementation status and the completion audit](implementation.md) for executed
checks and outstanding requirements. The specification's deployment gates have
not been passed.

## Evidence behind the decision

The [completed study](decision-evidence.md) provides:

- 6,000 generated requests over public product records; the indexed implementations
  reproduced every ordered exhaustive-reference top-100 list.
- Filtered exact harmonic ranking lost attainable top-three ingredient matches
  on 1,807 requests, or 30.1%.
- One million synthetic records; 151,256 measured searches across six local load
  cells, zero failures or deadline misses, and p95 latency of 16.95–19.84 ms.

This evidence supports the agreed matching objective and a local component
capacity screen. Customer ingredient identity, planning quality, canonical-store
reads, AWS capacity and full-routine behavior require their own implementation
checks. The spec does not reopen the semantic-method comparison.

## Delivery expectation

Plan **15–22 engineering person-days for an integrated test MVP** and
**44–65 person-days for the production scope including contingency**. With two
engineers, the latter is roughly **6–9 elapsed weeks**, subject to feed readiness,
cloud quotas and rollout observation. These are revised planning estimates,
not measured delivery velocity. See the [work breakdown](delivery.md).

Implementation is underway. Before
customer release, record the feed's stable IDs and ingredient registry, field
completeness, availability policy, deployment region/capacity, and cost ceilings.
Those deployment inputs do not change the selected ranking rule.
