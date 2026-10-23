# -----------------------------------------------------------
# API Gateway REST API
# -----------------------------------------------------------

resource "aws_api_gateway_rest_api" "skincare" {
  name        = "${local.prefix}-SkincareRoutineApi"
  description = "Async AI-powered skincare routine generator"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}


# -----------------------------------------------------------
# Cognito Authorizer — validates ID tokens on API Gateway
# -----------------------------------------------------------

resource "aws_api_gateway_authorizer" "cognito" {
  name          = "${local.prefix}-cognito"
  rest_api_id   = aws_api_gateway_rest_api.skincare.id
  type          = "COGNITO_USER_POOLS"
  provider_arns = [aws_cognito_user_pool.main.arn]
  # Validate the ID token audience here; the runtime no longer receives JWTs.
  identity_validation_expression = "^${aws_cognito_user_pool_client.frontend.id}$"
}

# -----------------------------------------------------------
# POST /analyze
# -----------------------------------------------------------

resource "aws_api_gateway_resource" "analyze" {
  rest_api_id = aws_api_gateway_rest_api.skincare.id
  parent_id   = aws_api_gateway_rest_api.skincare.root_resource_id
  path_part   = "analyze"
}

resource "aws_api_gateway_request_validator" "body" {
  name                        = "validate-body"
  rest_api_id                 = aws_api_gateway_rest_api.skincare.id
  validate_request_body       = true
  validate_request_parameters = true
}

resource "aws_api_gateway_method" "analyze_post" {
  rest_api_id          = aws_api_gateway_rest_api.skincare.id
  resource_id          = aws_api_gateway_resource.analyze.id
  http_method          = "POST"
  authorization        = "COGNITO_USER_POOLS"
  authorizer_id        = aws_api_gateway_authorizer.cognito.id
  request_validator_id = aws_api_gateway_request_validator.body.id

  request_parameters = {
    "method.request.header.Authorization" = true
  }
}

resource "aws_api_gateway_integration" "analyze_post" {
  rest_api_id             = aws_api_gateway_rest_api.skincare.id
  resource_id             = aws_api_gateway_resource.analyze.id
  http_method             = aws_api_gateway_method.analyze_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.api_proxy.response_streaming_invoke_arn
  timeout_milliseconds    = 900000
  response_transfer_mode  = "STREAM"

  depends_on = [aws_lambda_permission.api_gateway, aws_bedrockagentcore_resource_policy.proxy_only]
}

# CORS OPTIONS for /analyze
resource "aws_api_gateway_method" "analyze_options" {
  rest_api_id   = aws_api_gateway_rest_api.skincare.id
  resource_id   = aws_api_gateway_resource.analyze.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "analyze_options" {
  rest_api_id = aws_api_gateway_rest_api.skincare.id
  resource_id = aws_api_gateway_resource.analyze.id
  http_method = aws_api_gateway_method.analyze_options.http_method
  type        = "MOCK"

  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

resource "aws_api_gateway_method_response" "analyze_options_200" {
  rest_api_id = aws_api_gateway_rest_api.skincare.id
  resource_id = aws_api_gateway_resource.analyze.id
  http_method = aws_api_gateway_method.analyze_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

resource "aws_api_gateway_integration_response" "analyze_options_200" {
  rest_api_id = aws_api_gateway_rest_api.skincare.id
  resource_id = aws_api_gateway_resource.analyze.id
  http_method = aws_api_gateway_method.analyze_options.http_method
  status_code = aws_api_gateway_method_response.analyze_options_200.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,Authorization'"
    "method.response.header.Access-Control-Allow-Methods" = "'POST,OPTIONS'"
    "method.response.header.Access-Control-Allow-Origin"  = "'${local.cors_origin}'"
  }

  depends_on = [aws_api_gateway_integration.analyze_options]
}

# -----------------------------------------------------------
# Deployment & Stage
# -----------------------------------------------------------

resource "aws_api_gateway_deployment" "main" {
  rest_api_id = aws_api_gateway_rest_api.skincare.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.analyze,
      aws_api_gateway_request_validator.body,
      aws_api_gateway_method.analyze_post,
      aws_api_gateway_integration.analyze_post,
      aws_api_gateway_authorizer.cognito,
      aws_api_gateway_method.analyze_options,
      aws_api_gateway_integration.analyze_options,
      aws_api_gateway_method_response.analyze_options_200,
      aws_api_gateway_integration_response.analyze_options_200,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_cloudwatch_log_group" "api_access_logs" {
  name              = "/aws/apigateway/${local.prefix}-api"
  retention_in_days = 365
  # AWS-managed encryption (simpler for demo, still encrypted at rest)
}

resource "aws_api_gateway_stage" "prod" {
  deployment_id = aws_api_gateway_deployment.main.id
  rest_api_id   = aws_api_gateway_rest_api.skincare.id
  stage_name    = "prod"

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access_logs.arn
    format          = "$context.identity.sourceIp $context.identity.caller $context.identity.user [$context.requestTime] \"$context.httpMethod $context.resourcePath $context.protocol\" $context.status $context.responseLength $context.requestId"
  }
}

# -----------------------------------------------------------
# Method Settings (throttling + CloudWatch metrics)
# -----------------------------------------------------------

resource "aws_api_gateway_method_settings" "all" {
  rest_api_id = aws_api_gateway_rest_api.skincare.id
  stage_name  = aws_api_gateway_stage.prod.stage_name
  method_path = "*/*"

  settings {
    metrics_enabled        = true
    logging_level          = "INFO"
    data_trace_enabled     = false
    throttling_burst_limit = 50
    throttling_rate_limit  = 100
  }
}

# CloudFront-only access is enforced via WAF header inspection (see waf.tf).
# API Gateway resource policies cannot inspect custom HTTP headers.
