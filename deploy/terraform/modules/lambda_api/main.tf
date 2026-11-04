resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "migrate" {
  name              = "/aws/lambda/${var.name}-migrate"
  retention_in_days = var.log_retention_days

  tags = var.tags
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "runtime" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.app_secret_arn]
  }

  statement {
    actions   = ["kms:Decrypt"]
    resources = ["*"]
  }

  dynamic "statement" {
    for_each = var.dynamodb_table_arn == null ? [] : [var.dynamodb_table_arn]
    content {
      actions = [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query",
        "dynamodb:BatchGetItem",
        "dynamodb:BatchWriteItem",
        "dynamodb:TransactWriteItems",
        "dynamodb:DescribeTable",
      ]
      resources = [statement.value, "${statement.value}/index/*"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${var.name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.assume.json

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "vpc" {
  count = length(var.subnet_ids) == 0 ? 0 : 1

  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "runtime" {
  name   = "${var.name}-runtime"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.runtime.json
}

resource "aws_lambda_function" "this" {
  function_name = var.name
  description   = "AI Gateway control plane"
  role          = aws_iam_role.lambda.arn

  package_type  = "Image"
  image_uri     = var.image_uri
  architectures = ["x86_64"]

  image_config {
    command = ["agw.lambda_handler.handler"]
  }

  memory_size = var.memory_mb
  timeout     = var.timeout_seconds

  environment {
    variables = var.environment
  }

  dynamic "vpc_config" {
    for_each = length(var.subnet_ids) == 0 ? [] : [1]
    content {
      subnet_ids         = var.subnet_ids
      security_group_ids = var.security_group_ids
    }
  }

  tags = var.tags

  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_function" "migrate" {
  function_name = "${var.name}-migrate"
  description   = "AI Gateway Alembic migrations"
  role          = aws_iam_role.lambda.arn

  package_type = "Image"
  image_uri    = var.image_uri

  image_config {
    command = ["agw.lambda_migrate.handler"]
  }

  memory_size = 1024
  timeout     = 300

  environment {
    variables = var.environment
  }

  dynamic "vpc_config" {
    for_each = length(var.subnet_ids) == 0 ? [] : [1]
    content {
      subnet_ids         = var.subnet_ids
      security_group_ids = var.security_group_ids
    }
  }

  tags = var.tags

  depends_on = [aws_cloudwatch_log_group.migrate]
}

data "aws_lambda_invocation" "migrate" {
  count = var.run_migrations ? 1 : 0

  function_name = aws_lambda_function.migrate.function_name
  input         = jsonencode({})

  # Seed the store only after the storage it talks to exists. The runtime policy
  # is what carries the table ARN, so waiting on it orders the migration after
  # the DynamoDB table (Postgres has its own ordering through the network).
  depends_on = [
    aws_lambda_function.migrate,
    aws_iam_role_policy.runtime,
  ]
}

resource "aws_apigatewayv2_api" "this" {
  name          = var.name
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins  = var.cors_allow_origins
    allow_methods  = ["*"]
    allow_headers  = ["*"]
    expose_headers = ["x-trace-id"]
    max_age        = 3600
  }

  tags = var.tags
}

resource "aws_apigatewayv2_integration" "this" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.this.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = min(var.timeout_seconds * 1000, 30000)

  depends_on = [data.aws_lambda_invocation.migrate]
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.this.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  tags = var.tags
}

resource "aws_lambda_permission" "api" {
  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}
