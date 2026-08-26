# RDS PostgreSQL (single-AZ, private) + pgvector. Aurora, Multi-AZ, and read
# replicas are explicitly out of scope for this pilot (approved PR-009
# decision #5) - see infra/README.md.
#
# PILOT COMPROMISE (see infra/README.md and the application repo's
# migrations/runner.py): the application runs its own startup migrations
# (CREATE EXTENSION vector, DDL) using the SAME credential it uses for all
# runtime traffic. There is no separate migration-privileged vs.
# runtime-DML-privileged credential in PR-009 - that split is PR-010 debt.

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-db-subnet-group"
  subnet_ids = var.private_subnet_ids

  tags = merge(var.tags, { Name = "${var.name_prefix}-db-subnet-group" })
}

resource "aws_db_instance" "this" {
  identifier     = "${var.name_prefix}-db"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage = var.allocated_storage_gb
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.master_username
  # No `password` argument: RDS generates and manages the master password in
  # Secrets Manager (manage_master_user_password=true). It is never a
  # Terraform variable, never appears in a committed .tfvars file, and is
  # never read back into a Terraform output - only the secret's ARN
  # (an identifier, not the value) is exposed, in outputs.tf.
  manage_master_user_password = true

  multi_az               = false
  publicly_accessible    = false
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.security_group_id]

  backup_retention_period    = var.backup_retention_days
  copy_tags_to_snapshot      = true
  auto_minor_version_upgrade = true

  # Cheap, no new resource required (unlike Enhanced Monitoring/Performance
  # Insights, deferred to PR-010 - see infra/README.md): ships PostgreSQL's
  # own log output to the CloudWatch log group this Terraform already
  # creates access to.
  enabled_cloudwatch_logs_exports = ["postgresql"]

  # Pilot simplicity trade-off, not a security control: no deletion
  # protection and no final snapshot requirement, so `terraform destroy`
  # cleanly tears down the pilot without a manual snapshot step. Revisit
  # before this database ever holds data that matters.
  deletion_protection = false
  skip_final_snapshot = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-db" })
}
