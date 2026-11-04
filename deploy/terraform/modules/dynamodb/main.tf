resource "aws_dynamodb_table" "this" {
  name         = var.name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  point_in_time_recovery {
    enabled = var.point_in_time_recovery
  }

  server_side_encryption {
    enabled = true
  }

  ttl {
    attribute_name = "expires_at_epoch"
    enabled        = true
  }

  deletion_protection_enabled = var.deletion_protection

  tags = merge(var.tags, { Name = var.name })
}
