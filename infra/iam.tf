# The pipeline's permissions (#8; D-024). Only the policy is defined here: who it's attached to
# (a role assumed without keys, or a narrow rotated-key user) is decided in T8.
#
# Least privilege: read and write on the private prefixes, put *.json on the public bucket,
# no deletes anywhere (overwrites create versions, so history is never lost).

locals {
  private_objects = [for p in local.private_prefixes : "${local.private_arn}/${p}*"]
}

resource "aws_iam_policy" "pipeline" {
  name        = "pm25-forecast-pipeline"
  description = "AirWatch pipeline: private prefixes read/write, public *.json write. No deletes."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListPrivatePrefixes"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = local.private_arn
        Condition = {
          StringLike = { "s3:prefix" = [for p in local.private_prefixes : "${p}*"] }
        }
      },
      {
        Sid      = "ReadWritePrivateObjects"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = local.private_objects
      },
      {
        Sid      = "PublishPublicJson"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${local.public_arn}/*.json"
      },
    ]
  })
}
