# One VPC, two public subnets in different availability zones (RDS requires
# two), an internet gateway, and no NAT gateway.
#
# Why no NAT: the app needs outbound internet (Anthropic, Voyage, ECR,
# Secrets Manager, CloudWatch). A NAT gateway is the usual way and costs
# ~$35/month on its own. A public IP on the task does the same job for
# ~$4/month, and the security group below means nothing can connect in
# except from your IP.

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = "10.40.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true # needed for the RDS endpoint name to resolve
  tags                 = { Name = var.name }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = var.name }
}

resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true
  tags                    = { Name = "${var.name}-public-${count.index}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.name}-public" }
}

resource "aws_route_table_association" "public" {
  count = 2

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# ------------------------------------------------------------ security groups

# The app: port 8000 from your IP only. Step 20 replaces this rule with
# "from the load balancer only".
resource "aws_security_group" "app" {
  name        = "${var.name}-app"
  description = "App tasks"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "app_from_me" {
  security_group_id = aws_security_group.app.id
  description       = "API and UI from my IP"
  cidr_ipv4         = var.my_ip
  ip_protocol       = "tcp"
  from_port         = 8000
  to_port           = 8000
}

resource "aws_vpc_security_group_egress_rule" "app_out" {
  security_group_id = aws_security_group.app.id
  description       = "Anthropic, Voyage, AWS APIs, and the database"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# The database: Postgres from the app, and from your IP while db_public is on.
resource "aws_security_group" "db" {
  name        = "${var.name}-db"
  description = "Postgres"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "db_from_app" {
  security_group_id            = aws_security_group.db.id
  description                  = "Postgres from app tasks"
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_ingress_rule" "db_from_me" {
  count = var.db_public ? 1 : 0

  security_group_id = aws_security_group.db.id
  description       = "Postgres from my IP, only while restoring"
  cidr_ipv4         = var.my_ip
  ip_protocol       = "tcp"
  from_port         = 5432
  to_port           = 5432
}
