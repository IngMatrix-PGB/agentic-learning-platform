variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "state_bucket_name" {
  description = "Globally-unique name for the Terraform remote-state bucket."
  type        = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
