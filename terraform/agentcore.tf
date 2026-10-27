# -----------------------------------------------------------
# AgentCore Runtime — source archive, CodeBuild image, runtime
# -----------------------------------------------------------

locals {
  # One file list drives both packaging and rebuild detection.
  agent_source_files = sort(concat(
    [for f in fileset("${path.module}/..", "agents/**/*.py") : f],
    [for f in fileset("${path.module}/..", "prompts/**/*.txt") : f],
    [
      ".dockerignore",
      "Dockerfile.agentcore",
      "agentcore_entrypoint.py",
      "catalog.py",
      "config.py",
      "data/catalog.yaml",
      "pyproject.toml",
      "uv.lock",
    ],
  ))

  agent_build_files = concat(local.agent_source_files, [
    "terraform/buildspec.yml",
    "terraform/scripts/package-agent-code.sh",
    "terraform/scripts/build-image.sh",
  ])

  agent_source_hash = sha1(jsonencode({
    for f in local.agent_build_files : f => filesha1("${path.module}/../${f}")
  }))
}

# Stage + zip agent code for S3 upload
resource "null_resource" "package_agent_code" {
  triggers = {
    source_hash = local.agent_source_hash
  }

  provisioner "local-exec" {
    command = "bash \"${path.module}/scripts/package-agent-code.sh\" ${join(" ", [for f in local.agent_source_files : "'${f}'"])}"
  }
}

# S3 bucket for agent source code
resource "aws_s3_bucket" "agentcore_source" {
  bucket_prefix = "${local.prefix}-agentcore-src-"
  force_destroy = var.enable_force_destroy
}

resource "aws_s3_bucket_public_access_block" "agentcore_source" {
  bucket = aws_s3_bucket.agentcore_source.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "agentcore_source" {
  bucket = aws_s3_bucket.agentcore_source.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Upload source zip (re-uploads when source hash changes)
resource "aws_s3_object" "agentcore_source" {
  bucket = aws_s3_bucket.agentcore_source.id
  key    = "agent-code-${local.agent_source_hash}.zip"
  source = "${path.module}/.build/agent-code.zip"

  depends_on = [null_resource.package_agent_code]
}

# -----------------------------------------------------------
# CodeBuild — builds ARM64 Docker image and pushes to ECR
# -----------------------------------------------------------

resource "aws_codebuild_project" "agentcore_image" {
  name          = "${local.prefix}-agentcore-build"
  description   = "Build AgentCore Docker image for ${local.prefix}"
  service_role  = aws_iam_role.codebuild.arn
  build_timeout = 60

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type = "BUILD_GENERAL1_LARGE"
    image        = "aws/codebuild/amazonlinux2-aarch64-standard:3.0"
    type         = "ARM_CONTAINER"
    # Privileged mode required: CodeBuild builds Docker images (docker-in-docker)
    privileged_mode             = true
    image_pull_credentials_type = "CODEBUILD"

    environment_variable {
      name  = "AWS_DEFAULT_REGION"
      value = local.region
    }

    environment_variable {
      name  = "AWS_ACCOUNT_ID"
      value = local.account_id
    }

    environment_variable {
      name  = "IMAGE_REPO_NAME"
      value = aws_ecr_repository.agentcore.name
    }

    environment_variable {
      name  = "IMAGE_TAG"
      value = local.agent_source_hash
    }
  }

  source {
    type      = "S3"
    location  = "${aws_s3_bucket.agentcore_source.id}/${aws_s3_object.agentcore_source.key}"
    buildspec = file("${path.module}/buildspec.yml")
  }

  logs_config {
    cloudwatch_logs {
      group_name = "/aws/codebuild/${local.prefix}-agentcore-build"
    }
  }
}

# Trigger CodeBuild when source changes
resource "null_resource" "trigger_agentcore_build" {
  triggers = {
    source_hash    = local.agent_source_hash
    ecr_repository = aws_ecr_repository.agentcore.id
  }

  provisioner "local-exec" {
    command = "bash ${path.module}/scripts/build-image.sh \"${aws_codebuild_project.agentcore_image.name}\" \"${local.region}\" \"${aws_ecr_repository.agentcore.name}\" \"${local.agent_source_hash}\" \"${aws_ecr_repository.agentcore.repository_url}\""
  }

  depends_on = [
    aws_codebuild_project.agentcore_image,
    aws_ecr_repository.agentcore,
    aws_iam_role_policy.codebuild,
    aws_s3_object.agentcore_source,
  ]
}

# -----------------------------------------------------------
# AgentCore Runtime
# -----------------------------------------------------------

resource "aws_bedrockagentcore_agent_runtime" "main" {
  # A distinct name replaces legacy bearer-token runtimes during migration.
  agent_runtime_name = replace("${local.prefix}_agent_iam", "-", "_")
  description        = "Smart Beauty skincare analysis agent (${var.environment})"
  role_arn           = aws_iam_role.agentcore_execution.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.agentcore.repository_url}:${local.agent_source_hash}"
    }
  }

  # No JWT authorizer: service-to-service invocations require IAM/SigV4.
  # The runtime resource policy permits only the API proxy role.
  lifecycle {
    create_before_destroy = true
  }

  network_configuration {
    network_mode = "VPC"
    network_mode_config {
      security_groups = [aws_security_group.search_clients.id]
      subnets         = aws_subnet.search[*].id
    }
  }

  environment_variables = {
    METRICS_DEPLOYMENT          = local.prefix
    AWS_REGION                  = local.region
    AWS_DEFAULT_REGION          = local.region
    PRODUCTS_TABLE_NAME         = aws_dynamodb_table.canonical_products.name
    CATALOG_METADATA_TABLE_NAME = aws_dynamodb_table.catalog_metadata.name
    CATALOG_ID                  = local.search_config.catalog_id
    OPENSEARCH_ENDPOINT         = "https://${aws_opensearch_domain.products.endpoint}"
    AGENTCORE_RUNTIME           = "true"
    # Bedrock Guardrails configuration (applied in application code)
    GUARDRAIL_ID      = aws_bedrock_guardrail.smart_beauty.guardrail_id
    GUARDRAIL_VERSION = aws_bedrock_guardrail_version.smart_beauty.version
  }

  depends_on = [
    null_resource.trigger_agentcore_build,
    aws_iam_role_policy.agentcore_permissions,
    aws_vpc_endpoint.search_apis,
    aws_vpc_endpoint.search_s3,
    aws_vpc_endpoint.search_dynamodb,
  ]
}
