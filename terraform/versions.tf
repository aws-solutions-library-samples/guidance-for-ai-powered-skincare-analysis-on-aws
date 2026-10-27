terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.69"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }

  # Remote state storage — configure via -backend-config during init:
  #
  #   1. Create a backend config file (e.g. backend.hcl):
  #        bucket         = "my-tfstate-bucket"
  #        key            = "terraform.tfstate"
  #        region         = "us-east-1"
  #        dynamodb_table = "my-tfstate-lock"
  #        encrypt        = true
  #
  #   2. Initialize with:
  #        terraform init -backend-config=backend.hcl
  #
  #   Or pass values inline:
  #        terraform init \
  #          -backend-config="bucket=my-tfstate-bucket" \
  #          -backend-config="key=terraform.tfstate" \
  #          -backend-config="region=us-east-1" \
  #          -backend-config="dynamodb_table=my-tfstate-lock" \
  #          -backend-config="encrypt=true"
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "smart-beauty"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# CloudFront WAF MUST be in us-east-1 regardless of var.aws_region.
# Both providers use the same credential chain (env vars, profile, instance role).
# If using AWS SSO with a named profile, ensure it has access to us-east-1.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = {
      Project     = "smart-beauty"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
