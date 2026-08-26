output "db_endpoint" {
  description = "Host:port endpoint - the application's DB_HOST/DB_PORT."
  value       = aws_db_instance.this.address
}

output "db_port" {
  value = aws_db_instance.this.port
}

output "db_name" {
  value = aws_db_instance.this.db_name
}

output "master_username" {
  value = aws_db_instance.this.username
}

# Identifier only, never the secret value - the value is resolved by the
# ECS execution role at task-launch time via the `secrets` block in the
# task definition (see modules/ecs), not read by Terraform.
output "master_user_secret_arn" {
  value = aws_db_instance.this.master_user_secret[0].secret_arn
}
