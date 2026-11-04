variable "aws_region" {
  description = "AWS region."
  type        = string
  default     = "eu-central-1"
}

variable "name" {
  description = "Base name. The environment is appended to form the resource prefix."
  type        = string
  default     = "ai-gateway"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,40}$", var.name))
    error_message = "name must be lowercase letters, digits, and hyphens."
  }
}

variable "environment" {
  description = "Environment tag."
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,20}$", var.environment))
    error_message = "environment must be lowercase letters, digits, and hyphens."
  }
}

variable "image_uri" {
  description = "ECR image URI. Leave empty for the ECR bootstrap apply, then pass the built image."
  type        = string
  default     = ""
}

variable "data_backend" {
  description = "Storage backend: dynamodb for edge, postgres for a VPC-attached deployment."
  type        = string
  default     = "dynamodb"

  validation {
    condition     = contains(["dynamodb", "postgres"], var.data_backend)
    error_message = "data_backend must be dynamodb or postgres."
  }
}

variable "enable_vpc" {
  description = "Attach the Lambda to a VPC. Ignored for postgres, which always needs the VPC; defaults to false for dynamodb."
  type        = bool
  default     = null
}

variable "dynamodb_point_in_time_recovery" {
  description = "Enable continuous backups for the DynamoDB table."
  type        = bool
  default     = true
}

variable "dynamodb_deletion_protection" {
  description = "Protect the DynamoDB table from deletion."
  type        = bool
  default     = false
}

variable "vpc_cidr" {
  description = "VPC CIDR block."
  type        = string
  default     = "10.42.0.0/16"
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_engine_version" {
  description = "PostgreSQL major version."
  type        = string
  default     = "16"
}

variable "db_multi_az" {
  description = "Run a standby in a second AZ."
  type        = bool
  default     = false
}

variable "db_deletion_protection" {
  description = "Protect the database from deletion."
  type        = bool
  default     = false
}

variable "enable_rds_proxy" {
  description = "Create an RDS Proxy for Lambda connection pooling."
  type        = bool
  default     = true
}

variable "lambda_memory_mb" {
  description = "Lambda memory in MB."
  type        = number
  default     = 1024
}

variable "lambda_timeout_seconds" {
  description = "Lambda timeout. API Gateway HTTP API caps requests at 30 seconds."
  type        = number
  default     = 30
}

variable "run_migrations" {
  description = "Prepare storage through the migration Lambda before enabling the API (Alembic for Postgres, builtin roles for DynamoDB)."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Additional tags."
  type        = map(string)
  default     = {}
}
