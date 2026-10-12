# Two secrets, injected into the container as environment variables by ECS.
# Nothing secret goes into the image or the task definition itself.

# The full connection string, built from the RDS endpoint and the generated
# password. The password also sits in Terraform's local state file, which
# is gitignored; for a single-person stack that's the accepted trade-off.
resource "aws_secretsmanager_secret" "db" {
  name                    = "${var.name}/database-url"
  recovery_window_in_days = 0 # delete immediately on destroy, so a rebuild can reuse the name
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.db.id
  secret_string = format(
    "postgresql://%s:%s@%s:%d/%s?sslmode=require",
    aws_db_instance.main.username,
    random_password.db.result,
    aws_db_instance.main.address,
    aws_db_instance.main.port,
    aws_db_instance.main.db_name,
  )
}

# API keys: Terraform creates the empty secret; you put the values in with
# the AWS CLI (make aws-keys), so the keys never pass through Terraform or
# its state file.
resource "aws_secretsmanager_secret" "api_keys" {
  name                    = "${var.name}/api-keys"
  recovery_window_in_days = 0
}
