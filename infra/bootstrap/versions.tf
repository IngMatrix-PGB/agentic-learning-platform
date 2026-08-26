terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.24.0, < 7.0.0"
    }
  }

  # Deliberately no backend block: this module creates the S3 bucket that
  # environments/dev's remote state will live in, so it cannot use that same
  # bucket as its own backend without a chicken-and-egg problem. State for
  # this module stays local (a single `terraform.tfstate` file, not
  # committed - see .gitignore). See infra/README.md's bootstrap section.
}
