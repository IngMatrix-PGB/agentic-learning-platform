variable "name_prefix" {
  description = "Prefix used for naming/tagging every resource this module creates."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the pilot VPC."
  type        = string
  default     = "10.60.0.0/16"
}

variable "az_count" {
  description = "Number of availability zones to spread public/private subnets across. RDS requires a DB subnet group covering at least 2 AZs even for a single-AZ instance."
  type        = number
  default     = 2
}

variable "allowed_ingress_cidrs" {
  description = <<-EOT
    CIDR blocks permitted to reach the pilot ALB. This is a NETWORK-LAYER
    COMPENSATING CONTROL ONLY - it is NOT authentication. The application
    still trusts X-Organization-Id/X-Course-Id/X-User-Id headers with zero
    verification (see PR-008/routes.authorization in the application repo).
    Real authentication is PR-010 scope. Do not set this to ["0.0.0.0/0"]
    without deliberately setting allow_unrestricted_ingress=true.
  EOT
  type        = list(string)
  default     = []

  # A HARD failure (validation), not a check block: check blocks only ever
  # emit a warning and never stop plan/apply, even on a failing assertion -
  # empirically proven during the PR-009 adversarial review (a standalone
  # reproduction showed both `plan` and `apply` exit 0 despite a failing
  # check). Cross-variable validation (referencing allow_unrestricted_ingress
  # here) requires Terraform >= 1.9; required_version is already >= 1.10.
  validation {
    condition = var.allow_unrestricted_ingress || (
      length(var.allowed_ingress_cidrs) > 0 &&
      !contains(var.allowed_ingress_cidrs, "0.0.0.0/0")
    )
    error_message = "allowed_ingress_cidrs must be non-empty and must not contain 0.0.0.0/0 unless allow_unrestricted_ingress=true is explicitly set. CIDR restriction is a compensating control while the application trusts unauthenticated headers - see docs/architecture.md and infra/README.md."
  }
}

variable "allow_unrestricted_ingress" {
  description = "Explicit override allowing allowed_ingress_cidrs to be empty or contain 0.0.0.0/0. Approved PR-009 scope keeps this false - it exists purely so an insecure config can never happen silently, not as a setting meant to be flipped during this pilot."
  type        = bool
  default     = false
}

variable "alb_listener_port" {
  description = "Port the ALB listens on. HTTP only for this pilot - TLS/ACM/domain acquisition is explicitly deferred to PR-010 (approved Option A)."
  type        = number
  default     = 80
}

variable "container_port" {
  description = "Port the ECS task's container listens on."
  type        = number
  default     = 8000
}

variable "db_port" {
  description = "Port PostgreSQL listens on."
  type        = number
  default     = 5432
}

variable "tags" {
  description = "Common tags applied to every resource in this module."
  type        = map(string)
  default     = {}
}
