#!/bin/bash
# Smart Beauty — Tear down one deployment environment
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV="${1:-dev}"

if [[ ! "$ENV" =~ ^(dev|test|staging|prod)$ ]]; then
  echo "Usage: ./destroy.sh [dev|test|staging|prod]"
  exit 1
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo "╔════════════════════════════════════════╗"
echo "║   Smart Beauty — Destroy ($ENV)       ║"
echo "╚════════════════════════════════════════╝"
echo ""

print_success() { echo -e "${GREEN}✅ $1${NC}"; }
print_error()   { echo -e "${RED}❌ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }

print_warning "This will DELETE all Smart Beauty ($ENV) resources:"
echo "   • AgentCore Runtime + Endpoint"
echo "   • API Gateway, CloudFront"
echo "   • Canonical, metadata, outbox and usage-limit tables (all data)"
echo "   • Private OpenSearch domain, indices and search networking"
echo "   • Catalog publication and maintenance functions"
echo "   • S3 buckets, ECR repository"
echo "   • CodeBuild project"
echo "   • WAF, IAM roles, CloudWatch logs"
echo ""
print_warning "This action CANNOT be undone!"
echo ""

read -p "Type 'yes' to confirm: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  print_error "Cancelled"
  exit 0
fi

echo ""
echo "🏗️  Destroying Terraform infrastructure..."

cd "$PROJECT_ROOT/terraform"

AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null || true)}}"
AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION AWS_DEFAULT_REGION="$AWS_REGION"

terraform init -input=false -reconfigure \
  -backend-config="bucket=smart-beauty-tfstate-${AWS_ACCOUNT}" \
  -backend-config="key=${ENV}/terraform.tfstate" \
  -backend-config="region=us-east-1" \
  -backend-config="dynamodb_table=smart-beauty-tfstate-lock" \
  -backend-config="encrypt=true"

TFVARS_FILE="env-${ENV}.tfvars"
TFVARS_ARGS=()
if [ -f "$TFVARS_FILE" ]; then
  TFVARS_ARGS+=("-var-file=$TFVARS_FILE")
fi
if [ -f terraform.tfvars ]; then
  TFVARS_ARGS+=("-var-file=terraform.tfvars")
fi
TFVARS_ARGS+=("-var=environment=$ENV" "-var=aws_region=$AWS_REGION")

terraform destroy -auto-approve -input=false "${TFVARS_ARGS[@]}"

cd "$PROJECT_ROOT"

print_success "$ENV infrastructure destroyed"

echo ""
echo "╔════════════════════════════════════════╗"
echo "║     Cleanup Complete                   ║"
echo "╚════════════════════════════════════════╝"
echo ""
print_success "Environment resources removed; shared resources and Terraform state remain."
echo ""
