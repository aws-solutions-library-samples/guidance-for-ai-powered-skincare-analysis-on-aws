variable "aws_region" {
  description = "AWS region for deployment. Required services, model profiles and compatible Availability Zones must be available in this region."
  type        = string
  default     = "us-east-1"
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
    condition     = var.analysis_proxy_concurrency >= 1 && var.analysis_proxy_concurrency <= 3000 && floor(var.analysis_proxy_concurrency) == var.analysis_proxy_concurrency
    error_message = "analysis_proxy_concurrency must be an integer from 1 to 3000 and fit the account's applied Lambda quota."
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

variable "search_alarm_actions" {
  description = "SNS topic or other supported CloudWatch alarm action ARNs, owned by the operating team."
  type        = list(string)
  default     = []
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

variable "search_instance_type" {
  description = "OpenSearch data node type; two AZs. Qualify capacity before production use."
  type        = string
  default     = "r6g.large.search"
}

variable "search_volume_gib" {
  description = "Storage per OpenSearch data node in GiB."
  type        = number
  default     = 30
  validation {
    condition     = var.search_volume_gib >= 20 && floor(var.search_volume_gib) == var.search_volume_gib
    error_message = "search_volume_gib must be an integer of at least 20."
  }
}

variable "search_availability_zone_ids" {
  description = "Optional ordered pair of standard Availability Zone IDs for search and AgentCore. Defaults to the first two enabled zones, sorted by ID."
  type        = list(string)
  default     = null

  validation {
    condition = var.search_availability_zone_ids == null ? true : (
      length(var.search_availability_zone_ids) == 2 &&
      length(distinct(var.search_availability_zone_ids)) == 2 &&
      alltrue([for zone_id in var.search_availability_zone_ids : try(trimspace(zone_id) != "", false)])
    )
    error_message = "search_availability_zone_ids must be null or contain exactly two distinct, non-empty Availability Zone IDs."
  }
}

variable "route53_zone_id" {
  description = "Route53 hosted zone ID for the custom domain"
  type        = string
  default     = ""
}
