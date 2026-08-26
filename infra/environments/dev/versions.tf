terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.24.0, < 7.0.0"
    }
  }

  # Native S3 state locking (use_lockfile) requires Terraform >= 1.10 - no
  # separate DynamoDB lock table. Terraform 1.15.5 is installed in this
  # implementation environment, well above that floor - see infra/README.md.
  #
  # bucket/key values below are placeholders: this backend block cannot be
  # applied until infra/bootstrap has been applied once (manually, outside
  # this PR - see infra/README.md's bootstrap section) and the real state
  # bucket name is substituted here.
  #
  # `region` here is intentionally a STATIC literal, not var.aws_region:
  # Terraform backend blocks cannot reference input variables/locals at all
  # (a hard Terraform limitation, not a choice made in this PR). If the
  # deployment region ever changes, this value and var.aws_region's default
  # must be updated together, by hand - nothing enforces that they stay in
  # sync. See infra/README.md.
  backend "s3" {
    bucket       = "REPLACE-WITH-BOOTSTRAP-STATE-BUCKET-NAME"
    key          = "pr-009/agentic-learning-platform/dev/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}
