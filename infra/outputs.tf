output "private_bucket" {
  description = "Private data bucket (raw/, records/, models/, reports/)."
  value       = aws_s3_bucket.private.bucket
}

output "public_bucket" {
  description = "Public bucket for derived JSON only."
  value       = aws_s3_bucket.public.bucket
}

output "public_base_url" {
  description = "HTTPS base URL the page fetches JSON from."
  value       = "https://${aws_s3_bucket.public.bucket}.s3.${var.region}.amazonaws.com/"
}

output "pipeline_policy_arn" {
  description = "IAM policy to attach to the pipeline's identity in T8 (D-024)."
  value       = aws_iam_policy.pipeline.arn
}

output "prefect_run_role_arn" {
  description = "Role ARN to enter in the managed work pool's Federated Identity settings (T8)."
  value       = aws_iam_role.prefect_run.arn
}

output "alerts_topic_arn" {
  description = "SNS topic for the watchdog's emails (T9). Confirm the subscription email first."
  value       = aws_sns_topic.alerts.arn
}

output "watchdog_function_name" {
  description = "The watchdog Lambda, for a test invoke (T9 guide)."
  value       = aws_lambda_function.watchdog.function_name
}

output "prefect_key_parameter" {
  description = "SSM parameter the owner creates with the Prefect API key (T9 guide)."
  value       = local.prefect_key_param
}

output "github_token_parameter" {
  description = "SSM parameter the owner creates with the GitHub lock token (#113, T9 guide)."
  value       = local.github_token_param
}
