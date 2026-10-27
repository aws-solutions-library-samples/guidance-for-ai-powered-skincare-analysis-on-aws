# Guidance for AI-Powered Skincare Analysis on AWS

## Table of Contents

1. [Overview](#overview)
    - [How it works](#how-it-works)
    - [Architecture](#architecture)
    - [Cost](#cost)
2. [Prerequisites](#prerequisites)
    - [Operating System](#operating-system)
    - [Third-party Tools](#third-party-tools)
    - [AWS Account Requirements](#aws-account-requirements)
    - [Supported Regions](#supported-regions)
3. [Deployment Steps](#deployment-steps)
4. [Deployment Validation](#deployment-validation)
5. [Running the Guidance](#running-the-guidance)
6. [Next Steps](#next-steps)
7. [Cleanup](#cleanup)
8. [FAQ, Known Issues, Additional Considerations, and Limitations](#faq-known-issues-additional-considerations-and-limitations)
9. [Revisions](#revisions)
10. [Notices](#notices)
11. [Authors](#authors)

## Overview

This Guidance demonstrates how to build a personalized skincare analysis application using a multi-agent AI architecture on AWS. A user submits up to three skin photos through a secure web interface. Specialized AI agents analyze the photos, plan a routine, and select products from the catalog while the application streams progress to the user.

The multi-agent system is orchestrated as a directed graph using the [Strands Agents SDK](https://github.com/strands-agents/sdk-python) and runs on Amazon Bedrock AgentCore Runtime. Specialized agents handle skin analysis, routine planning, ingredient selection, and product matching against a DynamoDB-backed catalog. Progress and intermediate results stream to the frontend via Server-Sent Events (SSE).

### How it works

#### 1. Analyze and plan

The skin-analysis agent turns the photos into a structured skin profile. The planning agent uses that profile and the available catalog categories to choose 2–8 distinct routine steps, including their order, timing, and rationale.

![Analyze and plan: illustrated facial observations lead to a structured skin profile and an ordered routine plan.](assets/images/analyze-and-plan.png)

**The skin profile and ordered plan carry forward into product selection.**

#### 2. Select and assemble

Each planned step runs an ingredient agent followed by a product agent; these step-specific chains run in parallel. Available catalog ingredients inform ingredient selection. The product agent's catalog tool retrieves candidates within the step's category and ranks them by ingredient matches before the agent chooses products and explains its recommendations.

![Select and assemble: parallel step chains use catalog ingredients and ranked products; code checks product IDs, uses catalog facts, and assembles the routine in the planned order.](assets/images/select-and-assemble.png)

Code checks selected product IDs against that step's retrieved candidates and restores trusted catalog fields. After all steps finish, deterministic code assembles the routine in its planned order without another model call. Agent-written explanations remain generated text.

The illustrations use a fictional profile and three example steps. See the [architecture guide](docs/architecture.md) for the implemented request path, streaming contract, and current search limitations.

### Architecture

![Approved reference architecture showing the web application, authentication, streaming Lambda proxy, AgentCore agents, product catalog, and build pipeline.](assets/images/architecture.png)

[View the reference architecture at full resolution](assets/images/architecture.png).

The numbered steps below follow the approved reference architecture:

1. **Web application.** The user signs in and submits up to three skin photos. **Amazon CloudFront** serves the React application from a private **Amazon S3** bucket, with **AWS WAF** protecting the web and API paths.
2. **Authentication.** **Amazon Cognito** authenticates administrator-created users. **Amazon API Gateway** validates the Cognito ID token on each analysis request.
3. **Controlled runtime access.** API Gateway invokes a streaming **AWS Lambda** proxy. The proxy checks the authenticated identity, enforces per-user usage limits and active-analysis leases in **Amazon DynamoDB**, and invokes **Amazon Bedrock AgentCore Runtime** with IAM credentials.
4. **Analysis and planning.** AgentCore runs the agents in isolated sessions. A skin-analysis agent uses an **Amazon Bedrock** multimodal model to produce a structured profile. A planning agent chooses 2–8 routine steps from the available catalog categories.
5. **Product selection.** Each routine step runs an ingredient agent followed by a product agent. These chains run in parallel across steps and query the DynamoDB catalog. **Amazon Bedrock Guardrails** screen model calls.
6. **Build and monitoring.** **AWS CodeBuild** builds the agent image from source in S3 and pushes it to **Amazon ECR** for the runtime. **Amazon CloudWatch** supports API, WAF, build, and runtime observability.
7. **Assembly and streaming.** Code validates the selected products against retrieved catalog records and assembles the routine in its planned order. Progress and results stream back as SSE through Lambda, API Gateway, and CloudFront to the browser.

The [architecture guide](docs/architecture.md) explains the Lambda proxy, usage limits, streaming contract, and deployment boundaries in more detail.

### Cost

You are responsible for the cost of the AWS services used while running this Guidance. As of June 2026, the cost for running this Guidance with the default settings in the US East (N. Virginia) region is approximately **$74 per month** for processing 1,000 skincare analyses.

We recommend creating a [Budget](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html) through [AWS Cost Explorer](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/) to help manage costs. Prices are subject to change. For full details, refer to the pricing webpage for each AWS service used in this Guidance.

#### Assumptions

The cost estimate is based on deployment in **US East (N. Virginia) — `us-east-1`**. Pricing may vary by region. It assumes the following usage pattern:

- **1 selfie image** at typical smartphone resolution (~1920×1080), which is downscaled to 1,568 tokens by the API
- **5 routine steps** on average (the system generates 2–8 steps depending on the skin profile)
- **12 model invocations** per analysis: 1 Sonnet call (vision) + 1 Haiku call (step planning) + 5 Haiku calls (ingredients) + 5 Haiku calls (products)
- **~60 seconds** average end-to-end processing time per analysis, with ~70% spent in I/O wait (waiting for model responses)

#### Token Usage Per Analysis

| Agent | Model | Input Tokens | Output Tokens | Calls |
| --- | --- | --- | --- | --- |
| Skin Analysis | Claude Sonnet 4.6 | ~3,000 (1,568 image + 1,340 system prompt + 50 text) | ~500 | 1 |
| Step Analysis | Claude Haiku 4.5 | ~1,100 (520 system prompt + 580 skin profile) | ~600 | 1 |
| Ingredients (per step) | Claude Haiku 4.5 | ~1,600 (520 system prompt + 400 context + 680 tool result) | ~500 | 5 |
| Products (per step) | Claude Haiku 4.5 | ~1,700 (490 system prompt + 400 context + 810 tool result) | ~400 | 5 |
| **Total per analysis** | | **~20,600 input** | **~5,600 output** | **12** |

#### Sample Cost Table

The following table provides a sample cost breakdown for deploying this Guidance with the default parameters in the US East (N. Virginia) Region for one month, processing **1,000 skincare analyses**.

| AWS Service | Dimensions | Cost [USD] |
| --- | --- | --- |
| Amazon Bedrock — Claude Sonnet 4.6 | 1,000 calls × 3,000 input tokens = 3.0M input tokens @ $3/MTok; 1,000 × 500 output tokens = 0.5M output tokens @ $15/MTok | $16.50 |
| Amazon Bedrock — Claude Haiku 4.5 | 11,000 calls × ~1,550 avg input tokens = 17.1M input tokens @ $1/MTok; 11,000 × ~480 avg output tokens = 5.3M output tokens @ $5/MTok | $43.50 |
| Amazon Bedrock AgentCore Runtime | 1,000 sessions × 60s; CPU active ~30% of time (70% I/O wait): $0.0895/vCPU-hr × 1 vCPU × 5 hrs active; Memory: $0.00945/GB-hr × 2 GB × 16.7 hrs total | $0.76 |
| Amazon CloudFront | 10 GB data transfer + 50,000 HTTPS requests (within Always Free tier: 1 TB transfer + 10M requests/month) | $0.00 |
| AWS WAF | 2 Web ACLs ($10) + 2 custom rules ($2) + 1 managed rule group ($1) + 55,000 requests @ $0.60/million ($0.03) | $13.03 |
| Amazon API Gateway | 5,000 REST API calls @ $3.50/million | $0.02 |
| Amazon DynamoDB | On-demand mode; ~22,000 read request units @ $0.125/million + ~1,000 write request units @ $0.625/million; <1 GB storage (within 25 GB free tier) | $0.01 |
| Amazon S3 | <1 GB storage (frontend assets) @ $0.023/GB; 1,000 PUT + 5,000 GET requests | $0.03 |
| Amazon Cognito | Up to 10,000 monthly active users (within free tier) | $0.00 |
| Amazon ECR | <1 GB container image storage @ $0.10/GB | $0.10 |
| **Total estimated monthly cost** | | **~$73.92** |

> **Note:** This estimate is for `us-east-1` — pricing may differ in other supported regions. The primary cost driver is Amazon Bedrock model invocations (~80% of total cost). Costs scale linearly with the number of analyses. Infrastructure costs (WAF, API Gateway) remain relatively constant regardless of usage volume. Model pricing is based on published rates for Claude Sonnet 4.6 ($3/$15 per MTok input/output) and Claude Haiku 4.5 ($1/$5 per MTok input/output). AgentCore Runtime pricing is based on consumption-based billing ($0.0895/vCPU-hr, $0.00945/GB-hr). CloudFront data transfer and requests fall within the [Always Free tier](https://aws.amazon.com/cloudfront/pricing/) (1 TB transfer + 10M requests/month). For the most current rates, refer to the [Amazon Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/) and the [AgentCore pricing page](https://aws.amazon.com/bedrock/agentcore/pricing/).

## Prerequisites

### Operating System

These deployment instructions are optimized for **macOS** or **Amazon Linux 2023 / Ubuntu 22.04+**. Deployment on Windows requires WSL2 (Windows Subsystem for Linux).

### Third-party Tools

| Tool | Minimum Version | Purpose | Installation |
| --- | --- | --- | --- |
| Node.js | 24.x (LTS) | Frontend build toolchain | [nodejs.org](https://nodejs.org/) |
| Python | 3.11 | Agent runtime and utilities | [python.org](https://www.python.org/downloads/) |
| uv | Latest | Python package manager | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) |
| Terraform | 1.5 | Infrastructure provisioning | [hashicorp.com](https://developer.hashicorp.com/terraform/downloads) |
| AWS CLI | 2.x | AWS service interaction | [aws.amazon.com/cli](https://aws.amazon.com/cli/) |

### AWS Account Requirements

- An AWS account with permissions to create and manage: IAM roles/policies, Amazon Bedrock, Amazon Bedrock AgentCore, Amazon DynamoDB, Amazon S3, Amazon CloudFront, AWS WAF, Amazon Cognito, Amazon API Gateway, Amazon ECR, and AWS CodeBuild.
- Amazon Bedrock model access enabled for the following models in your deployment region:
    - **Anthropic Claude Sonnet 4.6** (cross-region inference profile: `global.anthropic.claude-sonnet-4-6`)
    - **Anthropic Claude Haiku 4.5** (cross-region inference profile: `global.anthropic.claude-haiku-4-5-20251001-v1:0`)

  Enable model access in the [Amazon Bedrock console — Model access](https://console.aws.amazon.com/bedrock/home#/modelaccess).

### Supported Regions

This Guidance uses Amazon Bedrock cross-region inference and must be deployed in one of the following regions:

| Region | Region Code |
| --- | --- |
| US East (N. Virginia) | `us-east-1` **(default)** |
| US West (Oregon) | `us-west-2` |

## Deployment Steps

### 1. Clone the repository

```bash
git clone https://github.com/aws-solutions-library-samples/guidance-for-smart-beauty-on-aws.git
cd guidance-for-smart-beauty-on-aws
```

### 2. Run initial setup

```bash
make setup
```

This command:
- Installs `uv` if not already present
- Creates a Python virtual environment (`.venv/`)
- Installs all Python dependencies from `requirements.txt`
- Installs frontend npm dependencies
- Creates the Terraform remote state S3 bucket and DynamoDB lock table
- Prints the `terraform init` command for the next step

### 3. Initialize Terraform

Run the command printed by `make setup`, substituting your AWS account ID:

```bash
cd terraform && terraform init \
  -backend-config="bucket=smart-beauty-tfstate-<YOUR_ACCOUNT_ID>" \
  -backend-config="key=dev/terraform.tfstate" \
  -backend-config="region=us-east-1" \
  -backend-config="dynamodb_table=smart-beauty-tfstate-lock" \
  -backend-config="encrypt=true"
cd ..
```

Each environment (`dev`, `staging`, `prod`) uses its own isolated state file, allowing multiple stacks to coexist in the same account.

### 4. Configure AWS credentials

```bash
export AWS_PROFILE=your-profile
# or set credentials directly:
export AWS_ACCESS_KEY_ID=<your-access-key>
export AWS_SECRET_ACCESS_KEY=<your-secret-key>
export AWS_REGION=us-east-1

# Verify access
aws sts get-caller-identity
```

### 5. Deploy the full stack

```bash
make deploy
```

Or target a specific environment:

```bash
make deploy ENV=staging
```

The deployment will:
1. Validate all prerequisites (Node.js, Terraform, AWS CLI, uv, active credentials)
2. Provision infrastructure via Terraform (DynamoDB, API Gateway, CloudFront, WAF, Cognito, AgentCore)
3. Build and push the AgentCore container image via AWS CodeBuild
4. Migrate the product catalog to DynamoDB (idempotent — safe to re-run)
5. Build the React frontend and deploy to S3 with CloudFront cache invalidation

### 6. Create a user

```bash
make create-user EMAIL=user@example.com
```

The user will receive a temporary password and must set a new password on first login.

## Deployment Validation

After deployment completes, validate with the following steps:

1. **Verify Terraform outputs:**
    ```bash
    cd terraform && terraform output
    ```
    Confirm the following outputs are present: `cloudfront_url`, `api_gateway_url`, `cognito_user_pool_id`.

2. **Verify the CloudFront distribution is active:**
    ```bash
    aws cloudfront list-distributions \
      --query "DistributionList.Items[?Comment=='smart-beauty'].{Id:Id,Status:Status,Domain:DomainName}" \
      --output table
    ```
    The status should show `Deployed`.

3. **Verify the AgentCore Runtime endpoint:**
    ```bash
    cd terraform && terraform output -raw agentcore_endpoint_url
    ```

4. **Access the application:** Open the CloudFront URL in a browser — you should see the login page.

## Running the Guidance

1. Open the CloudFront URL (from `terraform output cloudfront_url`) in a modern browser (Chrome, Firefox, Safari, or Edge).
2. Sign in with the Cognito user created during deployment. On first login, you will be prompted to set a permanent password.
3. Click **Start Analysis** to begin the skincare analysis flow.
4. Grant camera access when prompted and position your face within the on-screen guide overlay.
5. The camera captures your photo automatically (with countdown timer and flash effect).
6. Observe real-time streaming progress as the AI agents process your skin:
    - **Skin Analysis** — Identifies skin type (oily, dry, combination, sensitive, normal) and specific concerns
    - **Step Planning** — Chooses 2–8 routine steps based on the analysis and available categories
    - **Ingredient Selection** — Selects ingredients available in the catalog for each step
    - **Product Matching** — Recommends up to 3 products per step from the retrieved catalog candidates
7. Review your personalized skincare routine with product recommendations, ingredient details, and rationale.

### Expected Output

A complete analysis produces:
- A structured multi-step skincare routine (morning and/or evening)
- Up to 3 product recommendations per step with ingredient match scores

## Next Steps

- **Integrate your own product catalog** — Replace `data/products.csv` with your product data and update `data/catalog.yaml` to configure categories, schema mapping, and currency.
- **Tune AI models** — Update `config.py` to select different Amazon Bedrock models (e.g., Amazon Nova Pro for cost optimization or Claude Opus for enhanced analysis depth).
- **Add a custom domain** — Attach a custom domain with an ACM certificate by configuring `terraform/env-dev.tfvars`.
- **Deploy multiple environments** — Use the `ENV` parameter (`dev`, `staging`, `prod`) to run isolated parallel environments with separate Terraform state.
- **Customize content guardrails** — Adjust Amazon Bedrock Guardrails in `terraform/bedrock_guardrails.tf` to modify content filtering policies, PII redaction rules, and topic restrictions.

## Cleanup

Remove all deployed AWS resources:

```bash
make destroy
```

This command will:
- Empty the S3 frontend assets bucket
- Destroy all Terraform-managed infrastructure (CloudFront, WAF, API Gateway, Cognito, DynamoDB, ECR, AgentCore, IAM roles)

**Manual cleanup required:** The Terraform remote state resources are not destroyed automatically. Remove them manually if no longer needed:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws s3 rb s3://smart-beauty-tfstate-${ACCOUNT_ID} --force
aws dynamodb delete-table --table-name smart-beauty-tfstate-lock --region us-east-1
```

## FAQ, Known Issues, Additional Considerations, and Limitations

**Q: Deployment fails at the CodeBuild step.**
A: Verify that your AWS account has CodeBuild service permissions and that the ECR repository was created. Check the CodeBuild project logs in the CloudWatch console for detailed error output.

**Q: I receive "model access not available" errors at runtime.**
A: Enable both Claude Sonnet 4.6 and Claude Haiku 4.5 in the [Amazon Bedrock Model Access console](https://console.aws.amazon.com/bedrock/home#/modelaccess) for your deployment region. Model access approval can take a few minutes.

**Q: The browser camera does not activate.**
A: Camera access requires a secure context (HTTPS). CloudFront serves over HTTPS by default. If testing locally, use `localhost` (not a bare IP address).

**Q: The Terraform state bucket already exists.**
A: The `make setup` command is idempotent — if the state bucket and lock table already exist, it will skip creation and proceed.

**Known limitations:**

- Photos are processed in-memory only and are never persisted to storage. Re-analysis requires capturing a new photo.
- The included product catalog contains 48 synthetic products with fictional brand names for demonstration purposes. Replace with real product data for production use.
- Amazon Bedrock cross-region inference requires deployment in `us-east-1` or `us-west-2`.
- Self-registration is disabled by design. Users must be created by an administrator via `make create-user` or the Cognito console.

**Additional considerations:**

- This Guidance creates an Amazon CloudFront distribution that serves content over the public internet.
- Amazon Bedrock model invocations are the primary cost driver — costs scale linearly with the number of analyses performed.
- The AgentCore container image is built via CodeBuild on each deployment. Subsequent deployments only rebuild if source code has changed.

For feedback, questions, or suggestions, please use the [Issues](https://github.com/aws-solutions-library-samples/guidance-for-smart-beauty-on-aws/issues) tab in this repository.

## Revisions

| Date | Description |
| --- | --- |
| June 2026 | Initial release |

## Notices

*Customers are responsible for making their own independent assessment of the information in this Guidance. This Guidance: (a) is for informational purposes only, (b) represents AWS current product offerings and practices, which are subject to change without notice, and (c) does not create any commitments or assurances from AWS and its affiliates, suppliers or licensors. AWS products or services are provided "as is" without warranties, representations, or conditions of any kind, whether express or implied. AWS responsibilities and liabilities to its customers are controlled by AWS agreements, and this Guidance is not part of, nor does it modify, any agreement between AWS and its customers.*

## Authors

- **Rania Khemiri** — Prototyping Architect
- **Sophie Manuella Siake Tchouamou** — Delivery Consultant
