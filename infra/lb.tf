# ------------------------------------------------------------------ certificate
# A free public certificate for your domain. ACM proves you control the
# domain by asking for one DNS record (make aws-dns prints it).

resource "aws_acm_certificate" "app" {
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# Waits until ACM sees the validation record. The HTTPS listener depends on
# this, so apply pauses here until your DNS record is in place.
resource "aws_acm_certificate_validation" "app" {
  certificate_arn = aws_acm_certificate.app.arn
}

# ------------------------------------------------------------------ load balancer

resource "aws_lb" "main" {
  name               = var.name
  load_balancer_type = "application"
  internal           = false
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb.id]

  # Longer than the default 60s: a worst-case answer takes ~120s (Step 17).
  # gunicorn's keepalive (125s) stays above this, so the load balancer never
  # reuses a connection the app has already closed.
  idle_timeout = 120

  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "app" {
  name        = var.name
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip" # Fargate tasks register by IP
  vpc_id      = aws_vpc.main.id

  deregistration_delay = 30

  health_check {
    path                = "/health" # liveness only: no database, no model
    matcher             = "200"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      protocol    = "HTTPS"
      port        = "443"
      status_code = "HTTP_301"
    }
  }
}

locals {
  cognito_auth = {
    user_pool_arn       = aws_cognito_user_pool.main.arn
    user_pool_client_id = aws_cognito_user_pool_client.alb.id
    user_pool_domain    = aws_cognito_user_pool_domain.main.domain
    scope               = "openid email"
    session_timeout     = var.session_hours * 3600
  }
}

# Pages: not logged in → redirect to the Cognito login, then back.
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.app.certificate_arn

  default_action {
    type  = "authenticate-cognito"
    order = 1
    authenticate_cognito {
      user_pool_arn              = local.cognito_auth.user_pool_arn
      user_pool_client_id        = local.cognito_auth.user_pool_client_id
      user_pool_domain           = local.cognito_auth.user_pool_domain
      scope                      = local.cognito_auth.scope
      session_timeout            = local.cognito_auth.session_timeout
      on_unauthenticated_request = "authenticate"
    }
  }

  default_action {
    type             = "forward"
    order            = 2
    target_group_arn = aws_lb_target_group.app.arn
  }
}

# API calls: not logged in → a plain 401, not a redirect. A fetch() that
# follows a redirect to the login page fails as an opaque network error; a
# 401 lets the UI say "your login expired, reload".
resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10

  condition {
    path_pattern {
      values = ["/api/*"]
    }
  }

  action {
    type  = "authenticate-cognito"
    order = 1
    authenticate_cognito {
      user_pool_arn              = local.cognito_auth.user_pool_arn
      user_pool_client_id        = local.cognito_auth.user_pool_client_id
      user_pool_domain           = local.cognito_auth.user_pool_domain
      scope                      = local.cognito_auth.scope
      session_timeout            = local.cognito_auth.session_timeout
      on_unauthenticated_request = "deny"
    }
  }

  action {
    type             = "forward"
    order            = 2
    target_group_arn = aws_lb_target_group.app.arn
  }
}
