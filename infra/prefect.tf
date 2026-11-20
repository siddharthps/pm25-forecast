# Keyless AWS access for the Prefect Managed run (#15, T8; D-024, D-040).
#
# Prefect Cloud is an OIDC identity provider. A managed run presents a token, AWS STS exchanges it
# (AssumeRoleWithWebIdentity) for temporary credentials of the role below, and Prefect injects
# them into the run. No long-lived key exists anywhere. Prefect's token names the account only,
# not a workspace or deployment, so the role trusts exactly our account's ID and the
# prefect-cloud audience. Its permissions are the least-privilege pipeline policy (iam.tf).
# Source: prefect.io/docs/v3/how-to-guides/deployment_infra/managed-aws-federated-identity.

resource "aws_iam_openid_connect_provider" "prefect" {
  url            = "https://api.prefect.cloud/oidc-provider"
  client_id_list = ["prefect-cloud"]
}

resource "aws_iam_role" "prefect_run" {
  name                 = "pm25-forecast-prefect-run"
  description          = "Assumed by this project's Prefect Managed runs (web identity). No keys."
  max_session_duration = 3600

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "sts:AssumeRoleWithWebIdentity"
        Principal = { Federated = aws_iam_openid_connect_provider.prefect.arn }
        Condition = {
          StringEquals = {
            "api.prefect.cloud/oidc-provider:aud" = "prefect-cloud"
            "api.prefect.cloud/oidc-provider:sub" = "prefect:account:${var.prefect_account_id}"
          }
        }
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "prefect_run_pipeline" {
  role       = aws_iam_role.prefect_run.name
  policy_arn = aws_iam_policy.pipeline.arn
}
