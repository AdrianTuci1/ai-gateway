variable "name" {
  description = "Lambda and API Gateway name."
  type        = string
}

variable "image_uri" {
  description = "ECR image URI for the gateway."
  type        = string
}

variable "app_secret_arn" {
  description = "Secrets Manager secret with secret_key, database_url, and bootstrap_token."
  type        = string
}

variable "dynamodb_table_arn" {
  description = "DynamoDB table ARN when the DynamoDB backend is used."
  type        = string
  default     = null
}

variable "environment" {
  description = "Environment variables for the Lambda functions."
  type        = map(string)
}

variable "subnet_ids" {
  description = "Private subnet IDs for the Lambda functions. Leave empty to run outside a VPC."
  type        = list(string)
  default     = []
}

variable "security_group_ids" {
  description = "Security groups for the Lambda functions."
  type        = list(string)
  default     = []
}

variable "memory_mb" {
  description = "Lambda memory in MB."
  type        = number
  default     = 1024
}

variable "timeout_seconds" {
  description = "Lambda timeout. API Gateway HTTP API caps requests at 30 seconds."
  type        = number
  default     = 30
}

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 14
}

variable "cors_allow_origins" {
  description = "Origins allowed by API Gateway CORS."
  type        = list(string)
  default     = ["*"]
}

variable "run_migrations" {
  description = "Invoke the migration Lambda after it is created and before API Gateway is enabled."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
