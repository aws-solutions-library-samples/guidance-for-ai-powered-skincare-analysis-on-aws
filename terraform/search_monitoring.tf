# Metrics use only the bounded Deployment dimension. Request IDs, product IDs
# and generations remain log context and never create additional metric series.
locals {
  search_alarms = {
    publication_lag = { metric = "PublicationLag", threshold = 60, missing = "breaching" }
    unhealthy       = { metric = "UnhealthyGeneration", threshold = 1, missing = "breaching" }
    reconciliation  = { metric = "ReconciliationAge", threshold = 86400, missing = "breaching" }
    projection      = { metric = "ProjectionFailures", threshold = 1, missing = "notBreaching" }
    maintenance     = { metric = "MaintenanceFailures", threshold = 1, missing = "notBreaching" }
  }
}

resource "aws_cloudwatch_metric_alarm" "search" {
  for_each            = local.search_alarms
  alarm_name          = "${local.prefix}-${each.key}"
  namespace           = "SmartBeauty/ExactSearch"
  metric_name         = each.value.metric
  dimensions          = { Deployment = local.prefix }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = each.value.threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = each.value.missing
  alarm_actions       = var.search_alarm_actions
  ok_actions          = var.search_alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "catalog_function_errors" {
  for_each            = toset(["maintenance", "admin"])
  alarm_name          = "${local.prefix}-catalog-${each.key}-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.catalog[each.key].function_name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.search_alarm_actions
}

resource "aws_cloudwatch_dashboard" "search" {
  dashboard_name = "${local.prefix}-exact-search"
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title = "Routine admission and completion", region = local.region, period = 60, stat = "Sum"
          metrics = [for metric in ["RoutinesOffered", "RoutinesAdmitted", "RoutinesCompleted", "RoutinesFailed", "RoutinesCancelled", "RoutineAdmissionRejections"] :
            ["SmartBeauty/ExactSearch", metric, "Deployment", local.prefix]
          ]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title = "Step search latency and failures", region = local.region, period = 60
          metrics = [
            ["SmartBeauty/ExactSearch", "StepSearchLatency", "Deployment", local.prefix, { stat = "p95" }],
            ["SmartBeauty/ExactSearch", "StepSearchLatency", "Deployment", local.prefix, { stat = "p99" }],
            ["SmartBeauty/ExactSearch", "StepSearchFailures", "Deployment", local.prefix, { stat = "Sum", yAxis = "right" }],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title       = "Worst retained-generation publication lag", region = local.region, period = 60, stat = "Maximum"
          metrics     = [["SmartBeauty/ExactSearch", "PublicationLag", "Deployment", local.prefix]]
          annotations = { horizontal = [{ label = "Lag alarm", value = 60 }, { label = "Admission stops", value = 300 }] }
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title = "Bounded reads, no-match and retries", region = local.region, period = 60, stat = "Sum"
          metrics = [for metric in ["StepSearches", "StepNoMatch", "CandidatesRead", "CanonicalProductsRead", "DependencyRetries"] :
            ["SmartBeauty/ExactSearch", metric, "Deployment", local.prefix]
          ]
        }
      },
    ]
  })
}
