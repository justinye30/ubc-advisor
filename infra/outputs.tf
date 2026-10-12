output "region" {
  value = var.region
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "cluster" {
  value = aws_ecs_cluster.main.name
}

output "service" {
  value = aws_ecs_service.app.name
}

output "db_identifier" {
  value = aws_db_instance.main.identifier
}

output "db_secret_id" {
  value = aws_secretsmanager_secret.db.id
}

output "api_keys_secret_id" {
  value = aws_secretsmanager_secret.api_keys.id
}

output "log_group" {
  value = aws_cloudwatch_log_group.app.name
}

output "app_url" {
  value = "https://${var.domain_name}"
}

output "user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

# The two DNS records to add where justinye.xyz's DNS is hosted.
output "dns_records" {
  value = concat(
    [for o in aws_acm_certificate.app.domain_validation_options : {
      purpose = "certificate validation (keep it: ACM renews with it)"
      type    = o.resource_record_type
      name    = o.resource_record_name
      value   = o.resource_record_value
    }],
    [{
      purpose = "the app"
      type    = "CNAME"
      name    = "${var.domain_name}."
      value   = aws_lb.main.dns_name
    }],
  )
}
