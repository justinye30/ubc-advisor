variable "name" {
  description = "Prefix for every resource name."
  type        = string
  default     = "ubc-advisor"
}

variable "region" {
  description = "AWS region. ca-central-1 is Montreal."
  type        = string
  default     = "ca-central-1"
}

variable "my_ip" {
  description = "Your public IP as a /32 (curl -s https://checkip.amazonaws.com). The only address allowed in."
  type        = string

  validation {
    condition     = can(cidrhost(var.my_ip, 0)) && endswith(var.my_ip, "/32")
    error_message = "Use a single address in CIDR form, like 203.0.113.7/32."
  }

  # 203.0.113.0/24 is reserved for documentation, so it can only be the
  # example file's placeholder. Step 19's first restore failed on exactly this.
  validation {
    condition     = !startswith(var.my_ip, "203.0.113.")
    error_message = "my_ip is still the example placeholder. Use: curl -s https://checkip.amazonaws.com"
  }
}

variable "domain_name" {
  description = "Where the app lives, e.g. advisor.justinye.xyz. You add two DNS records for it (make aws-dns)."
  type        = string
}

variable "session_hours" {
  description = "How long a login lasts before Cognito asks again."
  type        = number
  default     = 8
}

variable "image_tag" {
  description = "Which image in ECR to run. make deploy sets this to the git commit."
  type        = string
  default     = "none"
}

# my_ip is still used for the database restore. Since Step 20 the app is
# reached through the load balancer and a login, not by IP.

variable "db_public" {
  description = "Give the database a public endpoint (still limited to my_ip). On only while restoring the dump."
  type        = bool
  default     = false
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "task_cpu" {
  description = "Fargate CPU units (1024 = 1 vCPU)."
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "Fargate memory in MiB."
  type        = number
  default     = 1024
}

variable "models" {
  description = "Must match your local .env, so production runs the same pipeline (same pipeline_version hash) you evaluated."
  type = object({
    router   = string
    entity   = string
    composer = string
  })
  default = {
    router   = "claude-haiku-4-5-20251001"
    entity   = "claude-haiku-4-5-20251001"
    composer = "claude-haiku-4-5-20251001"
  }
}
