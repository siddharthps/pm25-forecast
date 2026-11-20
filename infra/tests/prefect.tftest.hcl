# Safety rules for the Prefect run's keyless AWS access (#15, T8; D-024, D-040), on a mock AWS
# provider: offline, no credentials, nothing created. Run: terraform -chdir=infra test

mock_provider "aws" {
  # Realistic ARNs: the provider checks the format of an ARN passed between resources.
  mock_resource "aws_iam_policy" {
    defaults = { arn = "arn:aws:iam::123456789012:policy/pm25-forecast-pipeline" }
  }
  mock_resource "aws_iam_openid_connect_provider" {
    defaults = { arn = "arn:aws:iam::123456789012:oidc-provider/api.prefect.cloud/oidc-provider" }
  }
}

variables {
  alert_email        = "owner@example.invalid"
  prefect_account_id = "1d2c3b4a-5f6e-4a7b-8c9d-0e1f2a3b4c5d"
}

run "the_oidc_provider_is_prefect_clouds" {
  command = apply

  assert {
    condition     = aws_iam_openid_connect_provider.prefect.url == "https://api.prefect.cloud/oidc-provider"
    error_message = "The OIDC provider must be Prefect Cloud's."
  }

  assert {
    condition     = length(aws_iam_openid_connect_provider.prefect.client_id_list) == 1 && contains(aws_iam_openid_connect_provider.prefect.client_id_list, "prefect-cloud")
    error_message = "The only audience is prefect-cloud."
  }
}

run "only_our_prefect_account_can_assume_the_role" {
  command = apply

  assert {
    condition     = length(jsondecode(aws_iam_role.prefect_run.assume_role_policy).Statement) == 1
    error_message = "The trust policy has exactly one statement."
  }

  assert {
    condition = (
      one(jsondecode(aws_iam_role.prefect_run.assume_role_policy).Statement).Action == "sts:AssumeRoleWithWebIdentity"
      && one(jsondecode(aws_iam_role.prefect_run.assume_role_policy).Statement).Effect == "Allow"
      && one(jsondecode(aws_iam_role.prefect_run.assume_role_policy).Statement).Principal == { Federated = aws_iam_openid_connect_provider.prefect.arn }
    )
    error_message = "Only web-identity assumption, only through the Prefect OIDC provider."
  }

  assert {
    # StringEquals, never StringLike: no wildcard can widen who gets in.
    condition = one(jsondecode(aws_iam_role.prefect_run.assume_role_policy).Statement).Condition == {
      StringEquals = {
        "api.prefect.cloud/oidc-provider:aud" = "prefect-cloud"
        "api.prefect.cloud/oidc-provider:sub" = "prefect:account:1d2c3b4a-5f6e-4a7b-8c9d-0e1f2a3b4c5d"
      }
    }
    error_message = "The role must be limited to our Prefect account and the prefect-cloud audience."
  }
}

run "the_role_gets_only_the_pipeline_policy" {
  command = apply

  assert {
    condition     = aws_iam_role_policy_attachment.prefect_run_pipeline.policy_arn == aws_iam_policy.pipeline.arn
    error_message = "The Prefect run's only permissions are the least-privilege pipeline policy."
  }

  assert {
    condition     = aws_iam_role_policy_attachment.prefect_run_pipeline.role == aws_iam_role.prefect_run.name
    error_message = "The pipeline policy is attached to the Prefect run role."
  }

  assert {
    condition     = aws_iam_role.prefect_run.max_session_duration == 3600
    error_message = "Sessions last at most an hour; a run takes minutes."
  }
}

run "prefect_account_id_must_be_a_uuid" {
  command = plan

  variables {
    prefect_account_id = "not-a-uuid"
  }

  expect_failures = [var.prefect_account_id]
}
