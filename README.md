# Guidance for AI-Powered Skincare Analysis on AWS

## Table of Contents

[Overview](#overview) · [Prerequisites](#prerequisites) · [Deploy](#deployment-steps) ·
[Validate](#deployment-validation) · [Use](#running-the-guidance) ·
[Develop](#next-steps) · [Cleanup](#cleanup) ·
[Limitations](#faq-known-issues-additional-considerations-and-limitations) ·
[Revisions](#revisions) · [Notices](#notices) · [Authors](#authors)

## Overview

Smart Beauty turns skin photos into a suggested skincare routine. AI agents analyze
the photos and select preferred ingredients; server code finds products by exact
ingredient matches, and the agents explain the selected products.

The sample includes a React web app, Cognito sign-in, a streaming API, agents
hosted on Amazon Bedrock AgentCore, a private OpenSearch index and a DynamoDB
catalog. **Product search uses no embeddings or semantic similarity.**

![Smart Beauty reference architecture](assets/images/architecture.png)

The reference image predates the private search and catalog-update components.
The short [architecture guide](docs/architecture.md) describes the current flow.

**Cost:** deployment creates billable resources. Search nodes and VPC endpoints
incur charges while idle; model calls and other usage add to them. Estimate your
configuration with the [AWS Pricing Calculator](https://calculator.aws/) and
remove test environments when finished.

## Prerequisites

- macOS or Linux; Windows users need WSL2.
- Python 3.11+, Node.js 24, [uv](https://docs.astral.sh/uv/getting-started/installation/),
  Terraform 1.5+ and AWS CLI v2.
- An authenticated AWS CLI profile with permission to deploy the services in
  `terraform/`. Start with a dedicated test account.
- Amazon Bedrock access to the configured Claude Sonnet 5.5 and Haiku 5.5 models.
  Complete the [model-access prerequisites](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html).

Terraform accepts `us-east-1` (default), `us-west-2` and `eu-west-1`. Confirm model
availability and account quotas in your chosen region. The configured global
inference profiles can process requests outside that region.

## Deployment Steps

```bash
git clone https://github.com/aws-solutions-library-samples/guidance-for-smart-beauty-on-aws.git
cd guidance-for-smart-beauty-on-aws
make setup

export AWS_PROFILE=your-profile
export AWS_REGION=us-east-1
aws sts get-caller-identity
make deploy ENV=test
make create-user EMAIL=user@example.com
```

`make setup` installs local dependencies and packages the workers without AWS
changes. `make deploy` applies Terraform, builds the runtime and frontend, and
loads the fictional catalog into an empty environment. It applies changes without
another confirmation prompt. The created user receives an invitation email.

Review `terraform/env-test.tfvars`, `data/search-config.json` and
`data/ingredient-registry.json` before deploying. Optional overrides belong in
the ignored `terraform/terraform.tfvars`; start from
`terraform/terraform.tfvars.example`. Supported environments are `dev`, `test`,
`staging` and `prod`.

Each environment uses its own `<environment>/terraform.tfstate`. API Gateway
logging is shared: deployment reuses an existing role or creates one through
`terraform/shared/`. Do not overwrite another application's shared configuration.

Run `make deploy ENV=test` again from an updated checkout to update that same
environment. The source hash determines whether the agent image is rebuilt.

## Deployment Validation

```bash
terraform -chdir=terraform output
terraform -chdir=terraform output -raw app_url
```

Open the app URL and complete sign-in, photo upload and an analysis. Confirm that
progress arrives before the final routine and that product details match the
catalog. A successful Terraform apply alone does not verify the application.

Optional live checks are available through
`uv run --locked python -m tests.live_release --help` and
`uv run --locked python -m tests.live_models --help`. They require explicit
test-account and execution options and can incur AWS charges.

## Running the Guidance

1. Open the app URL and sign in. Set a new password on first login.
2. Capture or upload the three photos requested by the browser.
3. Optionally expand **Ingredient preferences** to set exclusions, category
   must-haves or a maximum price per product. Blank inputs impose none of these.
4. Start analysis and review the routine, product match counts and any no-match
   results. A match count measures ingredient coverage, not effectiveness.

## Next Steps

**Run local checks** after `make setup`:

```bash
make test
terraform -chdir=terraform init -backend=false -lockfile=readonly
terraform -chdir=terraform/shared init -backend=false -lockfile=readonly
make validate
```

Tests use mocked AWS boundaries unless you explicitly run a live checker.

**Use your own catalog:** configure categories in `data/catalog.yaml` and
`data/search-config.json`, and provide a validated identity/alias registry in
`data/ingredient-registry.json` before the first deployment. The bundled registry
is a demo dictionary, not a universal ingredient database. Supplier JSONL records
need stable product IDs, increasing revisions and explicit ingredient, category,
provenance and timestamp fields; price, currency, market, stock and ingredient-list
completeness must come from the supplier. See the importer contract in
[`scripts/migrate_products.py`](scripts/migrate_products.py).

```bash
make migrate-products SOURCE_JSONL=/absolute/path/to/supplier.jsonl
```

Use the intended environment's initialized Terraform state and a trusted publisher
identity. Registry/schema changes in an existing catalog need an explicit migration;
editing the local JSON files alone does not update its published registry.

**Find the code:**

| Path | Purpose |
| --- | --- |
| `agents/`, `prompts/`, `config.py` | Workflow, exact search and model settings |
| `frontend/`, `api_proxy/` | Browser app and authenticated streaming API |
| `data/`, `catalog_worker/` | Catalog configuration, fixtures and publication |
| `terraform/`, `scripts/` | Infrastructure, deployment and cleanup |
| `tests/` | Application and deployment checks |

Model changes must keep `config.py` and `terraform/iam.tf` consistent. Follow
[CONTRIBUTING.md](CONTRIBUTING.md) for contributions.

## Cleanup

```bash
make destroy ENV=test
```

Use the same account, region and environment as deployment. The command asks for
confirmation and deletes that environment's infrastructure and data. Nonempty
buckets/repositories can block staging/production deletion; the production user
pool also has deletion protection.

Shared API Gateway logging, the state bucket, lock table and account-level service
roles remain. Keep them while another environment or application depends on them.
Preserve Terraform state until environment teardown is verified.

## FAQ, Known Issues, Additional Considerations, and Limitations

- The sample has **48 fictional products and 61 fixture ingredient identities**,
  with GB/GBP defaults and no extra aliases. Real catalog integration requires
  reviewed mappings and supplier facts.
- Camera access requires HTTPS or localhost. Self-registration is disabled;
  administrators create users.
- Application code handles photos in memory. Review managed-service logging,
  retention, processing regions and the custom-domain TLS configuration before
  production use.
- The pinned AWS telemetry dependency has an unresolved
  [OpenTelemetry advisory](https://github.com/advisories/GHSA-xcq7-p3pf-p88h).
  Production security, capacity and recommendation quality are not qualified.
- For failures, use the request reference and actual CloudWatch error. Report
  security concerns through [SECURITY.md](SECURITY.md).

## Revisions

| Date | Description |
| --- | --- |
| June 2026 | Initial release |

## Notices

*Customers are responsible for making their own independent assessment of the information in this Guidance. This Guidance: (a) is for informational purposes only, (b) represents AWS current product offerings and practices, which are subject to change without notice, and (c) does not create any commitments or assurances from AWS and its affiliates, suppliers or licensors. AWS products or services are provided "as is" without warranties, representations, or conditions of any kind, whether express or implied. AWS responsibilities and liabilities to its customers are controlled by AWS agreements, and this Guidance is not part of, nor does it modify, any agreement between AWS and its customers.*

## Authors

- **Rania Khemiri** — Prototyping Architect
- **Sophie Manuella Siake Tchouamou** — Delivery Consultant
