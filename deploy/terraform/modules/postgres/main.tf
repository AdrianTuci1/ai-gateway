resource "random_password" "master" {
  length  = 40
  special = false
}

resource "aws_db_subnet_group" "this" {
  name       = "${var.name}-pg"
  subnet_ids = var.subnet_ids

  tags = merge(var.tags, { Name = "${var.name}-pg" })
}

resource "aws_db_instance" "this" {
  identifier = "${var.name}-pg"

  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.db_name
  username = var.username
  password = random_password.master.result

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = var.security_group_ids
  publicly_accessible    = false

  multi_az                = var.multi_az
  backup_retention_period = var.backup_retention_days
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:00-sun:05:00"

  auto_minor_version_upgrade = true
  apply_immediately          = false
  deletion_protection        = var.deletion_protection
  skip_final_snapshot        = var.skip_final_snapshot
  final_snapshot_identifier  = var.skip_final_snapshot ? null : "${var.name}-final"

  tags = merge(var.tags, { Name = "${var.name}-pg" })
}

resource "aws_secretsmanager_secret" "db" {
  name = "${var.name}-db"

  tags = merge(var.tags, { Name = "${var.name}-db" })
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.db.id
  secret_string = jsonencode({
    username = var.username
    password = random_password.master.result
  })
}

data "aws_iam_policy_document" "proxy_assume" {
  count = var.enable_proxy ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["rds.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "proxy" {
  count = var.enable_proxy ? 1 : 0

  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.db.arn]
  }

  statement {
    actions   = ["kms:Decrypt"]
    resources = ["*"]
  }
}

resource "aws_iam_role" "proxy" {
  count = var.enable_proxy ? 1 : 0

  name               = "${var.name}-rds-proxy"
  assume_role_policy = data.aws_iam_policy_document.proxy_assume[0].json

  tags = merge(var.tags, { Name = "${var.name}-rds-proxy" })
}

resource "aws_iam_role_policy" "proxy" {
  count = var.enable_proxy ? 1 : 0

  name   = "${var.name}-rds-proxy"
  role   = aws_iam_role.proxy[0].id
  policy = data.aws_iam_policy_document.proxy[0].json
}

resource "aws_db_proxy" "this" {
  count = var.enable_proxy ? 1 : 0

  name                   = "${var.name}-proxy"
  debug_logging          = false
  engine_family          = "POSTGRESQL"
  idle_client_timeout    = 1800
  require_tls            = true
  role_arn               = aws_iam_role.proxy[0].arn
  vpc_security_group_ids = var.security_group_ids
  vpc_subnet_ids         = var.subnet_ids

  auth {
    auth_scheme = "SECRETS"
    iam_auth    = "DISABLED"
    secret_arn  = aws_secretsmanager_secret.db.arn
  }

  tags = merge(var.tags, { Name = "${var.name}-proxy" })

  depends_on = [aws_secretsmanager_secret_version.db]
}

resource "aws_db_proxy_default_target_group" "this" {
  count = var.enable_proxy ? 1 : 0

  db_proxy_name = aws_db_proxy.this[0].name

  connection_pool_config {
    connection_borrow_timeout    = 120
    max_connections_percent      = 90
    max_idle_connections_percent = 50
  }
}

resource "aws_db_proxy_target" "this" {
  count = var.enable_proxy ? 1 : 0

  db_instance_identifier = aws_db_instance.this.identifier
  db_proxy_name          = aws_db_proxy.this[0].name
  target_group_name      = aws_db_proxy_default_target_group.this[0].name
}

locals {
  database_host = var.enable_proxy ? aws_db_proxy.this[0].endpoint : aws_db_instance.this.address
}
