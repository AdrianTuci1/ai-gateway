variable "name" {
  description = "Prefix for every resource."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnet IDs for RDS and RDS Proxy."
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security groups attached to RDS and RDS Proxy."
  type        = list(string)
}

variable "instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "engine_version" {
  description = "PostgreSQL major version."
  type        = string
  default     = "16"
}

variable "allocated_storage" {
  description = "Initial storage in GiB."
  type        = number
  default     = 20
}

variable "max_allocated_storage" {
  description = "Storage autoscaling ceiling in GiB."
  type        = number
  default     = 100
}

variable "db_name" {
  description = "Initial database name."
  type        = string
  default     = "agw"
}

variable "username" {
  description = "Master username."
  type        = string
  default     = "agw"
}

variable "multi_az" {
  description = "Run a standby in a second AZ."
  type        = bool
  default     = false
}

variable "backup_retention_days" {
  description = "Automated backup retention."
  type        = number
  default     = 7
}

variable "deletion_protection" {
  description = "Protect the database from deletion."
  type        = bool
  default     = false
}

variable "skip_final_snapshot" {
  description = "Skip the final snapshot when the database is destroyed."
  type        = bool
  default     = true
}

variable "enable_proxy" {
  description = "Create an RDS Proxy in front of Postgres."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
