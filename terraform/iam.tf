# -----------------------------------------------------------
# AgentCore Execution Role
# -----------------------------------------------------------

data "aws_iam_policy_document" "agentcore_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:bedrock-agentcore:${local.region}:${local.account_id}:*"]
    }
  }
}

resource "aws_iam_role" "agentcore_execution" {
  name               = "${local.prefix}-agentcore-execution-role"
  assume_role_policy = data.aws_iam_policy_document.agentcore_assume.json
}

data "aws_iam_policy_document" "agentcore_permissions" {
  # ECR image access
  statement {
    sid       = "ECRTokenAccess"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "ECRImageAccess"
    effect = "Allow"
    actions = [
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchCheckLayerAvailability",
    ]
    resources = [aws_ecr_repository.agentcore.arn]
  }

  # Bedrock model invocation - scoped to specific models
  statement {
    sid    = "BedrockModelInvocation"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = [
      # Exact primary/fast model IDs; global inference resolves across regions.
      "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-5-5",
      "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-5-5",
      "arn:aws:bedrock:${local.region}:${local.account_id}:inference-profile/global.anthropic.claude-sonnet-5-5",
      "arn:aws:bedrock:${local.region}:${local.account_id}:inference-profile/global.anthropic.claude-haiku-5-5",
    ]
  }

  # Bedrock Guardrails access
  statement {
    sid    = "BedrockGuardrailsAccess"
    effect = "Allow"
    actions = [
      "bedrock:ApplyGuardrail",
    ]
    resources = [aws_bedrock_guardrail.smart_beauty.guardrail_arn]
  }

  # Runtime has no product scan/query or publication permissions.
  statement {
    sid    = "CanonicalProductReads"
    effect = "Allow"
    actions = [
      "dynamodb:BatchGetItem",
    ]
    resources = [
      aws_dynamodb_table.canonical_products.arn,
    ]
  }
  statement {
    sid       = "BoundedCatalogMetadataReads"
    actions   = ["dynamodb:BatchGetItem"]
    resources = [aws_dynamodb_table.catalog_metadata.arn]
    condition {
      test     = "ForAllValues:StringLike"
      variable = "dynamodb:LeadingKeys"
      values   = ["CONFIG", "READINESS#*", "INGREDIENT#*", "ALIAS#*", "SUMMARY#*"]
    }
  }
  statement {
    sid       = "ExactProductSearch"
    actions   = ["es:ESHttpGet", "es:ESHttpPost"]
    resources = ["${aws_opensearch_domain.products.arn}/products-*/_search"]
  }

  # CloudWatch Logs
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:DescribeLogStreams",
      "logs:CreateLogGroup",
      "logs:DescribeLogGroups",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*"]
  }

  # X-Ray tracing
  statement {
    sid    = "XRayTracing"
    effect = "Allow"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets",
    ]
    resources = ["*"]
  }

  # CloudWatch Metrics
  statement {
    sid       = "CloudWatchMetrics"
    effect    = "Allow"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["bedrock-agentcore"]
    }
  }

}

resource "aws_iam_role_policy" "agentcore_permissions" {
  name   = "${local.prefix}-agentcore-permissions"
  role   = aws_iam_role.agentcore_execution.id
  policy = data.aws_iam_policy_document.agentcore_permissions.json
}

# -----------------------------------------------------------
# CodeBuild Service Role
# -----------------------------------------------------------

data "aws_iam_policy_document" "codebuild_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:codebuild:${local.region}:${local.account_id}:project/${local.prefix}-agentcore-build"]
    }
  }
}

resource "aws_iam_role" "codebuild" {
  name               = "${local.prefix}-codebuild-role"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume.json
}

data "aws_iam_policy_document" "codebuild_permissions" {
  # CloudWatch Logs
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/codebuild/*"]
  }

  # ECR auth token (requires wildcard resource)
  statement {
    sid       = "ECRAuthToken"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  # ECR image push operations (scoped to repo)
  statement {
    sid    = "ECRImagePush"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
    ]
    resources = [aws_ecr_repository.agentcore.arn]
  }

  # S3 source access
  statement {
    sid    = "S3SourceAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
    ]
    resources = ["${aws_s3_bucket.agentcore_source.arn}/*"]
  }

  statement {
    sid    = "S3BucketAccess"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation",
    ]
    resources = [aws_s3_bucket.agentcore_source.arn]
  }
}

resource "aws_iam_role_policy" "codebuild" {
  name   = "${local.prefix}-codebuild-permissions"
  role   = aws_iam_role.codebuild.id
  policy = data.aws_iam_policy_document.codebuild_permissions.json
}
