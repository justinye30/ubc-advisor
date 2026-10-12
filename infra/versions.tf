terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State stays on your machine (gitignored). It's a one-person, build-demo-
  # destroy stack; a shared S3 backend would be one more thing to tear down.
}

provider "aws" {
  region = var.region

  # Every resource gets these tags, so the billing console can show exactly
  # what this project costs, and anything left behind is easy to find.
  default_tags {
    tags = {
      Project   = var.name
      ManagedBy = "terraform"
    }
  }
}
