variable "name" {
  description = "Table name."
  type        = string
}

variable "point_in_time_recovery" {
  description = "Enable continuous backups."
  type        = bool
  default     = true
}

variable "deletion_protection" {
  description = "Prevent accidental destruction of the table."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to the table."
  type        = map(string)
  default     = {}
}
