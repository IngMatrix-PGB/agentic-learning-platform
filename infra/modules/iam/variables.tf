variable "name_prefix" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "master_user_secret_arn" {
  description = "RDS-managed Secrets Manager secret ARN the execution role resolves at task-launch time."
  type        = string
}

variable "s3_bucket_arn" {
  type = string
}

variable "bedrock_embedding_model_id" {
  type    = string
  default = "amazon.titan-embed-text-v2:0"
}

variable "bedrock_chat_model_id" {
  type    = string
  default = "anthropic.claude-3-5-haiku-20241022-v1:0"
}

variable "bedrock_embedding_resource_arns" {
  description = <<-EOT
    Override for the embedding model's invocable resource ARN(s). Leave empty
    to use the default foundation-model ARN shape - UNVERIFIED against the
    real target account/region as of this implementation (no personal-project
    AWS credentials were available in this session; only unrelated
    organization AWS profiles exist on this machine, and those were
    deliberately NOT used for this personal project). Verify with
    `aws bedrock get-foundation-model` / `aws bedrock list-inference-profiles`
    against the real target account before the first apply, and set this
    explicitly if the model requires an inference-profile ARN instead.
  EOT
  type        = list(string)
  default     = []
}

variable "bedrock_chat_resource_arns" {
  description = "Same override mechanism as bedrock_embedding_resource_arns, for the chat/generation model. Claude models are the more likely of the two to require a cross-region inference-profile ARN rather than the bare foundation-model ARN - UNVERIFIED, see that variable's description."
  type        = list(string)
  default     = []
}

variable "tags" {
  type    = map(string)
  default = {}
}

# Used only for the Bedrock ARN construction below - the ECR/log-group ARN
# reconstruction this module previously did (a name-convention guess) was
# removed entirely; that policy now lives at the environments/dev root,
# wired from modules/ecs's real resource outputs (see main.tf's header
# comment). data.aws_caller_identity is no longer needed here as a result.
data "aws_partition" "current" {}

locals {
  # UNVERIFIED default shape - see the two resource-arn variables'
  # descriptions above. Overridden entirely when the corresponding
  # *_resource_arns variable is non-empty. Uses the real partition (not a
  # hardcoded "aws" literal) so this is still correct outside the standard
  # commercial AWS partition, e.g. GovCloud/China, if this were ever reused
  # there.
  embedding_resource_arns = length(var.bedrock_embedding_resource_arns) > 0 ? (
    var.bedrock_embedding_resource_arns
  ) : ["arn:${data.aws_partition.current.partition}:bedrock:${var.aws_region}::foundation-model/${var.bedrock_embedding_model_id}"]

  chat_resource_arns = length(var.bedrock_chat_resource_arns) > 0 ? (
    var.bedrock_chat_resource_arns
  ) : ["arn:${data.aws_partition.current.partition}:bedrock:${var.aws_region}::foundation-model/${var.bedrock_chat_model_id}"]
}
