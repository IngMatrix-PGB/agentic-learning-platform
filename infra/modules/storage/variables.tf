variable "bucket_name" {
  description = "Globally-unique name for the private source-document bucket."
  type        = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
