data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  region      = data.aws_region.current.id
  prefix      = "smart-beauty-${var.environment}"
  cors_origin = var.custom_domain != "" ? "https://${var.custom_domain}" : "https://${aws_cloudfront_distribution.main.domain_name}"
}
