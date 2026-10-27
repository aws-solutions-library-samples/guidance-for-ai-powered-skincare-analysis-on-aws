# Smart Beauty — Build & Deploy
# Usage:
#   make setup       — Install local dependencies
#   make bootstrap   — Create AWS resources for Terraform state
#   make deploy      — Full deployment (infra + agent + frontend)
#   make destroy     — Tear down one deployment environment
#   make validate    — Check source code and Terraform configuration
#   make test        — Run local Python, frontend and proxy tests
#
# Environment:
#   ENV              — Target environment: dev (default), test, staging, prod
#   AWS_PROFILE      — AWS CLI profile to use (optional)
#   AWS_REGION       — Deployment region (defaults to the profile region or us-east-1)

ENV ?= dev
SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "make setup       Install local dependencies"
	@echo "make test        Run Python, frontend and proxy tests"
	@echo "make validate    Check source and Terraform configuration"
	@echo "make bootstrap   Create AWS resources for Terraform state"
	@echo "make deploy      Deploy the selected environment (ENV=dev by default)"
	@echo "make destroy     Remove the selected environment"

# ---------------------------------------------------------------------------
# Prerequisites check
# ---------------------------------------------------------------------------
.PHONY: check-prereqs
check-prereqs:
	@echo "Checking prerequisites..."
	@command -v docker >/dev/null 2>&1 || command -v finch >/dev/null 2>&1 || { echo "⚠️  Neither docker nor finch found (optional — only needed for local container testing)"; }
	@command -v node >/dev/null 2>&1 || { echo "❌ node not found"; exit 1; }
	@command -v npm >/dev/null 2>&1 || { echo "❌ npm not found"; exit 1; }
	@command -v terraform >/dev/null 2>&1 || { echo "❌ terraform not found"; exit 1; }
	@command -v aws >/dev/null 2>&1 || { echo "❌ aws cli not found"; exit 1; }
	@command -v python3 >/dev/null 2>&1 || { echo "❌ python3 not found"; exit 1; }
	@command -v uv >/dev/null 2>&1 || { echo "❌ uv not found; install it from https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
	@aws sts get-caller-identity >/dev/null 2>&1 || { echo "❌ AWS credentials not configured"; exit 1; }
	@echo "✅ All prerequisites met"

# ---------------------------------------------------------------------------
# Local setup
# ---------------------------------------------------------------------------
.PHONY: setup
setup:
	@uv sync --locked
	@echo "✅ Python dependencies installed"
	@cd frontend && npm ci
	@echo "✅ Frontend dependencies installed"
	@cd api_proxy && npm ci && npm run build
	@echo "✅ API proxy dependencies installed and packaged"
	@uv run --locked python scripts/build-catalog-worker.py
	@echo "✅ Catalog worker packaged"

# ---------------------------------------------------------------------------
# AWS state resources (one-time)
# ---------------------------------------------------------------------------
.PHONY: bootstrap
bootstrap: check-prereqs
	# Terraform state resources
	@set -e; ACCOUNT_ID=$$(aws sts get-caller-identity --query Account --output text); \
	BUCKET="smart-beauty-tfstate-$${ACCOUNT_ID}"; \
	TABLE="smart-beauty-tfstate-lock"; \
	if ! aws s3api head-bucket --bucket "$$BUCKET" --region us-east-1 2>/dev/null; then \
		aws s3api create-bucket --bucket "$$BUCKET" --region us-east-1; \
		echo "✅ Created S3 state bucket: $$BUCKET"; \
	else \
		echo "ℹ️  S3 state bucket already exists: $$BUCKET"; \
	fi; \
	if ! aws dynamodb describe-table --table-name "$$TABLE" --region us-east-1 >/dev/null 2>&1; then \
		aws dynamodb create-table \
			--table-name "$$TABLE" \
			--attribute-definitions AttributeName=LockID,AttributeType=S \
			--key-schema AttributeName=LockID,KeyType=HASH \
			--billing-mode PAY_PER_REQUEST \
			--region us-east-1 >/dev/null; \
		echo "✅ Created DynamoDB lock table: $$TABLE"; \
	else \
		echo "ℹ️  DynamoDB lock table already exists: $$TABLE"; \
	fi
	@echo "✅ Terraform state resources ready"

# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------
.PHONY: deploy
deploy: bootstrap
	@./scripts/deploy.sh "$(ENV)"

# ---------------------------------------------------------------------------
# Destroy
# ---------------------------------------------------------------------------
.PHONY: destroy
destroy:
	@./scripts/destroy.sh "$(ENV)"

# ---------------------------------------------------------------------------
# Validate (compile + configuration checks)
# ---------------------------------------------------------------------------
.PHONY: validate
validate:
	@uv run --locked python scripts/check_docs.py
	@echo "Validating Python..."
	@uv run --locked python -m compileall -q *.py agents scripts
	@echo "✅ Python compilation OK"
	@echo "Validating Terraform..."
	@terraform fmt -check -recursive terraform
	@cd terraform && terraform validate
	@cd terraform/shared && terraform validate
	@echo "✅ Terraform validation OK"
	@echo "Validating Frontend..."
	@cd frontend && npm run typecheck
	@echo "✅ Validation complete"

# ---------------------------------------------------------------------------
# Local tests (no deployed AWS resources required)
# ---------------------------------------------------------------------------
.PHONY: test
test:
	@uv run --locked pytest
	@cd frontend && npm test -- --run
	@cd api_proxy && npm test

# ---------------------------------------------------------------------------
# Migrate products (manual)
# ---------------------------------------------------------------------------
.PHONY: migrate-products
migrate-products:
	@if [ -z "$(SOURCE_JSONL)" ]; then echo "Usage: make migrate-products SOURCE_JSONL=/path/to/supplier.jsonl"; exit 1; fi
	@set -e; PRODUCTS_TABLE=$$(cd terraform && terraform output -raw products_table_name); \
	METADATA_TABLE=$$(cd terraform && terraform output -raw catalog_metadata_table_name); \
	OUTBOX_TABLE=$$(cd terraform && terraform output -raw catalog_outbox_table_name); \
	DEPLOYMENT_REGION=$$(cd terraform && terraform output -raw aws_region); \
	AWS_REGION="$$DEPLOYMENT_REGION" AWS_DEFAULT_REGION="$$DEPLOYMENT_REGION" \
	uv run --locked python scripts/migrate_products.py "$$PRODUCTS_TABLE" \
	--metadata-table "$$METADATA_TABLE" --outbox-table "$$OUTBOX_TABLE" \
	--source "$(SOURCE_JSONL)" --wait-ready

# ---------------------------------------------------------------------------
# Create Cognito user (manual)
# ---------------------------------------------------------------------------
.PHONY: create-user
create-user:
	@if [ -z "$(EMAIL)" ]; then echo "Usage: make create-user EMAIL=user@example.com"; exit 1; fi
	@set -e; POOL_ID=$$(cd terraform && terraform output -raw cognito_user_pool_id); \
	DEPLOYMENT_REGION=$$(cd terraform && terraform output -raw aws_region); \
	aws cognito-idp admin-create-user \
		--region "$$DEPLOYMENT_REGION" \
		--user-pool-id "$$POOL_ID" \
		--username "$(EMAIL)" \
		--user-attributes Name=email,Value="$(EMAIL)" \
		--desired-delivery-mediums EMAIL && \
	echo "✅ User created: $(EMAIL). Check the invitation email for credentials."
