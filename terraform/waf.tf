# -----------------------------------------------------------
# WAF — CloudFront (rate limiting + AWS managed rules)
# -----------------------------------------------------------

resource "aws_wafv2_web_acl" "cloudfront" {
  name        = "${local.prefix}-cloudfront-waf"
  description = "Rate limiting and common protections for CloudFront"
  scope       = "CLOUDFRONT"
  provider    = aws.us_east_1

  default_action {
    allow {}
  }

  # Rate limit: 500 requests per 5 minutes per IP
  rule {
    name     = "rate-limit"
    priority = 1

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 500
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.prefix}-rate-limit"
      sampled_requests_enabled   = false
    }
  }

  # AWS Managed Common Rule Set
  rule {
    name     = "aws-managed-common"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"

        # Exclude SizeRestrictions_BODY — our /api/analyze endpoint
        # receives base64-encoded images that exceed the 8KB default limit
        rule_action_override {
          name = "SizeRestrictions_BODY"
          action_to_use {
            count {}
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.prefix}-common-rules"
      sampled_requests_enabled   = false
    }
  }

  # AWS Managed Known Bad Inputs (Log4j / SSRF protection)
  rule {
    name     = "aws-managed-known-bad-inputs"
    priority = 3

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.prefix}-known-bad-inputs"
      sampled_requests_enabled   = false
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.prefix}-cloudfront-waf"
    sampled_requests_enabled   = false
  }
}

# CloudFront-only access to API Gateway is enforced via the
# X-Origin-Verify custom origin header with a random secret value.
# The regional WAF below blocks any request that doesn't include
# the correct header, preventing direct API Gateway access.

resource "random_password" "origin_verify_secret" {
  length  = 32
  special = false
}

resource "aws_wafv2_web_acl" "api_gateway" {
  name        = "${local.prefix}-apigw-waf"
  description = "Restrict API Gateway access to CloudFront only"
  scope       = "REGIONAL"

  default_action {
    block {}
  }

  rule {
    name = "allow-cloudfront-only"
    # Allow terminates evaluation; managed blocking rules must run first.
    priority = 3

    action {
      allow {}
    }

    statement {
      byte_match_statement {
        search_string = random_password.origin_verify_secret.result
        field_to_match {
          single_header {
            name = "x-origin-verify"
          }
        }
        positional_constraint = "EXACTLY"
        text_transformation {
          priority = 0
          type     = "NONE"
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.prefix}-cloudfront-only"
      sampled_requests_enabled   = false
    }
  }

  # AWS Managed Known Bad Inputs (Log4j / SSRF protection)
  rule {
    name     = "aws-managed-known-bad-inputs"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.prefix}-apigw-known-bad-inputs"
      sampled_requests_enabled   = false
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.prefix}-apigw-waf"
    sampled_requests_enabled   = false
  }
}

resource "aws_wafv2_web_acl_association" "api_gateway" {
  resource_arn = aws_api_gateway_stage.prod.arn
  web_acl_arn  = aws_wafv2_web_acl.api_gateway.arn
}

# -----------------------------------------------------------
# WAF Logging — CloudFront ACL
# -----------------------------------------------------------

resource "aws_cloudwatch_log_group" "waf_cloudfront" {
  name              = "aws-waf-logs-${local.prefix}-cloudfront"
  retention_in_days = 30
  provider          = aws.us_east_1
}

resource "aws_wafv2_web_acl_logging_configuration" "cloudfront" {
  log_destination_configs = [aws_cloudwatch_log_group.waf_cloudfront.arn]
  resource_arn            = aws_wafv2_web_acl.cloudfront.arn
  provider                = aws.us_east_1

  # Log redaction does not cover request sampling, which is disabled above.
  redacted_fields {
    single_header {
      name = "authorization"
    }
  }
  redacted_fields {
    single_header {
      name = "cookie"
    }
  }
  redacted_fields {
    single_header {
      name = "x-origin-verify"
    }
  }
}

# -----------------------------------------------------------
# WAF Logging — API Gateway ACL
# -----------------------------------------------------------

resource "aws_cloudwatch_log_group" "waf_api_gateway" {
  name              = "aws-waf-logs-${local.prefix}-apigw"
  retention_in_days = 30
}

resource "aws_wafv2_web_acl_logging_configuration" "api_gateway" {
  log_destination_configs = [aws_cloudwatch_log_group.waf_api_gateway.arn]
  resource_arn            = aws_wafv2_web_acl.api_gateway.arn

  redacted_fields {
    single_header {
      name = "authorization"
    }
  }
  redacted_fields {
    single_header {
      name = "cookie"
    }
  }
  redacted_fields {
    single_header {
      name = "x-origin-verify"
    }
  }
}
