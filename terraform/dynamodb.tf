# -----------------------------------------------------------
# DynamoDB Product Catalog
# -----------------------------------------------------------

resource "aws_dynamodb_table" "products" {
  name         = "${local.prefix}-SkincareProducts"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "product_id"

  attribute {
    name = "product_id"
    type = "S"
  }

  attribute {
    name = var.product_category_field
    type = "S"
  }

  global_secondary_index {
    name = "${var.product_category_field}-index"
    key_schema {
      attribute_name = var.product_category_field
      key_type       = "HASH"
    }
    projection_type = "ALL"
  }

  server_side_encryption {
    enabled = true
  }

  point_in_time_recovery {
    enabled = true
  }
}
