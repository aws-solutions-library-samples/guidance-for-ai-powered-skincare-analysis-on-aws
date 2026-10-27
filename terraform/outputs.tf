output "aws_region" {
  description = "Region containing the deployed resources"
  value       = local.region
}

output "app_url" {
  description = "Access your app here"
  value       = var.custom_domain != "" ? "https://${var.custom_domain}" : "https://${aws_cloudfront_distribution.main.domain_name}"
}

output "api_url" {
  description = "API Gateway endpoint"
  value       = aws_api_gateway_stage.prod.invoke_url
}

output "products_table_name" {
  description = "DynamoDB Products Table (for data migration)"
  value       = aws_dynamodb_table.canonical_products.name
}

output "catalog_metadata_table_name" {
  value = aws_dynamodb_table.catalog_metadata.name
}

output "catalog_outbox_table_name" {
  value = aws_dynamodb_table.catalog_outbox.name
}

output "catalog_admin_function_name" {
  value = aws_lambda_function.catalog["admin"].function_name
}

output "catalog_maintenance_function_name" {
  value = aws_lambda_function.catalog["maintenance"].function_name
}

output "search_dashboard_name" {
  value = aws_cloudwatch_dashboard.search.dashboard_name
}

output "catalog_publisher_policy_arn" {
  description = "Attach to the trusted supplier feed identity; not attached to application roles"
  value       = aws_iam_policy.catalog_publisher.arn
}

output "agentcore_ecr_repo_uri" {
  description = "ECR repository URI for AgentCore image"
  value       = aws_ecr_repository.agentcore.repository_url
}

output "agentcore_ecr_repo_name" {
  description = "ECR repository name for AgentCore"
  value       = aws_ecr_repository.agentcore.name
}

output "agentcore_execution_role_arn" {
  description = "IAM role ARN for AgentCore Runtime"
  value       = aws_iam_role.agentcore_execution.arn
}

output "agentcore_runtime_arn" {
  description = "AgentCore Runtime ARN"
  value       = aws_bedrockagentcore_agent_runtime.main.agent_runtime_arn
}

output "agentcore_runtime_id" {
  description = "AgentCore Runtime ID"
  value       = aws_bedrockagentcore_agent_runtime.main.agent_runtime_id
}

output "agentcore_build_project_name" {
  description = "CodeBuild project name for AgentCore"
  value       = aws_codebuild_project.agentcore_image.name
}

output "frontend_bucket" {
  description = "S3 bucket for frontend deployment"
  value       = aws_s3_bucket.frontend.id
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID (for cache invalidation)"
  value       = aws_cloudfront_distribution.main.id
}

# -----------------------------------------------------------
# Cognito Outputs
# -----------------------------------------------------------

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID"
  value       = aws_cognito_user_pool.main.id
}

output "cognito_user_pool_client_id" {
  description = "Cognito User Pool Client ID (frontend)"
  value       = aws_cognito_user_pool_client.frontend.id
}

output "frontend_env_config" {
  description = "Environment variables for frontend .env file"
  value       = <<-EOT
    VITE_COGNITO_USER_POOL_ID=${aws_cognito_user_pool.main.id}
    VITE_COGNITO_CLIENT_ID=${aws_cognito_user_pool_client.frontend.id}
    VITE_API_URL=${var.custom_domain != "" ? "https://${var.custom_domain}/api" : "https://${aws_cloudfront_distribution.main.domain_name}/api"}
  EOT
}

output "deployment_account_id" {
  description = "Account containing this deployment (used to guard live validation)"
  value       = local.account_id
}

output "deployment_environment" {
  description = "Environment selected for this state"
  value       = var.environment
}

output "analysis_limits_table_name" {
  description = "Per-user admission controls table"
  value       = aws_dynamodb_table.analysis_limits.name
}

output "api_proxy_function_name" {
  description = "Streaming proxy function used by release validation"
  value       = aws_lambda_function.api_proxy.function_name
}

output "agent_source_hash" {
  description = "Hash used to identify the packaged agent source and image build"
  value       = local.agent_source_hash
}
