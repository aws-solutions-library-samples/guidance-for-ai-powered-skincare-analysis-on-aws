# Qualification budget

The user approved a **USD 200 total qualification ceiling on 2026-10-27**.
The selected Region is `eu-west-1`; the account and profile are supplied explicitly
to the test harness and recorded in its private run manifest.
The ceiling includes infrastructure, ingestion, model calls, retries, logs,
load generators, rebuilds and cleanup time. It does not change the performance
or correctness requirements in `acceptance-targets.yaml`.

The managed DynamoDB transaction test passed on 2026-10-27. It used three
disposable tables, published 17 events across 16 shards, checked duplicate/stale
revision handling and lease fencing, and verified deletion of all three tables.
It reserved USD 1; its conservative request bound was USD 0.1793. This is an
estimate, not a reconciled AWS bill. No paid model calls have been made.

The managed search phase reserves USD 50 for private component tests and
cleanup. Its reviewed plan creates 108 resources in separate local state with a
unique prefix. It does not deploy the frontend, AgentCore runtime or models.
Minute schedules are disabled in this test copy; the harness invokes workers and
maintenance explicitly. A private probe uses the unchanged runtime search/read
IAM statements with a Lambda trust principal. Results therefore cannot qualify
the actual AgentCore trust policy, network startup or application request path.

Verified eu-west-1 unit prices on 2026-10-27:

| Item | Unit price | Bounded phase provision |
|---|---:|---:|
| OpenSearch r6g.large.search | USD 0.187/node-hour | 2 nodes |
| Interface VPC endpoints | USD 0.011/interface-hour | 14 interfaces |
| OpenSearch gp3 storage | USD 0.1342/GiB-month | 60 GiB |
| DynamoDB on-demand reads | USD 0.1415/million request units | Bounded fixture reads |
| DynamoDB on-demand writes | USD 0.705/million request units | Bounded fixture writes |

The fixed search/network/storage estimate is about USD 0.54/hour. Apply is
bounded to 45 minutes, tests to 30 minutes and teardown to 45 minutes; the reserve
also includes 24 hours of cleanup headroom and USD 20 for requests, logs, Lambda,
metrics and storage overhead. The phase estimate is below USD 35, with USD 50
reserved. The harness always attempts teardown and reports any remaining state
as a cleanup failure. USD 149 remains unallocated while both reservations are
held. Do not release the cleanup reserve until resource deletion is verified.
Two failed component attempts are retained in separate private manifests: the
first failed at domain creation and removed all 60 partial resources; the second
provisioned the domain but found the native TLS client defect. Its domain,
functions, tables and network were removed, while IAM cleanup was denied.
The phase reserve remains held for that cleanup and the corrected rerun.
No cost figure here is a reconciled bill.

Before deployment, record current unit prices and a worst-case estimate for the
bounded run. Reserve cleanup headroom. Track test requests, tokens, failed
attempts, resource hours and remaining budget locally; do not depend on delayed
billing data to stop a load generator. Do not start a phase whose estimated
maximum cost exceeds the unreserved remaining amount.

The required four-hour full-model soak alone offers 288,000 routines at
20 routines/second. Warm-ups, repeated measured cells and bursts are additional.
A smaller model sample or search-only load test must be reported under its
actual scope; it cannot pass the full-model gate. Any gate that cannot fit this
budget remains unqualified.

The current six-step graph makes at least one Sonnet 4.6 call and thirteen Haiku
4.5 calls per routine, before tool turns and retries. The official Bedrock pricing
page's Global Cross-region table for Europe (Ireland), checked on 2026-10-27,
lists Sonnet input/output at USD 3/15 per million tokens and Haiku at USD 1/5.
An illustrative 3,000 input and 500 output tokens per call would cost about
USD 0.088/routine, or USD 25,344 for the four-hour soak alone, before guardrails
and infrastructure. These token counts are assumptions, not measured usage or
a minimum cost. A full-model soak cannot be represented by the bounded component
test or silently shortened to claim the gate passes.

Read-only preflight found a Lambda account concurrency quota of 1,000 in the
selected account/Region. This is an account limit, not proof of throughput or
available capacity for this application. The current application default of
ten proxy invocations is also not a qualified 20-routine/second configuration.

Official references used for preflight:

- [AWS Price List GetProducts](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html)
- [Lambda GetAccountSettings](https://docs.aws.amazon.com/lambda/latest/api/API_GetAccountSettings.html)
- [Service Quotas ListServiceQuotas](https://docs.aws.amazon.com/servicequotas/2019-06-24/apireference/API_ListServiceQuotas.html)
- [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)
- [DynamoDB CreateTable](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_CreateTable.html)
- [DynamoDB DeleteTable](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_DeleteTable.html)
- [Lambda Invoke](https://docs.aws.amazon.com/lambda/latest/api/API_Invoke.html)
- [OpenSearch ListVersions](https://docs.aws.amazon.com/opensearch-service/latest/APIReference/API_ListVersions.html)
- [OpenSearch VPC service-linked role](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/slr-aos.html)
