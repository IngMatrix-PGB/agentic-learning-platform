variable "name_prefix" {
  type = string
}

variable "private_subnet_ids" {
  description = "At least 2 subnets across 2 AZs - required by aws_db_subnet_group even for a single-AZ instance."
  type        = list(string)
}

variable "security_group_id" {
  type = string
}

variable "engine_version" {
  description = "PostgreSQL engine version. Must be a version that supports the `vector` (pgvector) extension - verify with `aws rds describe-db-engine-versions --engine postgres` against the target account/region at implementation time before apply, since AWS periodically retires old minor versions."
  type        = string
  default     = "16.4"
}

variable "instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "allocated_storage_gb" {
  type    = number
  default = 20
}

variable "db_name" {
  type    = string
  default = "agentic_learning"
}

variable "master_username" {
  description = "Master username. The password itself is never a Terraform variable - RDS generates and owns it via manage_master_user_password (Secrets Manager). See infra/README.md's PILOT COMPROMISE note: this same privileged credential is used for both startup migrations and normal runtime traffic today."
  type        = string
  default     = "agentic_learning_admin"
}

variable "backup_retention_days" {
  type    = number
  default = 7
}

variable "tags" {
  type    = map(string)
  default = {}
}
