terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  prefix = "${var.name}-${var.environment}"

  # Postgres lives in private subnets, so it always needs the VPC. DynamoDB is
  # reached over the AWS network, so the edge deployment can skip the VPC and
  # its NAT gateway.
  use_vpc = var.data_backend == "postgres" ? true : coalesce(var.enable_vpc, false)

  tags = merge(
    {
      Project     = "ai-gateway"
      Environment = var.environment
    },
    var.tags,
  )
}

module "network" {
  source = "../../modules/network"
  count  = local.use_vpc ? 1 : 0

  name     = local.prefix
  vpc_cidr = var.vpc_cidr
  tags     = local.tags
}

module "postgres" {
  source = "../../modules/postgres"
  count  = var.data_backend == "postgres" ? 1 : 0

  name               = local.prefix
  subnet_ids         = module.network[0].private_subnet_ids
  security_group_ids = [module.network[0].rds_security_group_id]

  instance_class      = var.db_instance_class
  engine_version      = var.db_engine_version
  multi_az            = var.db_multi_az
  deletion_protection = var.db_deletion_protection
  enable_proxy        = var.enable_rds_proxy
  tags                = local.tags
}

module "dynamodb" {
  source = "../../modules/dynamodb"
  count  = var.data_backend == "dynamodb" ? 1 : 0

  name                   = local.prefix
  point_in_time_recovery = var.dynamodb_point_in_time_recovery
  deletion_protection    = var.dynamodb_deletion_protection
  tags                   = local.tags
}

resource "random_password" "app_secret" {
  length  = 48
  special = false
}

resource "random_password" "bootstrap_token" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "app" {
  name = "${local.prefix}-app"

  tags = local.tags
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id

  secret_string = jsonencode(merge(
    {
      secret_key      = random_password.app_secret.result
      bootstrap_token = random_password.bootstrap_token.result
    },
    var.data_backend == "postgres" ? {
      database_url = format(
        "postgresql+asyncpg://%s:%s@%s:%d/%s?ssl=require",
        module.postgres[0].username,
        module.postgres[0].password,
        module.postgres[0].database_host,
        module.postgres[0].port,
        module.postgres[0].database_name,
      )
    } : {},
  ))
}

resource "aws_ecr_repository" "app" {
  name                 = local.prefix
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = local.tags
}

module "api" {
  source = "../../modules/lambda_api"

  name           = local.prefix
  image_uri      = var.image_uri != "" ? var.image_uri : "${aws_ecr_repository.app.repository_url}:bootstrap"
  app_secret_arn = aws_secretsmanager_secret.app.arn

  dynamodb_table_arn = var.data_backend == "dynamodb" ? module.dynamodb[0].table_arn : null

  environment = {
    AGW_RUNTIME           = "request_response"
    AGW_DB_BACKEND        = var.data_backend
    AGW_DYNAMODB_TABLE    = var.data_backend == "dynamodb" ? module.dynamodb[0].table_name : ""
    AGW_DB_POOL_MODE      = "null"
    AGW_APP_SECRET_ARN    = aws_secretsmanager_secret.app.arn
    AGW_BOOTSTRAP_ENABLED = "true"
    AGW_CA_ENABLED        = "false"
    AGW_CA_DIR            = "/tmp/agw-ca"
    AGW_UI_ENABLED        = "true"
    AGW_PUBLIC_BASE_URL   = ""
    AGW_LOG_LEVEL         = "info"
    # API Gateway HTTP API ends requests at 30 seconds; fail tool calls first.
    AGW_TOOL_TIMEOUT_SECONDS = "25"
  }

  subnet_ids         = local.use_vpc ? module.network[0].private_subnet_ids : []
  security_group_ids = local.use_vpc ? [module.network[0].lambda_security_group_id] : []

  memory_mb       = var.lambda_memory_mb
  timeout_seconds = var.lambda_timeout_seconds
  run_migrations  = var.run_migrations
  tags            = local.tags
}
