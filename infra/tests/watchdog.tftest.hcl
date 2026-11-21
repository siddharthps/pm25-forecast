# Safety rules for the watchdog (#16, T9; D-011, D-041), on a mock AWS provider: offline, no
# credentials, nothing created. Run: terraform -chdir=infra test

mock_provider "aws" {
  source = "./tests/mocks"
}

variables {
  alert_email           = "owner@example.invalid"
  prefect_account_id    = "1d2c3b4a-5f6e-4a7b-8c9d-0e1f2a3b4c5d"
  prefect_workspace_id  = "2e3d4c5b-6a7f-4b8c-9d0e-1f2a3b4c5d6e"
  prefect_deployment_id = "3f4e5d6c-7b8a-4c9d-8e1f-2a3b4c5d6e7f"
  # Any file stands in for the zip: the mock provider only hashes it.
  watchdog_zip = "README.md"
}

run "two_daily_checks_in_chicago_time" {
  command = apply

  assert {
    condition     = toset(keys(aws_scheduler_schedule.watchdog)) == toset(["retry", "verify"])
    error_message = "Exactly two schedules: the 08:00 retry and the 09:00 verify."
  }

  assert {
    condition = (
      aws_scheduler_schedule.watchdog["retry"].schedule_expression == "cron(0 8 * * ? *)"
      && aws_scheduler_schedule.watchdog["verify"].schedule_expression == "cron(0 9 * * ? *)"
    )
    error_message = "The retry runs at 08:00 and the verify at 09:00, two and three hours after the issue time."
  }

  assert {
    condition     = alltrue([for s in aws_scheduler_schedule.watchdog : s.schedule_expression_timezone == "America/Chicago"])
    error_message = "The schedules follow the issue time's zone (D-019), so DST is handled by AWS."
  }

  assert {
    condition     = alltrue([for s in aws_scheduler_schedule.watchdog : one(s.flexible_time_window).mode == "OFF"])
    error_message = "No flexible window: the checks run on the hour."
  }

  assert {
    condition = alltrue([for k, s in aws_scheduler_schedule.watchdog : jsondecode(one(s.target).input) == {
      mode           = k
      scheduled_time = "<aws.scheduler.scheduled-time>"
    }])
    error_message = "Each schedule passes its mode and the scheduled time, so the Lambda checks the right day."
  }

  assert {
    # The raw text, not jsondecode: the scheduler substitutes only the literal placeholder, and
    # jsonencode writes < and > as < and >, which decode back and hid this (2026-11-21).
    condition     = alltrue([for s in aws_scheduler_schedule.watchdog : strcontains(one(s.target).input, "\"<aws.scheduler.scheduled-time>\"")])
    error_message = "The input must hold the literal <aws.scheduler.scheduled-time>, or the scheduler sends the placeholder itself."
  }

  assert {
    condition     = alltrue([for s in aws_scheduler_schedule.watchdog : one(s.target).arn == aws_lambda_function.watchdog.arn])
    error_message = "Both schedules invoke the watchdog Lambda."
  }
}

run "the_lambda_runs_the_zipped_handler" {
  command = apply

  assert {
    condition = (
      aws_lambda_function.watchdog.runtime == "python3.12"
      && aws_lambda_function.watchdog.architectures == tolist(["arm64"])
      && aws_lambda_function.watchdog.handler == "handler.lambda_handler"
    )
    error_message = "Python 3.12 (D-026) on arm64, matching the build's wheels."
  }

  assert {
    condition     = aws_lambda_function.watchdog.timeout <= 60
    error_message = "A check takes seconds; a hung call is cut off within a minute."
  }

  assert {
    condition = aws_lambda_function.watchdog.environment[0].variables == tomap({
      DATA_BUCKET           = aws_s3_bucket.private.bucket
      ALERT_TOPIC_ARN       = aws_sns_topic.alerts.arn
      PREFECT_KEY_PARAMETER = "/pm25-forecast/prefect-api-key"
      PREFECT_API_URL       = "https://api.prefect.cloud/api/accounts/1d2c3b4a-5f6e-4a7b-8c9d-0e1f2a3b4c5d/workspaces/2e3d4c5b-6a7f-4b8c-9d0e-1f2a3b4c5d6e"
      PREFECT_DEPLOYMENT_ID = "3f4e5d6c-7b8a-4c9d-8e1f-2a3b4c5d6e7f"
    })
    error_message = "The Lambda's settings: names and IDs only, never the key itself."
  }

  assert {
    condition     = aws_lambda_function_event_invoke_config.watchdog.maximum_retry_attempts == 0
    error_message = "No async retries: a failed check has already emailed."
  }

  assert {
    condition     = one(aws_lambda_function.watchdog.logging_config).application_log_level == "INFO"
    error_message = "INFO, never DEBUG: at DEBUG the AWS SDK logs the decrypted key."
  }

  assert {
    condition     = aws_cloudwatch_log_group.watchdog.retention_in_days == 30
    error_message = "Logs are kept 30 days, then expire."
  }
}

run "the_lambda_may_only_check_start_and_email" {
  command = apply

  assert {
    condition = toset(flatten([
      for s in jsondecode(aws_iam_role_policy.watchdog.policy).Statement : s.Action
      ])) == toset([
      "s3:ListBucket", "s3:GetObject", "s3:PutObject", "ssm:GetParameter", "sns:Publish",
      "logs:CreateLogStream", "logs:PutLogEvents",
    ])
    error_message = "Only these actions; no deletes, no wildcards."
  }

  assert {
    condition = alltrue([
      for s in jsondecode(aws_iam_role_policy.watchdog.policy).Statement :
      s.Effect == "Allow" && !strcontains(jsonencode(s.Resource), "\"*\"")
    ])
    error_message = "Every statement names its resources; none is \"*\"."
  }

  assert {
    condition = one([
      for s in jsondecode(aws_iam_role_policy.watchdog.policy).Statement : s.Resource
      if s.Action == "s3:PutObject"
    ]) == "arn:aws:s3:::pm25-forecast-data-65bc08/reports/compute-alerts/*"
    error_message = "The only write is the monthly alert marker, outside the ledger and the records."
  }

  assert {
    condition = one([
      for s in jsondecode(aws_iam_role_policy.watchdog.policy).Statement : s.Resource
      if s.Action == "s3:GetObject"
    ]) == "arn:aws:s3:::pm25-forecast-data-65bc08/reports/compute/*"
    error_message = "It reads only the compute ledger (records are checked by listing)."
  }

  assert {
    condition = one([
      for s in jsondecode(aws_iam_role_policy.watchdog.policy).Statement : s.Resource
      if s.Action == "ssm:GetParameter"
    ]) == "arn:aws:ssm:us-east-1:123456789012:parameter/pm25-forecast/prefect-api-key"
    error_message = "It reads exactly one parameter: the Prefect key."
  }

  assert {
    condition = one([
      for s in jsondecode(aws_iam_role_policy.watchdog.policy).Statement : s.Resource
      if s.Action == "sns:Publish"
    ]) == aws_sns_topic.alerts.arn
    error_message = "It emails through the one alerts topic."
  }
}

run "only_the_scheduler_may_invoke_it" {
  command = apply

  assert {
    condition = one(jsondecode(aws_iam_role.scheduler.assume_role_policy).Statement) == {
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "scheduler.amazonaws.com" }
      Condition = { StringEquals = { "aws:SourceAccount" = "123456789012" } }
    }
    error_message = "Only EventBridge Scheduler, acting for this account, assumes the scheduler role."
  }

  assert {
    condition = one(jsondecode(aws_iam_role_policy.scheduler.policy).Statement) == {
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.watchdog.arn
    }
    error_message = "The scheduler role can invoke the watchdog and nothing else."
  }
}

run "failures_reach_the_owner" {
  command = apply

  assert {
    condition = (
      aws_sns_topic_subscription.owner_email.protocol == "email"
      && aws_sns_topic_subscription.owner_email.topic_arn == aws_sns_topic.alerts.arn
    )
    error_message = "The alerts topic emails the owner."
  }

  assert {
    condition = (
      aws_cloudwatch_metric_alarm.watchdog_errors.metric_name == "Errors"
      && aws_cloudwatch_metric_alarm.watchdog_errors.dimensions.FunctionName == aws_lambda_function.watchdog.function_name
      && aws_cloudwatch_metric_alarm.watchdog_errors.threshold == 1
      && aws_cloudwatch_metric_alarm.watchdog_errors.alarm_actions == toset([aws_sns_topic.alerts.arn])
    )
    error_message = "Any watchdog error or timeout raises an alarm that emails (fail closed)."
  }
}

run "workspace_id_must_be_a_uuid" {
  command = plan

  variables {
    prefect_workspace_id = "default"
  }

  expect_failures = [var.prefect_workspace_id]
}

run "deployment_id_must_be_a_uuid" {
  command = plan

  variables {
    prefect_deployment_id = "daily-forecast/daily-forecast"
  }

  expect_failures = [var.prefect_deployment_id]
}
