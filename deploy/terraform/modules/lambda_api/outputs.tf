output "api_url" {
  value = aws_apigatewayv2_api.this.api_endpoint
}

output "function_name" {
  value = aws_lambda_function.this.function_name
}

output "migration_function_name" {
  value = aws_lambda_function.migrate.function_name
}

output "lambda_role_arn" {
  value = aws_iam_role.lambda.arn
}
