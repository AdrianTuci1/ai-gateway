output "aws_region" {
  value = var.aws_region
}

output "data_backend" {
  value = var.data_backend
}

output "api_url" {
  value = module.api.api_url
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "app_secret_arn" {
  value = aws_secretsmanager_secret.app.arn
}

output "migration_function_name" {
  value = module.api.migration_function_name
}

output "database_host" {
  value = try(module.postgres[0].database_host, null)
}

output "dynamodb_table_name" {
  value = try(module.dynamodb[0].table_name, null)
}

output "dynamodb_table_arn" {
  value = try(module.dynamodb[0].table_arn, null)
}

output "vpc_id" {
  value = try(module.network[0].vpc_id, null)
}

output "bootstrap_token_command" {
  description = "Read the bootstrap token after apply."
  value = format(
    "aws secretsmanager get-secret-value --region %s --secret-id %s --query SecretString --output text | jq -r .bootstrap_token",
    var.aws_region,
    aws_secretsmanager_secret.app.arn,
  )
}
