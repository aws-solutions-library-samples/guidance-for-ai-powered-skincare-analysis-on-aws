# Terraform 1.7+. All providers are mocked; every run is plan-only.
mock_provider "aws" {}
mock_provider "aws" {
  alias = "us_east_1"
}
mock_provider "null" {}
mock_provider "random" {}

override_data {
  target = data.aws_availability_zones.search
  values = {
    zone_ids = ["use1-az4", "use1-az2", "use1-az1"]
  }
}

run "preserve_default_subnet_placement" {
  command = plan
  plan_options {
    target = [aws_subnet.search]
  }
  assert {
    condition = (
      aws_subnet.search[0].availability_zone_id == "use1-az1" &&
      aws_subnet.search[1].availability_zone_id == "use1-az2" &&
      aws_subnet.search[0].cidr_block == "10.24.0.0/24" &&
      aws_subnet.search[1].cidr_block == "10.24.1.0/24"
    )
    error_message = "Discovery must preserve the default deployment's zones and subnet order."
  }
}

run "discover_frankfurt_zones" {
  command = plan
  variables {
    aws_region = "eu-central-1"
  }
  plan_options {
    target = [aws_subnet.search]
  }
  override_data {
    target = data.aws_availability_zones.search
    values = {
      zone_ids = ["euc1-az3", "euc1-az1", "euc1-az2"]
    }
  }
  assert {
    condition = (
      aws_subnet.search[0].availability_zone_id == "euc1-az1" &&
      aws_subnet.search[1].availability_zone_id == "euc1-az2"
    )
    error_message = "A region outside the former allowlist must use its own discovered zones."
  }
}

run "discover_mumbai_zones" {
  command = plan
  variables {
    aws_region = "ap-south-1"
  }
  plan_options {
    target = [aws_subnet.search]
  }
  override_data {
    target = data.aws_availability_zones.search
    values = {
      zone_ids = ["aps1-az2", "aps1-az3", "aps1-az1"]
    }
  }
  assert {
    condition = (
      aws_subnet.search[0].availability_zone_id == "aps1-az1" &&
      aws_subnet.search[1].availability_zone_id == "aps1-az2"
    )
    error_message = "Zone selection must not depend on response order or a region-specific mapping."
  }
}

run "preserve_explicit_zone_order" {
  command = plan
  variables {
    aws_region                   = "us-west-1"
    search_availability_zone_ids = ["usw1-az3", "usw1-az1"]
  }
  plan_options {
    target = [aws_subnet.search]
  }
  override_data {
    target = data.aws_availability_zones.search
    values = {
      zone_ids = ["usw1-az1", "usw1-az2", "usw1-az3"]
    }
  }
  assert {
    condition = (
      aws_subnet.search[0].availability_zone_id == "usw1-az3" &&
      aws_subnet.search[1].availability_zone_id == "usw1-az1"
    )
    error_message = "An explicit compatible pair must keep the caller's order to avoid moving existing subnets."
  }
}

run "reject_duplicate_zone_override" {
  command = plan
  variables {
    search_availability_zone_ids = ["use1-az1", "use1-az1"]
  }
  plan_options {
    target = [aws_subnet.search]
  }
  expect_failures = [var.search_availability_zone_ids]
}

run "reject_zone_from_another_region" {
  command = plan
  variables {
    search_availability_zone_ids = ["use1-az1", "euw1-az1"]
  }
  plan_options {
    target = [aws_subnet.search]
  }
  expect_failures = [aws_subnet.search]
}

run "report_insufficient_zones" {
  command = plan
  plan_options {
    target = [aws_subnet.search]
  }
  override_data {
    target = data.aws_availability_zones.search
    values = {
      zone_ids = ["use1-az1"]
    }
  }
  expect_failures = [aws_subnet.search]
}

run "report_empty_zone_discovery" {
  command = plan
  plan_options {
    target = [aws_subnet.search]
  }
  override_data {
    target = data.aws_availability_zones.search
    values = {
      zone_ids = []
    }
  }
  expect_failures = [aws_subnet.search]
}
