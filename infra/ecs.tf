resource "aws_ecs_cluster" "main" {
  name = var.name
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.name}"
  retention_in_days = 14
}

# ------------------------------------------------------------------ IAM
# Two roles, with different jobs:
#   execution role: what ECS needs to START the task (pull the image,
#                   read the secrets, ship logs). The app never holds it.
#   task role:      what the running app can do. Only ECS Exec (a shell
#                   into the container for debugging); the app calls no AWS APIs.

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_base" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "read-app-secrets"
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = [aws_secretsmanager_secret.db.arn, aws_secretsmanager_secret.api_keys.arn]
    }]
  })
}

resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "task_exec" {
  name = "ecs-exec"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ssmmessages:CreateControlChannel",
        "ssmmessages:CreateDataChannel",
        "ssmmessages:OpenControlChannel",
        "ssmmessages:OpenDataChannel",
      ]
      Resource = "*"
    }]
  })
}

# ------------------------------------------------------------------ task

locals {
  # Non-secret settings. Same names as .env, production values.
  environment = {
    WEB_WORKERS             = "2"
    WEB_THREADS             = "4"
    DB_POOL_MIN             = "1"
    DB_POOL_MAX             = "4" # = WEB_THREADS: one request holds at most one connection
    DB_STATEMENT_TIMEOUT_MS = "5000"
    LLM_TIMEOUT             = "15"
    LLM_MAX_RETRIES         = "1"
    EMBED_MODEL             = "voyage-4"
    EMBED_DIM               = "1024"
    EMBED_RPM               = "0"
    EMBED_TPM               = "0"
    EMBED_TIMEOUT           = "10"
    EMBED_MAX_RETRIES       = "1"
    ROUTER_MODEL            = var.models.router
    ENTITY_MODEL            = var.models.entity
    COMPOSER_MODEL          = var.models.composer
    LOG_LEVEL               = "INFO"
  }
}

resource "aws_ecs_task_definition" "app" {
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64" # what make aws-image builds
  }

  container_definitions = jsonencode([{
    name      = "app"
    image     = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
    essential = true

    portMappings = [{ containerPort = 8000, protocol = "tcp" }]

    environment = [for k, v in local.environment : { name = k, value = v }]

    # "<secret arn>:<json key>::" picks one key out of a JSON secret.
    secrets = [
      { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.db.arn },
      { name = "ANTHROPIC_API_KEY", valueFrom = "${aws_secretsmanager_secret.api_keys.arn}:ANTHROPIC_API_KEY::" },
      { name = "VOYAGE_API_KEY", valueFrom = "${aws_secretsmanager_secret.api_keys.arn}:VOYAGE_API_KEY::" },
    ]

    # Liveness only: /health does no I/O, so a database blip doesn't get
    # the container killed and restarted.
    healthCheck = {
      command     = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "app"
      }
    }
  }])
}

resource "aws_ecs_service" "app" {
  name            = var.name
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  launch_type     = "FARGATE"

  # Starts at 0: nothing runs until the database is loaded and the keys are
  # set. After that, make aws-start / aws-stop set the count, and Terraform
  # leaves it alone (ignore_changes below).
  desired_count = 0

  enable_execute_command = true

  # Tasks register with the load balancer's target group. The grace period
  # stops the load balancer's health checks from failing a task that is
  # still starting up.
  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "app"
    container_port   = 8000
  }
  health_check_grace_period_seconds = 60

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = true
  }

  # A deployment whose new task keeps failing rolls back by itself.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  lifecycle {
    ignore_changes = [desired_count]
  }

  # The target group must be attached to a listener before a service can use it.
  depends_on = [aws_lb_listener.https]
}
