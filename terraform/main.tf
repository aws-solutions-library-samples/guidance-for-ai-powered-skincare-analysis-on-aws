data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  region      = data.aws_region.current.id
  prefix      = "smart-beauty-${var.environment}"
  cors_origin = var.custom_domain != "" ? "https://${var.custom_domain}" : "https://${aws_cloudfront_distribution.main.domain_name}"
}

# -----------------------------------------------------------
# AWS Guidance deployment tracking via the solution ID
# -----------------------------------------------------------

resource "aws_cloudformation_stack" "solution_tracking" {
  name = "${local.prefix}-tracking-stack"

  template_body = jsonencode({
    AWSTemplateFormatVersion = "2010-09-09"
    Description              = "Guidance for AI-Powered Skincare Analysis on AWS (SO9734)"

    Resources = {
      EmptyResource = {
        Type = "AWS::CloudFormation::WaitConditionHandle"
      }
    }
  })
}
