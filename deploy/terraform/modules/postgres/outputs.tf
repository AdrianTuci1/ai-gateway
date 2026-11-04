output "database_host" {
  description = "Host the application should use: RDS Proxy when enabled, otherwise the instance."
  value       = local.database_host
}

output "port" {
  value = 5432
}

output "database_name" {
  value = var.db_name
}

output "username" {
  value = var.username
}

output "password" {
  value     = random_password.master.result
  sensitive = true
}

output "db_secret_arn" {
  value = aws_secretsmanager_secret.db.arn
}

output "instance_address" {
  value = aws_db_instance.this.address
}

output "proxy_endpoint" {
  value = var.enable_proxy ? aws_db_proxy.this[0].endpoint : null
}
