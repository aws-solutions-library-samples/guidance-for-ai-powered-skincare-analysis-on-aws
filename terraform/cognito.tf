# -----------------------------------------------------------
# Cognito User Pool — direct SPA sign-in with JWT authorization
# -----------------------------------------------------------

resource "aws_cognito_user_pool" "main" {
  name                = "${local.prefix}-users"
  deletion_protection = var.environment == "prod" ? "ACTIVE" : "INACTIVE"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  # Only admins can create users — no self-registration
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_numbers   = true
    require_symbols   = true
    require_uppercase = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true

    string_attribute_constraints {
      min_length = 0
      max_length = 2048
    }
  }
}

# App client — public SPA client (no secret).
resource "aws_cognito_user_pool_client" "frontend" {
  name         = "${local.prefix}-frontend"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret = false

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  allowed_oauth_flows_user_pool_client = false
  # Explicitly clear OAuth settings retained by existing clients.
  allowed_oauth_flows  = []
  allowed_oauth_scopes = []
  callback_urls        = []
  logout_urls          = []

  id_token_validity      = 1
  access_token_validity  = 1
  refresh_token_validity = 30

  token_validity_units {
    id_token      = "hours"
    access_token  = "hours"
    refresh_token = "days"
  }

  prevent_user_existence_errors = "ENABLED"
}
