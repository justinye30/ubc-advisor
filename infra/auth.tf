# Cognito: the login in front of the app. The load balancer talks to it;
# the app never sees a password and has no login code of its own.

resource "aws_cognito_user_pool" "main" {
  name           = var.name
  user_pool_tier = "ESSENTIALS" # needed for managed login; free up to 10,000 monthly users

  # Nobody can sign up. The only account is the one you create (make aws-user).
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
    require_symbols                  = false
    temporary_password_validity_days = 3
  }

  # An authenticator app is required. Managed login walks you through
  # scanning the QR code the first time you sign in.
  mfa_configuration = "ON"
  software_token_mfa_configuration {
    enabled = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  deletion_protection = "INACTIVE" # destroy must be able to remove it
}

# Cognito domain prefixes are shared by every AWS customer in the region,
# so a short random suffix keeps the name unique.
resource "random_string" "auth_prefix" {
  length  = 6
  special = false
  upper   = false
}

resource "aws_cognito_user_pool_domain" "main" {
  domain                = "${var.name}-${random_string.auth_prefix.result}"
  user_pool_id          = aws_cognito_user_pool.main.id
  managed_login_version = 2
}

resource "aws_cognito_user_pool_client" "alb" {
  name         = "${var.name}-alb"
  user_pool_id = aws_cognito_user_pool.main.id

  # The load balancer is a confidential client: it keeps a secret and
  # exchanges the login code for tokens server-side.
  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email"]
  supported_identity_providers         = ["COGNITO"]

  # The load balancer's fixed callback path.
  callback_urls = ["https://${var.domain_name}/oauth2/idpresponse"]

  prevent_user_existence_errors = "ENABLED"
}

# Managed login needs a style assigned to the client; Cognito's defaults are fine.
resource "aws_cognito_managed_login_branding" "alb" {
  user_pool_id                = aws_cognito_user_pool.main.id
  client_id                   = aws_cognito_user_pool_client.alb.id
  use_cognito_provided_values = true
}
