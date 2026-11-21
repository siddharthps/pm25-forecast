# The watchdog: the AWS backup trigger for the daily forecast (#16, T9; D-011, D-041).
#
# EventBridge Scheduler invokes one Lambda at 08:00 and 09:00 America/Chicago. At 08:00 it checks
# for today's record in S3 and, if missing, starts the Prefect deployment (key from SSM) and
# emails; it also emails once a month when Prefect minutes pass 300. At 09:00 it only checks, and
# emails if the record is still missing. Any error emails, and a CloudWatch alarm on the Lambda's
# errors emails too (fail closed). Code: src/airwatch/watchdog/handler.py, zipped by
# `uv run python -m airwatch.watchdog.build` into infra/build/ before plan.
#
# The Prefect key is created by the owner with the AWS CLI (notes/guides/T9-WATCHDOG.md), so its
# value never enters Terraform's state. Terraform only knows the parameter's name.

data "aws_caller_identity" "current" {}

locals {
  watchdog_name      = "pm25-forecast-watchdog"
  prefect_key_param  = "/pm25-forecast/prefect-api-key"
  prefect_key_arn    = "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${local.prefect_key_param}"
  watchdog_log_group = "/aws/lambda/${local.watchdog_name}"
  watchdog_zip       = "${path.module}/${var.watchdog_zip}"
}

# --- Email -------------------------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name = "pm25-forecast-alerts"
}

# AWS emails a confirmation link; alerts arrive only after the owner clicks it.
resource "aws_sns_topic_subscription" "owner_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# --- The Lambda --------------------------------------------------------------------------------

resource "aws_iam_role" "watchdog" {
  name        = local.watchdog_name
  description = "The watchdog Lambda: check the record, start one Prefect run, email."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "sts:AssumeRole"
        Principal = { Service = "lambda.amazonaws.com" }
      },
    ]
  })
}

resource "aws_iam_role_policy" "watchdog" {
  name = local.watchdog_name
  role = aws_iam_role.watchdog.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListRecordsAndLedger"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = local.private_arn
        Condition = {
          StringLike = { "s3:prefix" = ["records/*", "reports/compute/*"] }
        }
      },
      {
        Sid      = "ReadLedger"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${local.private_arn}/reports/compute/*"
      },
      {
        Sid      = "WriteMonthlyAlertMarker"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${local.private_arn}/reports/compute-alerts/*"
      },
      {
        Sid      = "ReadPrefectKey"
        Effect   = "Allow"
        Action   = "ssm:GetParameter"
        Resource = local.prefect_key_arn
      },
      {
        Sid      = "Email"
        Effect   = "Allow"
        Action   = "sns:Publish"
        Resource = aws_sns_topic.alerts.arn
      },
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.watchdog.arn}:*"
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "watchdog" {
  name              = local.watchdog_log_group
  retention_in_days = 30
}

resource "aws_lambda_function" "watchdog" {
  function_name    = local.watchdog_name
  description      = "Backup trigger for the daily forecast (D-011, D-041)."
  role             = aws_iam_role.watchdog.arn
  filename         = local.watchdog_zip
  source_code_hash = filebase64sha256(local.watchdog_zip)
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "handler.lambda_handler"
  memory_size      = 128
  timeout          = 60

  environment {
    variables = {
      DATA_BUCKET           = aws_s3_bucket.private.bucket
      ALERT_TOPIC_ARN       = aws_sns_topic.alerts.arn
      PREFECT_KEY_PARAMETER = local.prefect_key_param
      PREFECT_API_URL       = "https://api.prefect.cloud/api/accounts/${var.prefect_account_id}/workspaces/${var.prefect_workspace_id}"
      PREFECT_DEPLOYMENT_ID = var.prefect_deployment_id
    }
  }

  logging_config {
    log_format            = "JSON"
    log_group             = aws_cloudwatch_log_group.watchdog.name
    application_log_level = "INFO"
    system_log_level      = "WARN"
  }
}

# The scheduler's own retries cover a failed invoke. Lambda's async retries are off: a failed
# check has already emailed, and a repeat would only email again.
resource "aws_lambda_function_event_invoke_config" "watchdog" {
  function_name                = aws_lambda_function.watchdog.function_name
  maximum_retry_attempts       = 0
  maximum_event_age_in_seconds = 3600
}

resource "aws_cloudwatch_metric_alarm" "watchdog_errors" {
  alarm_name          = "${local.watchdog_name}-errors"
  alarm_description   = "The watchdog Lambda failed or timed out (D-041). Check its logs."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.watchdog.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# --- The schedules -----------------------------------------------------------------------------

resource "aws_iam_role" "scheduler" {
  name        = "${local.watchdog_name}-scheduler"
  description = "EventBridge Scheduler: invoke the watchdog Lambda, nothing else."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "sts:AssumeRole"
        Principal = { Service = "scheduler.amazonaws.com" }
        Condition = {
          StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
        }
      },
    ]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  name = "${local.watchdog_name}-scheduler"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.watchdog.arn
      },
    ]
  })
}

resource "aws_scheduler_schedule_group" "watchdog" {
  name = "pm25-forecast"
}

# 08:00 and 09:00 exist every day: US DST changes happen at 02:00.
resource "aws_scheduler_schedule" "watchdog" {
  for_each = { retry = 8, verify = 9 }

  name                         = "${local.watchdog_name}-${each.key}"
  group_name                   = aws_scheduler_schedule_group.watchdog.name
  description                  = "Watchdog ${each.key} check, ${each.value}:00 America/Chicago (D-041)."
  schedule_expression          = "cron(0 ${each.value} * * ? *)"
  schedule_expression_timezone = "America/Chicago"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.watchdog.arn
    role_arn = aws_iam_role.scheduler.arn
    input = jsonencode({
      mode           = each.key
      scheduled_time = "<aws.scheduler.scheduled-time>"
    })

    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }
  }
}
