# PR-009 pilot: ECR repo, CloudWatch log group, ECS cluster/service/task
# definition, and an HTTP-only ALB (TLS/domain/ACM explicitly deferred to
# PR-010 - approved Option A). No autoscaling, no service discovery, no
# API Gateway - none are required by any code path (see infra/README.md).

resource "aws_ecr_repository" "this" {
  name                 = var.name_prefix
  image_tag_mutability = var.ecr_image_tag_mutability

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = merge(var.tags, { Name = var.name_prefix })
}

resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after ${var.ecr_untagged_expiry_days} days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = var.ecr_untagged_expiry_days
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only the last ${var.ecr_keep_last_n_tagged} tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["sha-"]
          countType     = "imageCountMoreThan"
          countNumber   = var.ecr_keep_last_n_tagged
        }
        action = { type = "expire" }
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.name_prefix}"
  retention_in_days = var.log_retention_days

  tags = merge(var.tags, { Name = "/ecs/${var.name_prefix}" })
}

resource "aws_ecs_cluster" "this" {
  name = var.name_prefix

  tags = merge(var.tags, { Name = var.name_prefix })
}

resource "aws_lb" "this" {
  name                       = "${var.name_prefix}-alb"
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [var.alb_security_group_id]
  subnets                    = var.public_subnet_ids
  drop_invalid_header_fields = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-alb" })
}

resource "aws_lb_target_group" "this" {
  name        = "${var.name_prefix}-tg"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/ready" # verifies DB pool connectivity, not just process liveness - see routes/health.py
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  # SSE (/v1/query/stream) needs long-lived responses - the deregistration
  # delay must not cut off an in-flight stream during a deployment.
  deregistration_delay = 30

  tags = merge(var.tags, { Name = "${var.name_prefix}-tg" })
}

# HTTP only for this pilot (approved Option A). enable_https exists as a
# toggle for PR-010 once a real domain/ACM certificate decision is made -
# see infra/README.md's TLS/domain section. It does not add a second
# listener on its own; wiring an HTTPS listener is left to that future PR
# so this module never silently claims TLS support it doesn't have.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = var.alb_listener_port
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }
}

locals {
  container_name = "app"

  container_env_list = [
    for k, v in var.container_environment : { name = k, value = v }
  ]

  container_secrets_list = [
    for k, v in var.container_secrets : { name = k, valueFrom = v }
  ]

  container_definitions = jsonencode([
    {
      name      = local.container_name
      image     = "${aws_ecr_repository.this.repository_url}:${var.image_tag}"
      essential = true
      portMappings = [
        { containerPort = var.container_port, protocol = "tcp" }
      ]
      environment = local.container_env_list
      secrets     = local.container_secrets_list
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.this.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = var.name_prefix
        }
      }
    }
  ])
}

resource "aws_ecs_task_definition" "this" {
  family                   = var.name_prefix
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn
  container_definitions    = local.container_definitions

  # Explicit for this pilot (approved: stay on X86_64, do not move to
  # ARM64/Graviton in PR-009). Any image built for this task definition -
  # locally or in CI - MUST target linux/amd64
  # (e.g. `docker build --platform linux/amd64 ...`); an arm64 image
  # (the default on Apple Silicon build machines) will fail to run here.
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  tags = merge(var.tags, { Name = var.name_prefix })
}

# desired_count=1 with deployment_minimum_healthy_percent=0 and
# deployment_maximum_percent=100: this caps in-flight tasks (RUNNING+PENDING)
# at floor(1 * 100%) = 1 and requires only ceil(1 * 0%) = 0 healthy tasks
# during a deployment. Because the old task occupies that single slot until
# it reaches STOPPED, ECS cannot create the new task's PENDING entry while
# the old one is still RUNNING - it must fully stop the old task first. This
# makes two run_migrations() startup calls overlapping in time impossible
# (see infra/README.md for the full proof), at the cost of brief downtime
# during every deployment - an explicit, approved trade-off for this pilot.
# DO NOT change these two values without re-deriving that proof.
#
# Scope of that guarantee, stated precisely (adversarial-review finding):
# it covers this ECS SERVICE's own managed rolling deployment, force-new-
# deployment, and steady-state single-task replacement after a crash - all
# of which go through this service's deployment configuration. It does NOT
# and CANNOT cover a task manually launched via `aws ecs run-task` against
# the same task definition outside this service - that bypasses this
# deployment configuration entirely and could race with the service's own
# task. Don't do that against this task definition while relying on this
# guarantee.
resource "aws_ecs_service" "this" {
  name            = var.name_prefix
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = var.deployment_minimum_healthy_percent
  deployment_maximum_percent         = var.deployment_maximum_percent
  health_check_grace_period_seconds  = var.health_check_grace_period_seconds

  dynamic "deployment_circuit_breaker" {
    for_each = var.enable_deployment_circuit_breaker ? [1] : []
    content {
      enable   = true
      rollback = true
    }
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.this.arn
    container_name   = local.container_name
    container_port   = var.container_port
  }

  tags = merge(var.tags, { Name = var.name_prefix })

  depends_on = [aws_lb_listener.http]
}
