resource "aws_cognito_user_pool" "main" {
  name = "${local.prefix}-users"

  # Enterprise setting: only administrators create accounts (no self sign-up).
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 3
  }

  mfa_configuration = "OPTIONAL"
  software_token_mfa_configuration {
    enabled = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  deletion_protection = var.force_destroy ? "INACTIVE" : "ACTIVE"
}

resource "aws_cognito_user_group" "groups" {
  for_each     = toset(local.cognito_groups)
  user_pool_id = aws_cognito_user_pool.main.id
  name         = each.value
  description  = each.value == "admin" ? "Full document access and sync control" : (each.value == "confidential" ? "May read documents classified confidential" : "Reads ${each.value} documents")
}

resource "aws_cognito_user_pool_domain" "main" {
  domain       = "${local.prefix}-${local.account_id}"
  user_pool_id = aws_cognito_user_pool.main.id
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "${local.prefix}-web"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret                      = false # browser app: authorization code + PKCE
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  explicit_auth_flows                  = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true

  callback_urls = ["${local.web_origin}/", "${var.local_dev_origin}/"]
  logout_urls   = ["${local.web_origin}/", "${var.local_dev_origin}/"]

  id_token_validity      = 60
  access_token_validity  = 60
  refresh_token_validity = 8
  token_validity_units {
    id_token      = "minutes"
    access_token  = "minutes"
    refresh_token = "hours"
  }
}
