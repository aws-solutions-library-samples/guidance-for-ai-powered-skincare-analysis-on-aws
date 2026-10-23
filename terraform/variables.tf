variable "aws_region" {
  description = "AWS region for deployment. This project supports us-east-1, us-west-2, and eu-west-1."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = contains(["us-east-1", "us-west-2", "eu-west-1"], var.aws_region)
    error_message = "This project supports deployments in us-east-1, us-west-2, and eu-west-1."
  }
}

variable "environment" {
  description = "Deployment environment (dev, test, staging, prod)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "test", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, test, staging, prod"
  }
}

variable "enable_force_destroy" {
  description = "Enable force_destroy on S3 buckets and ECR. Only set to true for dev/ephemeral environments."
  type        = bool
  default     = false
}

variable "analysis_requests_per_hour" {
  description = "Maximum accepted analyses per authenticated user per fixed UTC hour."
  type        = number
  default     = 5
  validation {
    condition     = var.analysis_requests_per_hour >= 1 && var.analysis_requests_per_hour <= 100 && floor(var.analysis_requests_per_hour) == var.analysis_requests_per_hour
    error_message = "analysis_requests_per_hour must be an integer from 1 to 100."
  }
}

variable "analysis_proxy_concurrency" {
  description = "Maximum simultaneous streaming proxy invocations for this deployment."
  type        = number
  default     = 10
  validation {
    condition     = var.analysis_proxy_concurrency >= 1 && var.analysis_proxy_concurrency <= 100 && floor(var.analysis_proxy_concurrency) == var.analysis_proxy_concurrency
    error_message = "analysis_proxy_concurrency must be an integer from 1 to 100."
  }
}

# -----------------------------------------------------------
# Custom Domain (Route53 + ACM)
# -----------------------------------------------------------

variable "custom_domain" {
  description = "Custom domain for CloudFront (e.g. beauty.example.com). Leave empty to use default CloudFront domain."
  type        = string
  default     = ""
}

variable "acm_certificate_arn" {
  description = "ACM certificate ARN for the custom domain (must be in us-east-1)"
  type        = string
  default     = ""
}

# -----------------------------------------------------------
# Product Catalog Schema
# -----------------------------------------------------------

variable "product_category_field" {
  description = "DynamoDB attribute name for product category (must match catalog.yaml schema.category_field)"
  type        = string
  default     = "product_type"
}

variable "route53_zone_id" {
  description = "Route53 hosted zone ID for the custom domain"
  type        = string
  default     = ""
}
