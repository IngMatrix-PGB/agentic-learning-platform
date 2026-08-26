output "alb_dns_name" {
  value = aws_lb.this.dns_name
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "ecs_service_name" {
  value = aws_ecs_service.this.name
}

output "ecr_repository_url" {
  value = aws_ecr_repository.this.repository_url
}

# Real resource ARN - consumed at the environments/dev root to build the
# execution role's ECR-pull policy without any name-convention guessing
# (see modules/iam/main.tf's header comment).
output "ecr_repository_arn" {
  value = aws_ecr_repository.this.arn
}

output "log_group_arn" {
  value = aws_cloudwatch_log_group.this.arn
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.this.name
}
