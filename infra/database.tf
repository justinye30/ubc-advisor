# Postgres 16 on RDS, with pgvector available as an extension. The data
# arrives as a pg_dump of your local database (make db-restore), so the
# ingestion pipeline never runs in the cloud.

resource "random_password" "db" {
  length  = 32
  special = false # it goes inside a URL; letters and digits need no escaping
}

resource "aws_db_subnet_group" "main" {
  name       = var.name
  subnet_ids = aws_subnet.public[*].id
}

resource "aws_db_instance" "main" {
  identifier     = var.name
  engine         = "postgres"
  engine_version = "16" # major only: RDS picks the current 16.x minor

  instance_class    = var.db_instance_class
  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = "advisor"
  username = "advisor"
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]

  # In public subnets but without a public endpoint, except while restoring.
  # Even then, the security group admits only your IP, and RDS for
  # Postgres 16 refuses unencrypted connections (rds.force_ssl defaults to 1).
  publicly_accessible = var.db_public
  apply_immediately   = true # so opening/closing for a restore happens now

  multi_az                     = false
  backup_retention_period      = 1
  auto_minor_version_upgrade   = true
  performance_insights_enabled = false

  # Built to be destroyed: no final snapshot, no deletion protection.
  skip_final_snapshot = true
  deletion_protection = false
}
