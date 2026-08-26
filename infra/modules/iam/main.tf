# Strict execution-role vs. task-role separation (approved PR-009 IAM
# design). Every policy below is hand-written to the exact actions/resources
# the application code actually calls - no AWS managed policies (which grant
# broader resource scopes than this app needs) and no bedrock:*/s3:*
# wildcards. The one unavoidable "*" (ecr:GetAuthorizationToken) is an AWS
# API constraint, not a design shortcut - see its comment below.
#
# NOTE: the execution role's ECR-pull and CloudWatch-Logs-write permissions
# are NOT granted here. They need the REAL aws_ecr_repository/
# aws_cloudwatch_log_group ARNs, which live in modules/ecs - and modules/ecs
# needs this module's role ARNs for its task definition. Attaching that one
# policy at the environments/dev root (which can safely depend on both
# already-evaluated child modules) avoids a module-to-module cycle without
# guessing/reconstructing an ARN - see environments/dev/main.tf and
# infra/README.md's "IAM/ECS coupling" section.

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# --- Execution role: ECR pull, CloudWatch Logs, task-definition secret resolution ---

resource "aws_iam_role" "execution" {
  name               = "${var.name_prefix}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json

  tags = merge(var.tags, { Name = "${var.name_prefix}-ecs-execution" })
}

data "aws_iam_policy_document" "execution" {
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # AWS API constraint: this action has no resource-level permissions.
  }

  statement {
    sid       = "ResolveDbSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.master_user_secret_arn]
  }

  # ecr:BatchGetImage/GetDownloadUrlForLayer and logs:CreateLogStream/
  # PutLogEvents are intentionally NOT here - see this file's header comment
  # and environments/dev/main.tf's aws_iam_role_policy.ecs_execution_ecr_logs.
}

resource "aws_iam_role_policy" "execution" {
  name   = "${var.name_prefix}-ecs-execution"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution.json
}

# --- Task role: the application's own AWS calls ---

resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json

  tags = merge(var.tags, { Name = "${var.name_prefix}-ecs-task" })
}

data "aws_iam_policy_document" "task" {
  statement {
    sid       = "BedrockEmbeddingInvoke"
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel"]
    resources = local.embedding_resource_arns
  }

  statement {
    sid    = "BedrockChatInvoke"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = local.chat_resource_arns
  }

  statement {
    sid     = "SourceDocumentWrite"
    effect  = "Allow"
    actions = ["s3:PutObject", "s3:DeleteObject"]
    # Matches S3DocumentStorageAdapter exactly - it never calls
    # GetObject/ListBucket, so neither is granted here.
    resources = ["${var.s3_bucket_arn}/org/*"]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "${var.name_prefix}-ecs-task"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}
