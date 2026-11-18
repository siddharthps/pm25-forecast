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
