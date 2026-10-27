# Exact ingredient search operations

This runbook describes the implemented control path. Cloud qualification is
tracked in [implementation.md](implementation.md); local passing tests are not
deployment or release approval.

## Initialize an environment

1. Select the intended account/profile and Region. Inspect the existing Terraform
   state and account-level API Gateway/OpenSearch roles before applying shared
   resources. Import existing shared resources instead of recreating them.
2. Build the locked proxy and catalog-worker archives. Review the Terraform plan,
   network boundaries and cost estimate. The private domain, two data nodes and
   interface endpoints incur charges while running.
3. Deploy the environment. The admin Lambda `initialize` action creates the
   strict keyword mapping, IAM role mappings, registry, manifest and all 16
   source/projection shards. Missing readiness fails closed while initial
   publication and reconciliation complete.
4. `scripts/deploy.sh` publishes the explicitly fictional bundled demo only into
   an empty catalog, then waits for fresh, healthy readiness and equal
   per-shard watermarks. It can resume its own interrupted demo import; it
   refuses to overwrite an unhealthy supplier import.
5. Configure `search_alarm_actions` with the operating team's alarm destination.
   Verify delivery and the `search_dashboard_name` output before release.

The current application default remains ten simultaneous proxy invocations,
five analyses per user/hour and one active analysis per user. Raising the proxy
setting must fit applied account quotas and retain the per-user limits. A quota
and test-workload plan is required for 20 routines/second.

## Publish supplier facts

Use `scripts/migrate_products.py --help` for the streaming JSONL import. Supply
the canonical table, metadata table and outbox table outputs. Attach the
`catalog_publisher_policy_arn` policy only to the trusted publisher identity.
Application, proxy and projection identities cannot write canonical products.

Every row has a stable supplier product ID, strictly increasing integer revision,
explicit category, provenance and timezone-aware source timestamp. The registry
normalizer resolves only exact identities and reviewed same-identity aliases.
Missing market, price, stock and list-completeness facts stay unknown. Failed
normalization leaves source health false; repair the source and replay it.
Never acknowledge an import after skipping invalid rows.

Event identity is `catalog/product/revision`. The base outbox key is
`catalog_shard` plus a monotonically increasing `sequence`, with 16 deterministic
product shards. Canonical product, event and counter advance in one conditional
transaction. Duplicate revision/content is idempotent; changed content at the
same revision is an integrity failure. Retries use the same supplier revision.

The importer defaults to an immutable `snapshot` feed. A `live` publisher must
call `CatalogPublisher.set_source_health(..., mode="live")` at least every 60
seconds, normally every 30 seconds. No updates and no heartbeat are distinct.
The bundled demo's stable IDs are preserved in `data/product-id-migration.json`.
Real feeds need their own reviewed ID mapping before migration.

## Diagnose lag and failed publication

The admin Lambda's `status` action returns the active manifest, source
watermarks, retained generations, shard acknowledgements and rebuild cursor.
Workers are awakened by the outbox stream and by independent minute schedules.
An expired shard lease is reclaimed conditionally; every checkpoint write is
fenced against the current owner and expiry.

`PROJECTION#00` through `PROJECTION#15` contain a separate sequence and error
record for each generation. A batch failure keeps its checkpoint unchanged.
Its bounded diagnostic contains the next sequence and event identities; the
immutable event body remains in the outbox. Fix transient dependencies and
allow replay. Never manually advance a checkpoint past an error or capture gap.
A failed retained generation does not stop successful generations advancing.

Bulk conflicts are accepted only after checking the stored revision and equal
revision content. A newer deletion remains a full tombstone. An equal-revision
content conflict requires investigation and a fresh reconciled generation,
not an overwrite using `external_gte`.

`PublicationLag` alarms at 60 seconds. Runtime admission rejects unresolved
changes aged 300 seconds, readiness older than 60 seconds, unhealthy feeds or
integrity/capture failures. Do not bypass readiness to make a test pass.
Inspect the event, canonical revision and index source together.

## Reconciliation and discovery

The maintenance role alone can scan canonical products and search index
snapshots. A resumable canonical pass replays authoritative full revisions;
an index pass checks IDs, versions, hashes and tombstones against strong
canonical reads. Newer concurrent canonical revisions are replayed. An index
identity missing from canonical storage or equal-revision disagreement is
quarantined. The next reconciliation starts after 12 hours to allow completion
within the 24-hour requirement; overdue evidence disables readiness.

`RECONCILIATION#<generation>` records phase, cursor, snapshot, start watermarks,
completion and errors. Lost PIT snapshots restart the entire index-side pass.
Transient failures retain the page and use a 30-second retry delay. Quarantined
generations require a reviewed repair/new generation.

`SUMMARY_BUILD` persists a fixed PIT and a composite category/ingredient cursor.
It retains only the deterministic top 30 per category in memory/metadata.
Completed summaries and their completion marker publish together, including
empty categories. Their generation and snapshot time are explicit. The next
build starts after three minutes; five-minute refresh remains a qualification
target. Discovery summaries are always advisory and do not gate rare identities.

## Rebuild, cutover and rollback

Invoke admin actions with JSON payloads through an authorized Lambda caller:

```json
{"action":"start_rebuild","generation":"products-20261027-b"}
```

`start_rebuild` registers the new generation and all 16 capture checkpoints
atomically while holding the shard/maintenance leases. Changes are mirrored
while the maintenance worker scans canonical products in bounded pages.
Monitor `REBUILD` and the generation's reconciliation record.

If a never-served rebuild is irrecoverable, `abort_rebuild` with its generation
stops mirroring it and permits a new generation. This retains its index and
diagnostics. It cannot abandon an active or previously served generation.

```json
{"action":"activate","generation":"products-20261027-b"}
```

Activation requires completed backfill, a recent successful reconciliation,
healthy source/index and all generation acknowledgements caught up. It atomically
updates the operational alias and then conditionally publishes the runtime
manifest against all 16 source watermarks and feed state. A failed transaction
leaves the old runtime manifest authoritative; rerun activation after catch-up
to reconcile alias and manifest. Existing routines keep their pinned compatible
generation.

Rollback uses the same `activate` action with the prior retained generation and
the same checks. An old stale index is not a fallback. Keep prior generations
mirrored for at least seven days and the entire replay horizon. `retire` stops
mirroring only after the grace period; it does not delete indices or history.
At most three generations can be retained by this implementation.

No automatic outbox, canonical tombstone or index deletion is configured.
This deliberately retains identity high-water marks. Storage pruning requires a
separate reviewed retention procedure; pending work must never expire.
An incompatible schema/registry migration needs a separate normalization and
reader-compatibility plan.

## Metrics and qualification

Embedded metrics use `SmartBeauty/ExactSearch` with the bounded `Deployment`
dimension. Generation/shard details remain log context. The dashboard separates
offered/admitted requests, compiled completion, failures and cancellation.
`RoutineStreamsCompleted` measures transport completion, not domain success.
Load generators must independently count offered requests, including requests
rejected before Lambda admission.

Search latency includes scheduled queue time, readiness, query, canonical reads
and binding. Candidate/read counts and retries accompany successful results.
Reconciliation age, publication lag, unhealthy generations and worker/admin
failures have alarms. Model cost, feed-to-canonical latency, AZ-failure recovery,
canary results and other release evidence still need deployed qualification.

For this task use the [approved USD 200 budget](qualification-budget.md).
Review estimated maximum spend before every paid phase, reserve cleanup funds
and record all retained resources. Run cleanup against only this task's
verified isolated environment after preserving evidence; never destroy shared
account resources or unrelated catalogs.
