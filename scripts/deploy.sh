#!/bin/bash
# Smart Beauty — Full deployment (Terraform + Frontend)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV="${1:-dev}"

if [[ ! "$ENV" =~ ^(dev|test|staging|prod)$ ]]; then
  echo "Usage: ./deploy.sh [dev|test|staging|prod]"
  exit 1
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo "╔════════════════════════════════════════╗"
echo "║   Smart Beauty — Deploy ($ENV)        ║"
echo "║   Terraform + AgentCore Runtime        ║"
echo "╚════════════════════════════════════════╝"
echo ""

print_success() { echo -e "${GREEN}✅ $1${NC}"; }
print_error()   { echo -e "${RED}❌ $1${NC}"; }
print_info()    { echo -e "${BLUE}ℹ️  $1${NC}"; }
print_step()    { echo -e "\n${BLUE}━━━ $1 ━━━${NC}\n"; }

# ──────────────────────────────────────────────
# 1. Prerequisites
# ──────────────────────────────────────────────
print_step "1/6  Checking prerequisites"

MISSING=0
for cmd in node npm aws terraform uv; do
  if ! command -v "$cmd" &>/dev/null; then
    print_error "$cmd is not installed"
    MISSING=1
  else
    print_success "$cmd found"
  fi
done

[ $MISSING -eq 1 ] && { print_error "Missing dependencies — aborting"; exit 1; }

cd "$PROJECT_ROOT"
uv sync --locked

# ──────────────────────────────────────────────
# 2. AWS identity
# ──────────────────────────────────────────────
print_step "2/6  Verifying AWS credentials"

if ! aws sts get-caller-identity &>/dev/null; then
  print_error "AWS credentials not configured. Run: aws configure"
  exit 1
fi

AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null || true)}}"
AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION AWS_DEFAULT_REGION="$AWS_REGION"
print_success "Account: $AWS_ACCOUNT  Region: $AWS_REGION"

# Package the pinned streaming proxy before Terraform reads its archive hash.
cd "$PROJECT_ROOT/api_proxy"
npm ci --omit=dev
npm run build
cd "$PROJECT_ROOT"
uv run --locked python scripts/build-catalog-worker.py

# ──────────────────────────────────────────────
# 3. Terraform apply (infra + AgentCore + CodeBuild)
# ──────────────────────────────────────────────
print_step "3/6  Terraform — shared account-level resources"

cd "$PROJECT_ROOT/terraform/shared"

terraform init -input=false -reconfigure \
  -backend-config="bucket=smart-beauty-tfstate-${AWS_ACCOUNT}" \
  -backend-config="key=shared/terraform.tfstate" \
  -backend-config="region=us-east-1" \
  -backend-config="dynamodb_table=smart-beauty-tfstate-lock" \
  -backend-config="encrypt=true"

terraform apply -auto-approve -input=false -var="aws_region=$AWS_REGION"
print_success "Shared resources ready"

print_step "4/6  Terraform — provisioning environment infrastructure"

cd "$PROJECT_ROOT/terraform"

terraform init -input=false -reconfigure \
  -backend-config="bucket=smart-beauty-tfstate-${AWS_ACCOUNT}" \
  -backend-config="key=${ENV}/terraform.tfstate" \
  -backend-config="region=us-east-1" \
  -backend-config="dynamodb_table=smart-beauty-tfstate-lock" \
  -backend-config="encrypt=true"

# Single apply: infrastructure and the AgentCore image/runtime.
# Load committed environment settings and optional local terraform.tfvars.
TFVARS_FILE="env-${ENV}.tfvars"
TFVARS_ARGS=("-var=environment=$ENV" "-var=aws_region=$AWS_REGION")
if [ -f "$TFVARS_FILE" ]; then
  TFVARS_ARGS=("-var-file=$TFVARS_FILE" "${TFVARS_ARGS[@]}")
fi

if ! terraform apply -auto-approve -input=false "${TFVARS_ARGS[@]}"; then
  print_error "Terraform apply failed"
  print_info "Check the error above. Common causes:"
  print_info "  - CodeBuild image build failure (check: aws codebuild list-builds-for-project)"
  print_info "  - IAM permission issues"
  print_info "  - Resource limits exceeded"
  print_info "Review the plan in terraform/ with the same environment, region, and variable file."
  exit 1
fi

# Capture outputs
APP_URL=$(terraform output -raw app_url)
API_URL=$(terraform output -raw api_url)
FRONTEND_BUCKET=$(terraform output -raw frontend_bucket)
CF_DISTRIBUTION_ID=$(terraform output -raw cloudfront_distribution_id)
PRODUCTS_TABLE=$(terraform output -raw products_table_name)
CATALOG_METADATA_TABLE=$(terraform output -raw catalog_metadata_table_name)
CATALOG_OUTBOX_TABLE=$(terraform output -raw catalog_outbox_table_name)
CATALOG_ADMIN_FUNCTION=$(terraform output -raw catalog_admin_function_name)
AGENTCORE_RUNTIME_ARN=$(terraform output -raw agentcore_runtime_arn)
COGNITO_USER_POOL_ID=$(terraform output -raw cognito_user_pool_id)
COGNITO_CLIENT_ID=$(terraform output -raw cognito_user_pool_client_id)

print_success "Infrastructure provisioned"
print_success "AgentCore Runtime: $AGENTCORE_RUNTIME_ARN"

cd "$PROJECT_ROOT"

# ──────────────────────────────────────────────
# 4. Initialize exact search and publish the demo only into an empty v2 catalog.
# ──────────────────────────────────────────────
print_step "5/6  Initializing exact product search"
uv run --locked python scripts/migrate_products.py "$PRODUCTS_TABLE" \
  --metadata-table "$CATALOG_METADATA_TABLE" --outbox-table "$CATALOG_OUTBOX_TABLE" \
  --admin-function "$CATALOG_ADMIN_FUNCTION" --demo-if-empty --wait-ready
print_success "Canonical catalog and exact search are ready"

# ──────────────────────────────────────────────
# 5. Build & deploy frontend + CloudFront invalidation
# ──────────────────────────────────────────────
print_step "6/6  Building & deploying frontend"

cd "$PROJECT_ROOT/frontend"

npm ci

echo "VITE_API_URL=${APP_URL}/api" > .env
echo "VITE_COGNITO_USER_POOL_ID=${COGNITO_USER_POOL_ID}" >> .env
echo "VITE_COGNITO_CLIENT_ID=${COGNITO_CLIENT_ID}" >> .env
npm run build

aws s3 sync dist/ "s3://${FRONTEND_BUCKET}/" --delete --quiet
print_success "Frontend deployed to S3"

cd "$PROJECT_ROOT"

# CloudFront invalidation
aws cloudfront create-invalidation \
  --distribution-id "$CF_DISTRIBUTION_ID" \
  --paths "/*" \
  --query 'Invalidation.Id' \
  --output text

print_success "Cache invalidation started"

# ──────────────────────────────────────────────
# Done
# ──────────────────────────────────────────────
echo ""
echo "╔════════════════════════════════════════╗"
echo "║     🎉 Deployment Complete             ║"
echo "╚════════════════════════════════════════╝"
echo ""
echo -e "🌐 App:      ${GREEN}${APP_URL}${NC}"
echo -e "🔌 API:      ${GREEN}${API_URL}${NC}"
echo -e "🤖 Agent:    ${GREEN}${AGENTCORE_RUNTIME_ARN}${NC}"
echo ""
