output "alb_dns_name" {
  value = module.ecs.alb_dns_name
}

output "s3_bucket_name" {
  value = module.storage.bucket_name
}

output "rds_endpoint" {
  value = module.database.db_endpoint
}

output "ecr_repository_url" {
  value = module.ecs.ecr_repository_url
}

# Identifier only - never the secret value (see modules/database/outputs.tf).
output "master_user_secret_arn" {
  value = module.database.master_user_secret_arn
}

output "bedrock_embedding_resource_arns_granted" {
  description = "UNVERIFIED unless bedrock_embedding_resource_arns was explicitly overridden - see infra/README.md."
  value       = module.iam.bedrock_embedding_resource_arns
}

output "bedrock_chat_resource_arns_granted" {
  description = "UNVERIFIED unless bedrock_chat_resource_arns was explicitly overridden - see infra/README.md."
  value       = module.iam.bedrock_chat_resource_arns
}
