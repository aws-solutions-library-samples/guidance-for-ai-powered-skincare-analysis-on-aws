# Private exact-ingredient search. Engine is pinned to a managed-service release.
# Size and throughput require workload-specific capacity testing.
data "aws_availability_zones" "search" {
  state = "available"

  # Exclude Local Zones and other opt-in zones.
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

locals {
  search_config      = jsondecode(file("${path.module}/../data/search-config.json"))
  search_domain_name = "${local.prefix}-search"
  catalog_roles      = toset(["worker", "maintenance", "admin"])
  # Stable IDs avoid account-specific AZ name ordering. Bound the slice so the
  # subnet precondition can report insufficient zones without an index error.
  search_zone_ids = var.search_availability_zone_ids != null ? var.search_availability_zone_ids : slice(
    sort(data.aws_availability_zones.search.zone_ids),
    0,
    min(2, length(data.aws_availability_zones.search.zone_ids)),
  )
}

resource "aws_vpc" "search" {
  cidr_block           = "10.24.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
}

resource "aws_subnet" "search" {
  count                   = 2
  vpc_id                  = aws_vpc.search.id
  cidr_block              = cidrsubnet(aws_vpc.search.cidr_block, 8, count.index)
  availability_zone_id    = try(local.search_zone_ids[count.index], null)
  map_public_ip_on_launch = false

  lifecycle {
    precondition {
      condition = length(local.search_zone_ids) == 2 && alltrue([
        for zone_id in local.search_zone_ids : try(contains(data.aws_availability_zones.search.zone_ids, zone_id), false)
      ])
      error_message = "The deployment requires two enabled standard Availability Zones in ${var.aws_region}. Set search_availability_zone_ids to a compatible pair."
    }
  }
}

resource "aws_route_table" "search" {
  vpc_id = aws_vpc.search.id
}

resource "aws_route_table_association" "search" {
  count          = 2
  subnet_id      = aws_subnet.search[count.index].id
  route_table_id = aws_route_table.search.id
}

resource "aws_security_group" "search_clients" {
  name_prefix = "${local.prefix}-search-clients-"
  description = "Agent runtime and catalog workers; private HTTPS dependencies only"
  vpc_id      = aws_vpc.search.id
}

resource "aws_security_group" "search_domain" {
  name_prefix = "${local.prefix}-search-domain-"
  description = "OpenSearch HTTPS from the application workloads"
  vpc_id      = aws_vpc.search.id
}

resource "aws_security_group" "search_endpoints" {
  name_prefix = "${local.prefix}-search-endpoints-"
  description = "Private AWS API endpoints for application workloads"
  vpc_id      = aws_vpc.search.id
}

resource "aws_security_group_rule" "search_ingress" {
  for_each                 = { domain = aws_security_group.search_domain.id, endpoints = aws_security_group.search_endpoints.id }
  type                     = "ingress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = each.value
  source_security_group_id = aws_security_group.search_clients.id
}

resource "aws_security_group_rule" "search_egress" {
  for_each                 = { domain = aws_security_group.search_domain.id, endpoints = aws_security_group.search_endpoints.id }
  type                     = "egress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = aws_security_group.search_clients.id
  source_security_group_id = each.value
}

resource "aws_vpc_endpoint" "search_apis" {
  for_each            = toset(["bedrock-runtime", "ecr.api", "ecr.dkr", "logs", "monitoring", "xray", "sts"])
  vpc_id              = aws_vpc.search.id
  service_name        = "com.amazonaws.${local.region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = aws_subnet.search[*].id
  security_group_ids  = [aws_security_group.search_endpoints.id]
}

resource "aws_vpc_endpoint" "search_dynamodb" {
  vpc_id            = aws_vpc.search.id
  service_name      = "com.amazonaws.${local.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.search.id]
}

resource "aws_vpc_endpoint" "search_s3" {
  vpc_id            = aws_vpc.search.id
  service_name      = "com.amazonaws.${local.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.search.id]
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow", Principal = "*", Action = ["s3:GetObject"]
      Resource = ["arn:aws:s3:::prod-${local.region}-starport-layer-bucket/*"]
    }]
  })
}

resource "aws_security_group_rule" "search_gateway_egress" {
  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  security_group_id = aws_security_group.search_clients.id
  prefix_list_ids   = [aws_vpc_endpoint.search_dynamodb.prefix_list_id, aws_vpc_endpoint.search_s3.prefix_list_id]
}

# Keep the former SkincareProducts table for migration/rollback; the runtime
# reads only this canonical v2 table, with no category GSI.
resource "aws_dynamodb_table" "canonical_products" {
  name         = "${local.prefix}-ProductsV2"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "product_id"
  attribute {
    name = "product_id"
    type = "S"
  }
  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
}

resource "aws_dynamodb_table" "catalog_metadata" {
  name         = "${local.prefix}-CatalogMetadata"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  attribute {
    name = "pk"
    type = "S"
  }
  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
}

resource "aws_dynamodb_table" "catalog_outbox" {
  name             = "${local.prefix}-CatalogOutbox"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "catalog_shard"
  range_key        = "sequence"
  stream_enabled   = true
  stream_view_type = "KEYS_ONLY"
  attribute {
    name = "catalog_shard"
    type = "S"
  }
  attribute {
    name = "sequence"
    type = "N"
  }
  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
  # Outbox and tombstones have no automatic expiry. Retention/pruning is an
  # explicit maintenance operation after all retained generations have caught up.
}

resource "aws_iam_role" "catalog" {
  for_each           = local.catalog_roles
  name               = "${local.prefix}-catalog-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.api_proxy_assume.json
}

resource "aws_opensearch_domain" "products" {
  domain_name    = local.search_domain_name
  engine_version = "OpenSearch_3.5"
  cluster_config {
    instance_type          = var.search_instance_type
    instance_count         = 2
    zone_awareness_enabled = true
    zone_awareness_config { availability_zone_count = 2 }
  }
  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = var.search_volume_gib
  }
  vpc_options {
    subnet_ids         = aws_subnet.search[*].id
    security_group_ids = [aws_security_group.search_domain.id]
  }
  encrypt_at_rest { enabled = true }
  node_to_node_encryption { enabled = true }
  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-PFS-2023-10"
  }
  advanced_security_options {
    enabled                        = true
    internal_user_database_enabled = false
    anonymous_auth_enabled         = false
    master_user_options { master_user_arn = aws_iam_role.catalog["admin"].arn }
  }
  access_policies = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow", Principal = { AWS = aws_iam_role.agentcore_execution.arn }
        Action   = ["es:ESHttpGet", "es:ESHttpPost"]
        Resource = "arn:aws:es:${local.region}:${local.account_id}:domain/${local.search_domain_name}/products-*/_search"
      },
      {
        Effect   = "Allow", Principal = { AWS = [for role in aws_iam_role.catalog : role.arn] }
        Action   = ["es:ESHttp*"]
        Resource = "arn:aws:es:${local.region}:${local.account_id}:domain/${local.search_domain_name}/*"
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "catalog" {
  for_each          = local.catalog_roles
  name              = "/aws/lambda/${local.prefix}-catalog-${each.key}"
  retention_in_days = 30
}

data "aws_iam_policy_document" "catalog" {
  for_each = local.catalog_roles
  statement {
    sid       = "PrivateSearchDataPlane"
    actions   = each.key == "worker" ? ["es:ESHttpGet", "es:ESHttpPost", "es:ESHttpPut"] : ["es:ESHttpGet", "es:ESHttpPost", "es:ESHttpPut", "es:ESHttpDelete"]
    resources = ["${aws_opensearch_domain.products.arn}/*"]
  }
  statement {
    sid       = "ControlPublication"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:ConditionCheckItem"]
    resources = [aws_dynamodb_table.catalog_metadata.arn]
  }
  dynamic "statement" {
    for_each = each.key == "maintenance" ? [1] : []
    content {
      sid       = "CanonicalBackfill"
      actions   = ["dynamodb:Scan", "dynamodb:GetItem"]
      resources = [aws_dynamodb_table.canonical_products.arn]
    }
  }
  dynamic "statement" {
    for_each = each.key != "admin" ? [1] : []
    content {
      sid       = "ReadDurableOutbox"
      actions   = ["dynamodb:Query"]
      resources = [aws_dynamodb_table.catalog_outbox.arn]
    }
  }
  dynamic "statement" {
    for_each = each.key == "worker" ? [1] : []
    content {
      sid       = "OutboxStreamWakeup"
      actions   = ["dynamodb:DescribeStream", "dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:ListStreams"]
      resources = [aws_dynamodb_table.catalog_outbox.stream_arn]
    }
  }
  statement {
    sid       = "OwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.catalog[each.key].arn}:*"]
  }
  statement {
    # Lambda's VPC execution role needs these ENI actions; describe/list APIs
    # and creation before an ENI exists require wildcard resources.
    sid       = "LambdaNetworkInterfaces"
    actions   = ["ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DescribeSubnets", "ec2:DeleteNetworkInterface", "ec2:AssignPrivateIpAddresses", "ec2:UnassignPrivateIpAddresses"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "catalog" {
  for_each = local.catalog_roles
  role     = aws_iam_role.catalog[each.key].id
  policy   = data.aws_iam_policy_document.catalog[each.key].json
}

resource "aws_lambda_function" "catalog" {
  for_each                       = local.catalog_roles
  function_name                  = "${local.prefix}-catalog-${each.key}"
  role                           = aws_iam_role.catalog[each.key].arn
  runtime                        = "python3.12"
  architectures                  = ["x86_64"]
  handler                        = "handler.${each.key}"
  filename                       = "${path.module}/../catalog_worker/.build/function.zip"
  source_code_hash               = filebase64sha256("${path.module}/../catalog_worker/.build/function.zip")
  timeout                        = each.key == "admin" ? 300 : 150
  memory_size                    = 512
  reserved_concurrent_executions = each.key == "worker" ? 16 : 1
  vpc_config {
    subnet_ids         = aws_subnet.search[*].id
    security_group_ids = [aws_security_group.search_clients.id]
  }
  environment {
    variables = {
      METRICS_DEPLOYMENT          = local.prefix
      CATALOG_ID                  = local.search_config.catalog_id
      PRODUCTS_TABLE_NAME         = aws_dynamodb_table.canonical_products.name
      CATALOG_METADATA_TABLE_NAME = aws_dynamodb_table.catalog_metadata.name
      CATALOG_OUTBOX_TABLE_NAME   = aws_dynamodb_table.catalog_outbox.name
      OPENSEARCH_ENDPOINT         = "https://${aws_opensearch_domain.products.endpoint}"
      SEARCH_RUNTIME_ROLE_ARN     = aws_iam_role.agentcore_execution.arn
      SEARCH_WRITER_ROLE_ARN      = aws_iam_role.catalog["worker"].arn
      SEARCH_MAINTENANCE_ROLE_ARN = aws_iam_role.catalog["maintenance"].arn
    }
  }
  depends_on = [aws_iam_role_policy.catalog, aws_vpc_endpoint.search_apis, aws_vpc_endpoint.search_dynamodb]
}

resource "aws_lambda_event_source_mapping" "catalog_outbox" {
  event_source_arn                   = aws_dynamodb_table.catalog_outbox.stream_arn
  function_name                      = aws_lambda_function.catalog["worker"].arn
  starting_position                  = "TRIM_HORIZON"
  batch_size                         = 100
  maximum_batching_window_in_seconds = 1
  maximum_retry_attempts             = 3
  # Failed notifications remain recoverable from the durable table. A scheduled
  # worker always resumes the last acknowledged source sequence.
}

resource "aws_cloudwatch_event_rule" "catalog_tick" {
  count               = 16
  name                = "${local.prefix}-catalog-shard-${count.index}"
  schedule_expression = "rate(1 minute)"
}

resource "aws_cloudwatch_event_target" "catalog_tick" {
  count     = 16
  rule      = aws_cloudwatch_event_rule.catalog_tick[count.index].name
  target_id = "shard-${count.index}"
  arn       = aws_lambda_function.catalog["worker"].arn
  input     = jsonencode({ shard = count.index })
}

resource "aws_lambda_permission" "catalog_tick" {
  count          = 16
  statement_id   = "CatalogShard${count.index}"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.catalog["worker"].function_name
  principal      = "events.amazonaws.com"
  source_arn     = aws_cloudwatch_event_rule.catalog_tick[count.index].arn
  source_account = local.account_id
}

resource "aws_cloudwatch_event_rule" "catalog_maintenance" {
  name                = "${local.prefix}-catalog-maintenance"
  schedule_expression = "rate(1 minute)"
}

resource "aws_cloudwatch_event_target" "catalog_maintenance" {
  rule = aws_cloudwatch_event_rule.catalog_maintenance.name
  arn  = aws_lambda_function.catalog["maintenance"].arn
}

resource "aws_lambda_permission" "catalog_maintenance" {
  statement_id   = "CatalogMaintenance"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.catalog["maintenance"].function_name
  principal      = "events.amazonaws.com"
  source_arn     = aws_cloudwatch_event_rule.catalog_maintenance.arn
  source_account = local.account_id
}

resource "aws_cloudwatch_metric_alarm" "catalog_worker_errors" {
  alarm_name          = "${local.prefix}-catalog-publication-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.catalog["worker"].function_name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.search_alarm_actions
}

# Attach explicitly to the trusted supplier publisher. Runtime, proxy and
# projection roles are never granted canonical product mutation permissions.
data "aws_iam_policy_document" "catalog_publisher" {
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem"]
    resources = [aws_dynamodb_table.canonical_products.arn]
  }
  statement {
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.catalog_outbox.arn]
    condition {
      test     = "ForAllValues:StringLike"
      variable = "dynamodb:LeadingKeys"
      values   = ["${local.search_config.catalog_id}#*"]
    }
  }
  statement {
    actions   = ["dynamodb:GetItem"]
    resources = [aws_dynamodb_table.catalog_metadata.arn]
    condition {
      test     = "ForAllValues:StringLike"
      variable = "dynamodb:LeadingKeys"
      values   = ["CONFIG", "SOURCE", "SOURCE#*", "PROJECTION", "PROJECTION#*", "READINESS#*", "DEMO_IMPORT"]
    }
  }
  statement {
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.catalog_metadata.arn]
    condition {
      test     = "ForAllValues:StringLike"
      variable = "dynamodb:LeadingKeys"
      values   = ["SOURCE", "SOURCE#*"]
    }
  }
  statement {
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.catalog_metadata.arn]
    condition {
      test     = "ForAllValues:StringLike"
      variable = "dynamodb:LeadingKeys"
      values   = ["DEMO_IMPORT"]
    }
  }
}

resource "aws_iam_policy" "catalog_publisher" {
  name        = "${local.prefix}-catalog-publisher"
  description = "Canonical and outbox transactions for the deployment's trusted supplier feed"
  policy      = data.aws_iam_policy_document.catalog_publisher.json
}
