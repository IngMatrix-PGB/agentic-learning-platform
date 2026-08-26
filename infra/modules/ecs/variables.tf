variable "name_prefix" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "alb_security_group_id" {
  type = string
}

variable "ecs_security_group_id" {
  type = string
}

variable "alb_listener_port" {
  type    = number
  default = 80
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "execution_role_arn" {
  type = string
}

variable "task_role_arn" {
  type = string
}

# --- ECS Fargate sizing (approved PR-009 decisions) ---

variable "task_cpu" {
  description = "Fargate task vCPU units (1024 = 1 vCPU). Starting point per the PR-009 discovery's ECS sizing reasoning - Docling's layout/table models are the dominant memory driver, not FastEmbed (irrelevant in AWS mode). Revise after observing one real /v1/documents upload in CloudWatch/Container Insights."
  type        = number
  default     = 1024
}

variable "task_memory" {
  description = "Fargate task memory in MiB (2048 = 2 GB)."
  type        = number
  default     = 2048
}

variable "desired_count" {
  description = "Locked at 1 for this pilot (approved PR-009 decision #4) - no autoscaling."
  type        = number
  default     = 1

  validation {
    condition     = var.desired_count == 1
    error_message = "desired_count is locked at 1 for this pilot per the approved PR-009 architecture. Raising it requires first resolving the startup-migration race (see deployment_minimum_healthy_percent/deployment_maximum_percent's documentation in main.tf and infra/README.md) - that is explicitly out of PR-009's scope."
  }
}

# --- Deployment serialization (required adjustment #2 from the PR-009 review) ---

variable "deployment_minimum_healthy_percent" {
  description = "0, together with deployment_maximum_percent=100, forces ECS to fully stop the old task before starting the new one at desired_count=1 - see infra/README.md's proof. Do not change without re-deriving that proof."
  type        = number
  default     = 0
}

variable "deployment_maximum_percent" {
  description = "100, together with deployment_minimum_healthy_percent=0, caps in-flight tasks at 1 during a deployment, making concurrent startup-migration execution impossible at desired_count=1. Do not change without re-deriving that proof."
  type        = number
  default     = 100
}

variable "enable_deployment_circuit_breaker" {
  type    = bool
  default = true
}

# Pilot value, not benchmarked: covers ECS container start + Docling/model
# import + the startup migration run before the ALB health check is allowed
# to fail the task. Tune from an observed real cold-start time once this is
# deployed - see infra/README.md.
variable "health_check_grace_period_seconds" {
  type    = number
  default = 120
}

# --- ECR ---

variable "ecr_image_tag_mutability" {
  type    = string
  default = "IMMUTABLE"
}

variable "ecr_untagged_expiry_days" {
  type    = number
  default = 7
}

variable "ecr_keep_last_n_tagged" {
  type    = number
  default = 10
}

# --- CloudWatch ---

variable "log_retention_days" {
  type    = number
  default = 14
}

# --- Image / environment ---

variable "image_tag" {
  description = "Immutable Git-SHA deployment tag, always in the form \"sha-<git-sha>\" - e.g. sha-824976c. No default - must be supplied explicitly at deploy time (there is no image to deploy yet at first apply; see infra/README.md's bootstrap sequencing note). Terraform never rewrites whatever tag you pass; it only rejects one that doesn't start with \"sha-\"."
  type        = string
  default     = "sha-unset-pending-first-image-push"

  validation {
    condition     = startswith(var.image_tag, "sha-")
    error_message = "image_tag must start with \"sha-\" (e.g. sha-824976c) - see infra/README.md's ECR tag/lifecycle contract. The ECR lifecycle policy's tagPrefixList=[\"sha-\"] only expires images matching this convention."
  }
}

variable "container_environment" {
  description = "Non-secret application environment variables (PUBLIC/DERIVED CONFIG per the PR-009 discovery's classification) - DB_PASSWORD is deliberately absent here, injected instead via container_secrets."
  type        = map(string)
}

variable "container_secrets" {
  description = "Map of container env var name -> Secrets Manager valueFrom ARN (e.g. \"<secret-arn>:username::\", \"<secret-arn>:password::\"). Resolved by the execution role at task launch, never placed in plain environment."
  type        = map(string)
}

variable "enable_https" {
  description = "Kept false for this pilot (approved Option A: HTTP ALB + restricted CIDR allowlist, TLS/domain/ACM explicitly deferred to PR-010). Exists as a first-class toggle so the TLS-deferred state is visible in the interface, not silently absent."
  type        = bool
  default     = false
}

variable "tags" {
  type    = map(string)
  default = {}
}
