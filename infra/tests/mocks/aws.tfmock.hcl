# Realistic mock values for the AWS provider, shared by every test file. The provider checks the
# format of an ARN passed between resources, and the mock's random strings fail that check.

mock_resource "aws_iam_policy" {
  defaults = { arn = "arn:aws:iam::123456789012:policy/pm25-forecast-pipeline" }
}

mock_resource "aws_iam_openid_connect_provider" {
  defaults = { arn = "arn:aws:iam::123456789012:oidc-provider/api.prefect.cloud/oidc-provider" }
}

mock_resource "aws_iam_role" {
  defaults = { arn = "arn:aws:iam::123456789012:role/pm25-forecast-watchdog" }
}

mock_resource "aws_sns_topic" {
  defaults = { arn = "arn:aws:sns:us-east-1:123456789012:pm25-forecast-alerts" }
}

mock_resource "aws_cloudwatch_log_group" {
  defaults = { arn = "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/pm25-forecast-watchdog" }
}

mock_resource "aws_lambda_function" {
  defaults = { arn = "arn:aws:lambda:us-east-1:123456789012:function:pm25-forecast-watchdog" }
}

mock_data "aws_caller_identity" {
  defaults = { account_id = "123456789012" }
}
