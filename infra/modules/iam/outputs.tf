output "execution_role_arn" {
  value = aws_iam_role.execution.arn
}

# Needed at the environments/dev root to attach the ECR-pull/CloudWatch-Logs
# policy that references modules/ecs's real resource ARNs (see
# modules/iam/main.tf's header comment) - aws_iam_role_policy's `role`
# argument takes the role's name/id, not its ARN.
output "execution_role_name" {
  value = aws_iam_role.execution.name
}

output "task_role_arn" {
  value = aws_iam_role.task.arn
}

output "bedrock_embedding_resource_arns" {
  description = "The resource ARNs actually granted - surfaced so `terraform plan`/`apply` output makes the UNVERIFIED-vs-explicit-override state visible without reading .tf source."
  value       = local.embedding_resource_arns
}

output "bedrock_chat_resource_arns" {
  value = local.chat_resource_arns
}
