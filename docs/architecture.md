# Architecture

CloudFront serves the React app from a private S3 bucket. Cognito authenticates
administrator-created users. API Gateway and a Lambda proxy validate access,
enforce usage limits and stream requests to an IAM-protected AgentCore runtime.
OpenSearch runs in private subnets; DynamoDB holds authoritative product records.

## Recommendation flow

1. **Analyze:** a skin agent reads the photos and produces a structured profile.
2. **Plan:** a planning agent chooses 2–8 steps from the configured catalog categories.
3. **Select ingredients:** an agent for each step selects preferred ingredient IDs
   using the profile, plan and bounded catalog discovery.
4. **Select products:** server code applies constraints, ranks exact matches and
   verifies product records. It selects up to three products per step.
5. **Explain and assemble:** agents explain the fixed product lists. Code rechecks
   catalog facts and assembles the routine in plan order.

Step-specific chains run concurrently. Progress arrives through Server-Sent Events;
a disconnected or failed stream is not a completed routine.

The explanation input reuses the structured plan and ingredient outputs. Code
joins each selected product's exact matched IDs to its ingredient reasoning and
attaches the routine's timing and order. It excludes unmatched ingredient
reasoning and prefilled fallback text. The explanation agent writes the final
wording; ingredient-level usage notes do not establish product-specific directions.

## Exact ingredient search

Names resolve through an explicit ingredient registry. Normalization handles
capitalization and whitespace; additional aliases must identify the same substance.
Unknown or ambiguous names remain unresolved. The bundled registry covers only
the demo labels. Similar names, derivatives and vitamin families are not
automatically interchangeable.

Each distinct preferred ingredient present in a product adds one point. A product
matching three preferences ranks above one matching two; ties use product ID.
Descriptions, ingredient-list position and repeated ingredients add no points.
There are no embeddings, vector queries or semantic reranking.

Explicit must-haves apply to their named category; exclusions apply across all
steps. Exclusions require a complete, fully resolved ingredient list. A price cap
requires a known price in the selected currency. Blank optional inputs impose no
must-haves, exclusions or price cap; market/currency use catalog defaults.

Search retrieves at most 100 index candidates and checks their canonical DynamoDB
records, initially ten with one bounded refill. Final assembly rechecks at most
24 selected products. Changed or ineligible products are removed. No eligible
products produces an explicit no-match result, not a substituted ingredient.

Each step has a 1.2-second search deadline, including queue time. DynamoDB
allows 250 ms to connect and 100 ms to read; metadata and product reads reserve
both limits before issuing a call. SDK retries are disabled; unprocessed keys
share one application retry within that same deadline. Release checks must cover
cold connections and concurrent searches inside the AgentCore VPC, including
canonical product reads and final validation. Warm or operator-laptop tests alone
do not qualify this path.

## Catalog updates

A trusted publisher writes product records and durable outbox events atomically.
Background workers project ordered revisions into OpenSearch; maintenance refreshes
ingredient summaries, reconciles records and checks readiness. Readiness failures
stop searches rather than serving an unchecked catalog. Registry/schema migrations
and index-generation cutovers require compatible data and current checkpoints.

## Models and boundaries

Skin analysis uses the Sonnet profile in `config.py`; planning, ingredients and
explanations use the Haiku profile. Bedrock Guardrails and structured-output
validation apply to model calls. Models cannot replace, reorder or fabricate the
server-selected product list. Generated explanations still require quality review.

The API accepts 1–3 images, each at most 1 MiB and 2048 pixels per side. It validates
and normalizes images before agent work. API v2 carries optional preferences and
explicit no-match outcomes; the original photos-only API remains supported.

Default admission permits five analyses per user per UTC hour, one active analysis
per user and ten concurrent proxy invocations. These are usage controls, not a
throughput guarantee. The sample has no persisted resume path after disconnecting.

See the [README](../README.md) for setup, customization, tests and cleanup.
