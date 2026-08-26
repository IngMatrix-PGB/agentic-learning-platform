# PR-009 — AWS Infrastructure (dev pilot)

Terraform for the `dev` pilot deployment of `agentic-learning-platform`'s
AWS-mode runtime (PR-008). This is infrastructure-as-code only: it never
provisions Bedrock models, it only grants the running application least-
privilege IAM access to invoke them, and it targets exactly one environment
(`dev`) by design — see the PR-009 discovery/planning conversation for the
full architecture rationale. This document is the operational summary; it
does not repeat every trade-off already recorded there.

## Structure

```
infra/
  bootstrap/            # one-time: the S3 bucket backing environments/dev's remote state
  modules/
    networking/          # VPC, public/private subnets, NAT Gateway, S3 Gateway endpoint, security groups
    database/            # RDS PostgreSQL (pgvector-capable), single-AZ, RDS-managed Secrets Manager credential
    storage/             # private S3 bucket for source documents (PR-008's S3DocumentStorageAdapter)
    iam/                 # ECS execution role + task role, least-privilege policies
    ecs/                 # ECR repo, CloudWatch log group, ECS cluster/service/task definition, ALB
  environments/
    dev/                 # wires the five modules together for the one approved environment
```

## Bootstrap (one-time, manual, NOT part of this PR's apply)

`environments/dev`'s backend is S3 with native locking
(`use_lockfile = true`, Terraform ≥ 1.10 — this implementation environment
has 1.15.5 installed). That bucket cannot be created in the state it backs,
so `infra/bootstrap` deliberately has **no** backend block (plain local
state) and must be applied once, by hand, before `environments/dev` can
point its backend at the resulting bucket name:

```bash
cd infra/bootstrap
terraform init
terraform apply -var="state_bucket_name=<globally-unique-name>"
# then replace REPLACE-WITH-BOOTSTRAP-STATE-BUCKET-NAME in
# environments/dev/versions.tf's backend block with that same name, and run
# `terraform init -reconfigure` in environments/dev (NOT `-migrate-state`:
# environments/dev has never been applied, so there is no existing local
# state to migrate - `-reconfigure` tells Terraform to just start using the
# new backend block as-is; the -backend=false init already run during
# implementation/review left this directory's working state expecting a
# different backend configuration, which is exactly what -reconfigure
# resolves).
```

**This apply has NOT been run.** `infra/bootstrap` is written, `terraform
init`/`validate` were exercised, but no state bucket exists yet — see the
PR-009 implementation report for exactly what remains blocked until you
separately authorize an apply.

## Approved pilot architecture

```
Internet (allowed_ingress_cidrs only)
   │  HTTP (TLS/domain deferred — see "TLS / domain" below)
   ▼
ALB  →  ECS Fargate (private, desired_count=1)  →  RDS PostgreSQL + pgvector (private)
                  │
                  ├──► Amazon Bedrock (InvokeModel / InvokeModelWithResponseStream)
                  ├──► S3 (source documents)
                  └──► CloudWatch Logs
```

RDS and ECS are never internet-facing. NAT Gateway provides ECS's outbound
path (Bedrock/ECR/CloudWatch); a free S3 Gateway endpoint keeps S3 traffic
off the NAT's billed per-GB path. No Interface VPC endpoints — not
justified at this traffic level. No Aurora, no Multi-AZ, no read replicas,
no autoscaling, no Bedrock Knowledge Bases, no S3 Vector Store, no
OpenSearch, no `awscc` provider anywhere in this tree.

## Ingress CIDR restriction — a compensating control, not authentication

`allowed_ingress_cidrs` is a **required** variable with no default.
`modules/networking`'s `variable "allowed_ingress_cidrs"` carries a
`validation` block that fails `plan`/`apply` with a hard, non-zero-exit
error if the list is empty or contains `0.0.0.0/0`, unless
`allow_unrestricted_ingress = true` is also set (it must not be, for this
pilot). **This is a `validation` block, not a `check` block** — an earlier
revision used a `check` block for this, which was found during adversarial
review to only ever emit a *warning*, never a hard failure, even when its
assertion fails (empirically reproduced: both `plan` and `apply` exited `0`
despite a failing `check` assertion). `validation` blocks on a variable are
enforced as real errors; this was verified for all four required scenarios
(empty list, `0.0.0.0/0`, a real restricted CIDR, and the explicit override)
during the fix round — see the PR-009 fix-round report for exact exit
codes. This restriction exists **only** because the application currently
trusts `X-Organization-Id`/`X-Course-Id`/`X-User-Id` headers with zero
verification (see the application repo's `routes/authorization.py` and
`infrastructure/authorization/dev_header_provider.py`) — restricting the
network path is a stopgap while that remains true. **It is not
authentication, and must never be represented as such.** Real
authentication (Cognito/OIDC/JWT) is PR-010 scope.

## TLS / domain

**Approved Option A**: HTTP ALB (port 80) restricted to
`allowed_ingress_cidrs`. No Route53 hosted zone, no ACM certificate, no
domain acquisition in PR-009 — none existed for this personal project at
implementation time (checked: no domain/ACM/Route53 reference anywhere in
the application repo, and none of the AWS CLI profiles configured on this
machine are evidenced to be this project's own account — they are all
unrelated organization accounts and were deliberately not used here). The
`enable_https` variable on `modules/ecs` exists as a first-class toggle for
whichever of Option B (real domain + ACM) or Option C (internal-only
access) is chosen later — it does not itself add an HTTPS listener.

## ECS deployment / migration-race serialization

The application runs its own startup migrations
(`infrastructure/db/migrations/runner.py`) on every process start, with no
database-side lock around its check-then-insert `schema_migrations` logic.
Two tasks starting concurrently could race. `desired_count=1` alone does
**not** prevent this during a rolling deployment, because ECS's *default*
deployment percentages (`minimum_healthy_percent=100`,
`maximum_percent=200`) explicitly allow a new task to start before the old
one stops.

This module instead sets `deployment_minimum_healthy_percent = 0` and
`deployment_maximum_percent = 100`. Proof this makes concurrent startup
migrations impossible:

- `maximum_percent=100` → max tasks allowed in `{PENDING, RUNNING}`
  simultaneously = `floor(1 × 100%) = 1`.
- `minimum_healthy_percent=0` → no floor forcing a second task to exist
  before the first is removed.
- The old task occupies that single slot as `RUNNING` until it reaches
  `STOPPED` — not merely "deregistered from the target group." Because the
  cap is 1, ECS cannot create the new task's `PENDING` entry while the old
  task still holds the slot; it must drive the old task to `STOPPED` first.
- Therefore the old task's process (and its own long-since-completed
  startup migration) fully exits before the new task's process — and its
  own `run_migrations()` call — ever starts. **Two migration runs can never
  overlap in time under this configuration.**

**Trade-off, deliberately accepted for this pilot**: brief downtime on
every deployment (the window between old-task-stop and new-task-ready:
image pull if not cached, Docling/model init, migration run, ALB health-
check grace period — see `health_check_grace_period_seconds = 120` below).
`deployment_circuit_breaker { enable = true, rollback = true }` is also
enabled as an orthogonal safety net — if the new task fails to stabilize,
ECS auto-rolls back to the previous task definition; this does not weaken
the serialization proof above.

**Do not change `deployment_minimum_healthy_percent`/
`deployment_maximum_percent` without re-deriving this proof.** If
`desired_count` is ever raised above 1, this configuration no longer
applies and the underlying race must be fixed properly (a PostgreSQL
advisory lock in the migration runner, or a one-off migration task) —
tracked as PR-010 debt, not solved here.

**Scope of this guarantee, stated precisely** (adversarial-review finding):
it covers this ECS service's own managed rolling deployment,
force-new-deployment, and steady-state single-task replacement after a
crash — all of which go through this service's deployment configuration.
It does **not**, and cannot, cover a task manually launched via
`aws ecs run-task` against the same task definition outside this service —
that bypasses the deployment configuration entirely and could race with
the service's own task. Don't do that against this task definition while
relying on this guarantee.

## ECS health-check grace period

`health_check_grace_period_seconds = 120` (a `modules/ecs` variable,
defaulted for `dev`) — without it, the ALB's health check could mark a
freshly-launched task unhealthy before it finishes Docling/model import
plus the startup migration run, before the app is even ready to serve
`/ready`. **120 seconds is a pilot value, not a benchmarked one** — tune it
from a real observed cold-start time once this is deployed. Does not
change the ALB health-check path (`/ready`) or its existing
interval/timeout/threshold values.

## ECR image-tag / lifecycle contract

Every `image_tag` **must** start with `sha-` (e.g. `sha-824976c`) —
enforced by a hard `validation` block on both `modules/ecs`'s and
`environments/dev`'s `image_tag` variable. This exists because the ECR
lifecycle policy's second rule (`tagPrefixList = ["sha-"]`, "keep only the
last N tagged images") only matches tags with that exact prefix — a bare
SHA (no `sha-` prefix) would silently never match, making that cleanup
rule permanently ineffective (found during adversarial review). Terraform
never rewrites whatever tag you actually push — it only refuses to plan
with one that doesn't start with `sha-`.

## Fargate CPU architecture

`aws_ecs_task_definition.this` sets `runtime_platform { operating_system_family
= "LINUX", cpu_architecture = "X86_64" }` explicitly (approved: stay on
X86_64 for this pilot, no move to ARM64/Graviton). **Any image built for
this task definition — locally or in CI — must target `linux/amd64`**
(e.g. `docker build --platform linux/amd64 ...`). This matters concretely
because this Terraform was authored and validated on an Apple Silicon
(`darwin_arm64`) machine, where a plain `docker build` produces an arm64
image by default — which would fail to run against this task definition's
X86_64 runtime platform. The `Dockerfile` itself is unchanged by this PR.

## IAM/ECS coupling

`modules/iam`'s execution-role policy needs the **real** ARNs of the ECR
repository and CloudWatch log group that `modules/ecs` creates; `modules/ecs`'s
task definition needs `modules/iam`'s role ARNs. Neither module can own
both sides without depending on the other, which would be a genuine
Terraform module cycle.

**Resolved** (not merely documented as accepted debt — an acyclic
real-resource-output wiring turned out to be cleanly possible): the
ECR-pull (`ecr:BatchGetImage`/`GetDownloadUrlForLayer`) and CloudWatch-Logs
(`logs:CreateLogStream`/`PutLogEvents`) statements were moved out of
`modules/iam` entirely and are now a separate `aws_iam_role_policy`
resource declared at the `environments/dev` **root**
(`aws_iam_role_policy.ecs_execution_ecr_logs`), which references
`module.ecs.ecr_repository_arn`/`module.ecs.log_group_arn` (real resource
outputs, not a name-convention guess) and `module.iam.execution_role_name`
(to attach to). The root module can safely depend on both already-evaluated
child modules — neither `iam` nor `ecs` references the other directly, so
there is no cycle, and no 6th module or `terraform_remote_state` was
introduced. `modules/iam` retains ownership of both IAM roles and the
Bedrock/S3 policy (which had no such cross-dependency); only the two
ECR/Logs statements moved. Resource scoping is unchanged (still
least-privilege, no wildcards) — if anything it's now *more* correct,
since it references the actual created resources instead of reconstructing
their names.

**Remaining coupling**: none of the ARN-guessing kind. The only coupling
left is the ordinary kind any Terraform root module has with its child
modules' outputs — not a defect.

## Pre-apply verification gates — three UNVERIFIED assumptions

None of these were empirically tested against a real target AWS account in
this PR (no target-account credentials were available — see below). Each
one **must** be verified before the first real apply/use of this
infrastructure is trusted, and a failure at any of them **must block**
deployment until resolved — none is safe to assume true from documentation
alone.

**A. PostgreSQL engine-version availability.** `engine_version` (currently
`16.4`) must actually be offered by RDS in the real target account/region
at apply time — AWS periodically retires old minor versions. Verify with
`aws rds describe-db-engine-versions --engine postgres` before apply (see
`modules/database/variables.tf`'s `engine_version` description).

**B. Bedrock foundation-model / inference-profile ARN shape.** See the
dedicated "Bedrock IAM resource ARNs — UNVERIFIED by default" section
immediately below — unchanged by this note.

**C. RDS master-user pgvector migration capability.** The application
schema requires the PostgreSQL `vector` extension (pgvector) — the
existing migration runner executes `CREATE EXTENSION IF NOT EXISTS vector`
using the RDS-managed master user this Terraform creates
(`manage_master_user_password`, see "Database credentials — pilot
compromise" below). This infrastructure provisions PostgreSQL; it does
**not** empirically prove that this specific master user, in the actual
target account/region, can successfully execute that extension migration.
This is a reasonable expectation based on documented AWS RDS PostgreSQL
behavior, but it has not been tested against a real instance in this PR —
**it remains UNVERIFIED until proven against the actual deployed target
RDS environment.** Before the first real pilot apply/use, verify that a
real ECS task boot completes `run_migrations()` successfully (no
`MigrationConflictError`, no extension-creation failure — see the
deployment acceptance test below); if that verification fails, deployment
must be blocked until resolved, not worked around by escalating
privileges or introducing new infrastructure ad hoc.

## Bedrock IAM resource ARNs — UNVERIFIED by default

No real AWS credentials for this personal project's actual target account
were available during implementation — the AWS CLI profiles configured on
this machine are all unrelated organization accounts, and were
deliberately not used to avoid conflating this personal project with them.
`modules/iam` therefore defaults to constructing
`arn:${partition}:bedrock:<region>::foundation-model/<model-id>` (using
`data.aws_partition.current.partition`, not a hardcoded `"aws"` literal —
correct outside the standard commercial partition too, e.g.
GovCloud/China) for both the embedding and chat models — **this shape is
still UNVERIFIED against the real target account/region**, unaffected by
that partition fix. Some Bedrock models (Claude models in particular)
require invocation via a cross-region **inference profile** ARN
(`arn:${partition}:bedrock:<region>:<account-id>:inference-profile/<profile-id>`)
instead of the bare foundation-model ARN — a different resource type
entirely.

Before treating the default as correct: with real target-account
credentials, run
```bash
aws bedrock get-foundation-model --model-identifier amazon.titan-embed-text-v2:0
aws bedrock list-inference-profiles
```
in the target region, and if the chat model requires a profile ARN, set
`bedrock_chat_resource_arns` (and/or `bedrock_embedding_resource_arns`)
explicitly in `terraform.tfvars`. **A real Bedrock invocation/smoke test
against the deployed pilot is required before PR-009 can be declared
operationally validated** — do not treat the first `AccessDeniedException`
in a production request as the intended discovery mechanism; that is a
sign the ARN shape was never actually verified.

## Database credentials — pilot compromise

RDS's `manage_master_user_password` feature stores the master credential in
Secrets Manager and is used for **both** the application's startup
migrations (`CREATE EXTENSION vector`, DDL) **and** all normal runtime
traffic — there is no separate migration-privileged vs.
runtime-DML-privileged credential in PR-009. **This is a deliberate pilot
compromise, not the final least-privilege model.** PR-010 should split
these: a narrower runtime credential (DML only, no DDL/extension
privileges) for request-serving connections, and the current privileged
credential reserved for migrations only. This requires either a DB-side
bootstrap step or an application-level change (two DSNs), neither of which
this PR builds.

What PR-009 does guarantee: the secret lives in Secrets Manager only; no
`password` Terraform variable exists anywhere in this tree; no committed
`.tfvars` file contains it; no Terraform `output` exposes the secret
*value* (only its ARN, an identifier); it is injected into the ECS task via
the task definition's `secrets` block, resolved by the **execution role**
at task launch; and the application never logs it (confirmed unchanged
behavior from PR-008's verified logging).

## Checkov

Approved as the one additive static-analysis check for PR-009 (not tfsec —
neither was previously installed on this machine; Checkov was chosen for
its Python-based install path, consistent with this repo's existing `uv`
tooling, and its broad default coverage of exactly the S3/RDS/SG concerns
in this plan). Run manually, not wired into any CI/CD pipeline (none exists
for this repo):
```bash
uv tool install checkov
checkov -d infra/ --skip-path infra/bootstrap  # bootstrap reviewed separately, see the implementation report
```
See the PR-009 implementation report for the actual run's findings and
their FIX / JUSTIFIED PILOT EXCEPTION / FALSE POSITIVE disposition.
Checkov is additive — `terraform plan` review by a human remains the real
gate, never replaced by a clean scanner run.

## Validation

```bash
terraform fmt -check -recursive infra/
cd infra/bootstrap        && terraform init -backend=false && terraform validate
cd infra/environments/dev && terraform init -backend=false && terraform validate
```
`terraform plan` for `environments/dev` requires the bootstrap bucket to
exist first (its backend block references a real bucket name) — see the
PR-009 implementation report for exactly what is blocked until bootstrap is
authorized and applied.

## Deployment acceptance test (after a real, separately-authorized apply + image push)

1. `terraform apply` (bootstrap, then `environments/dev`) — **not performed
   by this PR**.
2. Build (targeting `linux/amd64` — see "Fargate CPU architecture" above)
   and push the application image, tagged `sha-<git-sha>`, to the ECR
   repository this Terraform creates.
3. `terraform apply -var="image_tag=sha-<git-sha>"` (or update the task
   definition directly) to roll the ECS service onto that image.
4. `GET http://<alb_dns_name>/health` → 200.
5. `GET http://<alb_dns_name>/ready` → 200 (confirms DB connectivity).
6. First-boot CloudWatch Logs entry shows the migration applying at
   `embedding_dimension=1024` with no `MigrationConflictError`.
7. `POST /v1/documents` with a real PDF → 200, object appears in S3 at the
   deterministic key, chunks appear in `document_chunks` with 1024-dim
   embeddings.
8. `POST /v1/query` returns an answer; CloudWatch Logs shows a
   `bedrock_generation_completed` line with real token counts/latency.
9. `POST /v1/query/stream` streams real incremental tokens, ending with a
   correct `citations`/`done` sequence.
10. Trigger a service update (new task-definition revision) and confirm via
    `aws ecs describe-services`/CloudWatch Logs that the old task reaches
    `STOPPED` before the new task's startup/migration log line appears —
    directly observing this document's serialization proof in practice.
11. Confirm the ALB, probed from an IP outside `allowed_ingress_cidrs`,
    times out rather than reaching the application.
12. `aws ecs describe-task-definition` shows no
    `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` anywhere — task role only.

## Rollback

ECR tags are immutable `sha-<git-sha>` values — rollback is
`aws ecs update-service --task-definition <family>:<previous-revision>`,
no rebuild needed. The migration runner has no down-migrations; rollback
assumes the previous application code remains compatible with whatever
schema state the newer code's migrations left behind (a pre-existing
constraint, not introduced by this PR). Terraform itself has no built-in
rollback — revert via `git checkout` of the previous `.tf` state and
`apply`, or fix forward.

## PR-010 debt (created or confirmed by this PR)

- Real authentication replacing the dev-header trust model (top priority —
  the CIDR restriction above is a compensating control, not a substitute).
- Split migration-privileged vs. runtime-DML-privileged database
  credentials.
- Resolve the TLS/domain decision (Option B: real domain + ACM, or Option
  C: internal-only access) — Option A here is explicitly temporary.
- Confirm the Bedrock resource-ARN shape with real credentials if that
  could not be done during PR-009's implementation, and remove the
  UNVERIFIED status.
- PostgreSQL advisory lock or one-off migration task, if `desired_count` is
  ever raised above 1.
- Autoscaling tuning, CloudWatch alarms/dashboards/SLOs/tracing, backup/
  restore drill, DR strategy, CI/CD deployment pipeline, evals-in-CI, a
  written pilot runbook beyond this document, S3 access logging/VPC Flow
  Logs/SSE-KMS upgrade if ever required.

## Apply gate

**No `terraform apply` has been run for any module, including
`infra/bootstrap`.** Preparing this Terraform is not authorization to apply
it — a real apply requires separate, explicit authorization after
reviewing the implementation, validation results, Checkov findings, and a
`terraform plan`.
