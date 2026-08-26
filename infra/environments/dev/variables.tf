variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project" {
  type    = string
  default = "agentic-learning-platform"
}

variable "environment" {
  type    = string
  default = "dev"
}

# --- Ingress compensating control (required adjustment #1) ---
# No default: apply/plan fails until this is supplied explicitly. Never
# commit a real value here or in terraform.tfvars.example - see that file's
# placeholder and infra/README.md.
variable "allowed_ingress_cidrs" {
  description = "CIDR blocks permitted to reach the pilot ALB. NOT authentication - see modules/networking/variables.tf for the full warning. Required, no default."
  type        = list(string)
}

variable "allow_unrestricted_ingress" {
  type    = bool
  default = false
}

# --- Networking ---

variable "vpc_cidr" {
  type    = string
  default = "10.60.0.0/16"
}

# --- Database ---

variable "db_engine_version" {
  type    = string
  default = "16.4"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "db_allocated_storage_gb" {
  type    = number
  default = 20
}

variable "db_name" {
  type    = string
  default = "agentic_learning"
}

variable "db_master_username" {
  type    = string
  default = "agentic_learning_admin"
}

# --- Storage ---

variable "documents_bucket_name" {
  description = "Globally-unique S3 bucket name for source documents. No org-wide naming convention exists yet for this personal project's pilot resources - pick something unique (e.g. a random suffix) at apply time."
  type        = string
}

# --- ECS / application ---

variable "image_tag" {
  description = "Immutable deployment tag, always in the form \"sha-<git-sha>\" (e.g. sha-824976c). No default - there is no image to deploy at first apply (see infra/README.md). Terraform never rewrites your tag; it only rejects one that doesn't start with \"sha-\", so the ECR lifecycle policy's cleanup rule stays effective."
  type        = string

  validation {
    condition     = startswith(var.image_tag, "sha-")
    error_message = "image_tag must start with \"sha-\" (e.g. sha-824976c) - see infra/README.md's ECR tag/lifecycle contract."
  }
}

variable "task_cpu" {
  type    = number
  default = 1024
}

variable "task_memory" {
  type    = number
  default = 2048
}

# --- Bedrock (application config + IAM resource-ARN overrides) ---

variable "bedrock_embedding_model_id" {
  type    = string
  default = "amazon.titan-embed-text-v2:0"
}

variable "bedrock_chat_model_id" {
  type    = string
  default = "anthropic.claude-3-5-haiku-20241022-v1:0"
}

variable "bedrock_embedding_resource_arns" {
  description = "UNVERIFIED default if left empty - see modules/iam/variables.tf."
  type        = list(string)
  default     = []
}

variable "bedrock_chat_resource_arns" {
  description = "UNVERIFIED default if left empty - see modules/iam/variables.tf."
  type        = list(string)
  default     = []
}

variable "bedrock_max_output_tokens" {
  type    = number
  default = 1024
}

variable "bedrock_generation_timeout_seconds" {
  type    = number
  default = 30
}

variable "bedrock_max_retries" {
  type    = number
  default = 3
}

# --- Application config (mirrors .env.example; RUNTIME_MODE/EMBEDDING_DIMENSION
# are NOT variables - they are hardcoded to "aws"/1024 in main.tf since this
# environment only ever deploys AWS mode, and 1024 is the only dimension this
# module's Titan V2 default supports) ---

variable "max_upload_size_mb" {
  type    = number
  default = 20
}

variable "chunk_max_chars" {
  type    = number
  default = 1200
}

variable "retrieval_top_k" {
  type    = number
  default = 5
}

variable "retrieval_score_threshold" {
  type    = number
  default = 0.35
}

variable "max_question_length" {
  type    = number
  default = 2000
}

variable "cors_allowed_origins" {
  description = "The real ALB DNS name is only known after first apply (module.ecs.alb_dns_name) - referencing it here as a default would be circular (this value is an INPUT to the ecs module's task definition). Ships with the app's own local-mode default; update this and re-apply once the ALB DNS name (or a real domain, per PR-010) is known."
  type        = string
  default     = "http://localhost:8000"
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "tags" {
  type    = map(string)
  default = {}
}
