# Streaming API proxy: Cognito at the gateway, IAM from Lambda to AgentCore.
resource "aws_dynamodb_table" "analysis_limits" {
  name         = "${local.prefix}-AnalysisLimits"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
  server_side_encryption {
    enabled = true
  }
  point_in_time_recovery {
    enabled = true
  }
}

data "aws_iam_policy_document" "api_proxy_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api_proxy" {
  name               = "${local.prefix}-api-proxy"
  assume_role_policy = data.aws_iam_policy_document.api_proxy_assume.json
}

resource "aws_cloudwatch_log_group" "api_proxy" {
  name              = "/aws/lambda/${local.prefix}-api-proxy"
  retention_in_days = 30
}

data "aws_iam_policy_document" "api_proxy" {
  statement {
    sid     = "InvokeOnlyDefaultRuntime"
    actions = ["bedrock-agentcore:InvokeAgentRuntime"]
    resources = [
      aws_bedrockagentcore_agent_runtime.main.agent_runtime_arn,
      "${aws_bedrockagentcore_agent_runtime.main.agent_runtime_arn}/runtime-endpoint/DEFAULT",
    ]
  }
  statement {
    sid = "EnforceUserLimits"
    # DynamoDB transactions authorize each constituent item operation.
    actions = [
      "dynamodb:GetItem", "dynamodb:PutItem",
      "dynamodb:UpdateItem", "dynamodb:DeleteItem",
    ]
    resources = [aws_dynamodb_table.analysis_limits.arn]
  }
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.api_proxy.arn}:*"]
  }
}

resource "aws_iam_role_policy" "api_proxy" {
  role   = aws_iam_role.api_proxy.id
  policy = data.aws_iam_policy_document.api_proxy.json
}

data "aws_iam_policy_document" "runtime_proxy_only" {
  statement {
    sid       = "AllowProxy"
    actions   = ["bedrock-agentcore:InvokeAgentRuntime"]
    resources = [aws_bedrockagentcore_agent_runtime.main.agent_runtime_arn]
    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.api_proxy.arn]
    }
  }
  statement {
    sid       = "DenyInvocationOutsideProxy"
    effect    = "Deny"
    actions   = ["bedrock-agentcore:InvokeAgentRuntime*"]
    resources = [aws_bedrockagentcore_agent_runtime.main.agent_runtime_arn]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    condition {
      test     = "ArnNotEquals"
      variable = "aws:PrincipalArn"
      values   = [aws_iam_role.api_proxy.arn]
    }
  }
}

resource "aws_bedrockagentcore_resource_policy" "proxy_only" {
  resource_arn = aws_bedrockagentcore_agent_runtime.main.agent_runtime_arn
  policy       = data.aws_iam_policy_document.runtime_proxy_only.json
}

resource "aws_lambda_function" "api_proxy" {
  function_name                  = "${local.prefix}-api-proxy"
  role                           = aws_iam_role.api_proxy.arn
  runtime                        = "nodejs24.x"
  architectures                  = ["arm64"]
  handler                        = "index.handler"
  filename                       = "${path.module}/../api_proxy/.build/function.zip"
  source_code_hash               = filebase64sha256("${path.module}/../api_proxy/.build/function.zip")
  timeout                        = 900
  memory_size                    = 256
  reserved_concurrent_executions = var.analysis_proxy_concurrency

  environment {
    variables = {
      API_ID                   = aws_api_gateway_rest_api.skincare.id
      COGNITO_ISSUER           = "https://cognito-idp.${local.region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
      COGNITO_CLIENT_ID        = aws_cognito_user_pool_client.frontend.id
      AGENT_RUNTIME_ARN        = aws_bedrockagentcore_agent_runtime.main.agent_runtime_arn
      LIMITS_TABLE_NAME        = aws_dynamodb_table.analysis_limits.name
      USER_REQUESTS_PER_WINDOW = tostring(var.analysis_requests_per_hour)
      USER_WINDOW_SECONDS      = "3600"
      # Covers the two graph deadlines plus initialization/transport overhead.
      USER_LEASE_SECONDS = "1200"
    }
  }

  depends_on = [aws_iam_role_policy.api_proxy, aws_bedrockagentcore_resource_policy.proxy_only]
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id   = "InvokeFromAnalysisAPI"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.api_proxy.function_name
  principal      = "apigateway.amazonaws.com"
  source_account = local.account_id
  source_arn     = "${aws_api_gateway_rest_api.skincare.execution_arn}/prod/POST/analyze"
}
