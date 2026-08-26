locals {
  name_prefix = "${var.project}-${var.environment}"

  common_tags = merge(var.tags, {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

module "networking" {
  source = "../../modules/networking"

  name_prefix                = local.name_prefix
  vpc_cidr                   = var.vpc_cidr
  allowed_ingress_cidrs      = var.allowed_ingress_cidrs
  allow_unrestricted_ingress = var.allow_unrestricted_ingress
  tags                       = local.common_tags
}

module "storage" {
  source = "../../modules/storage"

  bucket_name = var.documents_bucket_name
  tags        = local.common_tags
}

module "database" {
  source = "../../modules/database"

  name_prefix          = local.name_prefix
  private_subnet_ids   = module.networking.private_subnet_ids
  security_group_id    = module.networking.rds_security_group_id
  engine_version       = var.db_engine_version
  instance_class       = var.db_instance_class
  allocated_storage_gb = var.db_allocated_storage_gb
  db_name              = var.db_name
  master_username      = var.db_master_username
  tags                 = local.common_tags
}

module "iam" {
  source = "../../modules/iam"

  name_prefix                     = local.name_prefix
  aws_region                      = var.aws_region
  master_user_secret_arn          = module.database.master_user_secret_arn
  s3_bucket_arn                   = module.storage.bucket_arn
  bedrock_embedding_model_id      = var.bedrock_embedding_model_id
  bedrock_chat_model_id           = var.bedrock_chat_model_id
  bedrock_embedding_resource_arns = var.bedrock_embedding_resource_arns
  bedrock_chat_resource_arns      = var.bedrock_chat_resource_arns
  tags                            = local.common_tags
}

locals {
  # PUBLIC/DERIVED CONFIG only - DB_PASSWORD is deliberately absent, injected
  # instead via container_secrets below. See docs in the application repo's
  # config.py / .env.example for what each of these maps to.
  container_environment = {
    APP_NAME                           = var.project
    APP_ENV                            = "production"
    LOG_LEVEL                          = "INFO"
    APP_HOST                           = "0.0.0.0"
    APP_PORT                           = "8000"
    RUNTIME_MODE                       = "aws"
    EMBEDDING_DIMENSION                = "1024" # Titan Embed Text V2 constraint - see config.validate_aws_configuration
    AWS_REGION                         = var.aws_region
    BEDROCK_EMBEDDING_MODEL_ID         = var.bedrock_embedding_model_id
    BEDROCK_CHAT_MODEL_ID              = var.bedrock_chat_model_id
    BEDROCK_MAX_OUTPUT_TOKENS          = tostring(var.bedrock_max_output_tokens)
    BEDROCK_GENERATION_TIMEOUT_SECONDS = tostring(var.bedrock_generation_timeout_seconds)
    BEDROCK_MAX_RETRIES                = tostring(var.bedrock_max_retries)
    S3_BUCKET                          = module.storage.bucket_name
    DB_HOST                            = module.database.db_endpoint
    DB_PORT                            = tostring(module.database.db_port)
    DB_NAME                            = module.database.db_name
    MAX_UPLOAD_SIZE_MB                 = tostring(var.max_upload_size_mb)
    CHUNK_MAX_CHARS                    = tostring(var.chunk_max_chars)
    RETRIEVAL_TOP_K                    = tostring(var.retrieval_top_k)
    RETRIEVAL_SCORE_THRESHOLD          = tostring(var.retrieval_score_threshold)
    MAX_QUESTION_LENGTH                = tostring(var.max_question_length)
    CORS_ALLOWED_ORIGINS               = var.cors_allowed_origins
  }

  # SENSITIVE CONFIG: resolved by the execution role at task-launch time from
  # the RDS-managed Secrets Manager secret - never a plaintext value here.
  # The ":username::" / ":password::" suffix selects a JSON key out of the
  # secret (RDS's manage_master_user_password stores {"username":...,
  # "password":...}) - this is the documented ECS `secrets` valueFrom syntax
  # for JSON-keyed secrets.
  container_secrets = {
    DB_USER     = "${module.database.master_user_secret_arn}:username::"
    DB_PASSWORD = "${module.database.master_user_secret_arn}:password::"
  }
}

module "ecs" {
  source = "../../modules/ecs"

  name_prefix           = local.name_prefix
  aws_region            = var.aws_region
  vpc_id                = module.networking.vpc_id
  public_subnet_ids     = module.networking.public_subnet_ids
  private_subnet_ids    = module.networking.private_subnet_ids
  alb_security_group_id = module.networking.alb_security_group_id
  ecs_security_group_id = module.networking.ecs_security_group_id
  execution_role_arn    = module.iam.execution_role_arn
  task_role_arn         = module.iam.task_role_arn
  task_cpu              = var.task_cpu
  task_memory           = var.task_memory
  image_tag             = var.image_tag
  container_environment = local.container_environment
  container_secrets     = local.container_secrets
  log_retention_days    = var.log_retention_days
  tags                  = local.common_tags
}

# Attached here, not inside modules/iam, specifically to avoid a
# module-to-module cycle: this policy needs modules/ecs's REAL
# aws_ecr_repository/aws_cloudwatch_log_group ARNs (not a name-convention
# guess), while modules/ecs's task definition needs modules/iam's role
# ARNs. The environments/dev root can safely depend on both already-
# evaluated child modules - neither module references the other directly,
# so there is no cycle. See modules/iam/main.tf's header comment and
# infra/README.md's "IAM/ECS coupling" section. Resource scoping here is
# identical to (in fact stricter-by-construction than) the original
# name-reconstructed version: least-privilege, no wildcards.
data "aws_iam_policy_document" "ecs_execution_ecr_logs" {
  statement {
    sid       = "EcrPull"
    effect    = "Allow"
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [module.ecs.ecr_repository_arn]
  }

  statement {
    sid       = "LogsWrite"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${module.ecs.log_group_arn}:*"]
  }
}

resource "aws_iam_role_policy" "ecs_execution_ecr_logs" {
  name   = "${local.name_prefix}-ecs-execution-ecr-logs"
  role   = module.iam.execution_role_name
  policy = data.aws_iam_policy_document.ecs_execution_ecr_logs.json
}
