# AirWatch AWS base (D-018). The owner runs plan and apply (D-023); see README.md.
# Versions looked up 2026-11-18: Terraform 1.17.2, hashicorp/aws 6.73.0.

terraform {
  required_version = "~> 1.17.2"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.73.0"
    }
  }

  # State bucket created by the owner in T0c: private, versioned, all public access blocked.
  # S3-native locking (use_lockfile) needs no DynamoDB table.
  backend "s3" {
    bucket       = "pm25-forecast-tfstate-65bc08"
    key          = "pm25-forecast/base.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project    = "pm25-forecast"
      managed-by = "terraform"
      repo       = "siddharthps/pm25-forecast"
    }
  }
}

locals {
  private_bucket = "pm25-forecast-data-${var.name_suffix}"
  public_bucket  = "pm25-forecast-public-${var.name_suffix}"

  # ARNs built from names, not read from resources, so the plan (and the tests) can see them.
  private_arn = "arn:aws:s3:::${local.private_bucket}"
  public_arn  = "arn:aws:s3:::${local.public_bucket}"

  # Private prefixes (SPEC § Structure). records/ is the durable forecast record (T6).
  private_prefixes = ["raw/", "records/", "models/", "reports/"]
}
