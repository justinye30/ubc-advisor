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
