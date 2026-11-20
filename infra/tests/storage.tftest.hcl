# Safety rules for the storage layer (#8, T3b; D-012, D-028), checked on the plan with a mock
# AWS provider: offline, no credentials, nothing created. Run: terraform -chdir=infra test

mock_provider "aws" {}

variables {
  alert_email        = "owner@example.invalid"
  prefect_account_id = "1d2c3b4a-5f6e-4a7b-8c9d-0e1f2a3b4c5d"
}

run "private_bucket_can_never_be_public" {
  command = plan

  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.private.block_public_acls,
      aws_s3_bucket_public_access_block.private.ignore_public_acls,
      aws_s3_bucket_public_access_block.private.block_public_policy,
      aws_s3_bucket_public_access_block.private.restrict_public_buckets,
    ])
    error_message = "All four public-access blocks must be on for the private bucket."
  }

  assert {
    condition     = one(aws_s3_bucket_ownership_controls.private.rule).object_ownership == "BucketOwnerEnforced"
    error_message = "ACLs must be disabled on the private bucket."
  }

  assert {
    condition     = one(aws_s3_bucket_versioning.private.versioning_configuration).status == "Enabled"
    error_message = "The private bucket must be versioned."
  }

  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.private.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256"
    error_message = "The private bucket must encrypt by default."
  }
}

run "private_lifecycle_trims_raw_and_never_touches_records" {
  command = plan

  assert {
    condition = anytrue([
      for r in aws_s3_bucket_lifecycle_configuration.private.rule :
      r.status == "Enabled" && one(r.filter).prefix == "raw/" && length(r.noncurrent_version_expiration) == 1
    ])
    error_message = "Old versions of raw/ downloads must expire."
  }

  assert {
    # records/ is the durable at-most-once record (T6): no rule may expire anything in it.
    condition = alltrue([
      for r in aws_s3_bucket_lifecycle_configuration.private.rule :
      length(r.expiration) == 0 && length(r.noncurrent_version_expiration) == 0
      if !startswith(one(r.filter).prefix, "raw/")
    ])
    error_message = "Only raw/ may have expiry rules; records/, models/ and reports/ are kept."
  }
}

run "public_bucket_allows_only_anonymous_reads_of_objects" {
  command = plan

  assert {
    # ACLs stay blocked; only a bucket policy may grant public reads.
    condition = alltrue([
      aws_s3_bucket_public_access_block.public.block_public_acls,
      aws_s3_bucket_public_access_block.public.ignore_public_acls,
    ])
    error_message = "Public ACLs must stay blocked on the public bucket."
  }

  assert {
    condition = length([
      for s in jsondecode(aws_s3_bucket_policy.public.policy).Statement : s
      if s.Effect == "Allow"
    ]) == 1
    error_message = "The public bucket policy must have exactly one Allow statement."
  }

  assert {
    condition = alltrue([
      for s in jsondecode(aws_s3_bucket_policy.public.policy).Statement :
      s.Action == "s3:GetObject" && s.Resource == "arn:aws:s3:::${aws_s3_bucket.public.bucket}/*"
      if s.Effect == "Allow"
    ])
    error_message = "Anonymous access must be s3:GetObject on objects only (no listing, no writes)."
  }
}

run "public_cors_is_the_pages_origin_only" {
  command = plan

  assert {
    condition     = one(aws_s3_bucket_cors_configuration.public.cors_rule).allowed_origins == toset(["https://siddharthps.github.io"])
    error_message = "CORS must allow only the GitHub Pages origin."
  }

  assert {
    condition     = one(aws_s3_bucket_cors_configuration.public.cors_rule).allowed_methods == toset(["GET", "HEAD"])
    error_message = "CORS must allow only GET and HEAD."
  }
}

run "both_buckets_refuse_plain_http" {
  command = plan

  assert {
    condition = alltrue([
      for p in [aws_s3_bucket_policy.private.policy, aws_s3_bucket_policy.public.policy] :
      anytrue([
        for s in jsondecode(p).Statement :
        s.Effect == "Deny" && s.Condition.Bool["aws:SecureTransport"] == "false"
      ])
    ])
    error_message = "Each bucket policy must deny requests without TLS."
  }
}

run "pipeline_policy_is_least_privilege" {
  command = plan

  assert {
    condition = alltrue(flatten([
      for s in jsondecode(aws_iam_policy.pipeline.policy).Statement : [
        for a in flatten([s.Action]) : !strcontains(a, "*") && a != "s3:DeleteObject"
      ]
    ]))
    error_message = "No wildcard actions, and the pipeline may not delete objects."
  }

  assert {
    # The pipeline writes only *.json to the public bucket, and nothing else there.
    condition = alltrue([
      for s in jsondecode(aws_iam_policy.pipeline.policy).Statement :
      flatten([s.Action]) == ["s3:PutObject"] && flatten([s.Resource]) == ["arn:aws:s3:::${aws_s3_bucket.public.bucket}/*.json"]
      if anytrue([for r in flatten([s.Resource]) : startswith(r, "arn:aws:s3:::${aws_s3_bucket.public.bucket}")])
    ])
    error_message = "On the public bucket the pipeline may only put *.json objects."
  }

  assert {
    condition = alltrue(flatten([
      for s in jsondecode(aws_iam_policy.pipeline.policy).Statement : [
        for r in flatten([s.Resource]) :
        startswith(r, "arn:aws:s3:::${aws_s3_bucket.private.bucket}") || startswith(r, "arn:aws:s3:::${aws_s3_bucket.public.bucket}")
      ]
    ]))
    error_message = "The pipeline policy may only name this project's two buckets."
  }
}

run "pages_origin_must_be_https_without_a_path" {
  command = plan

  variables {
    pages_origin = "http://siddharthps.github.io/"
  }

  expect_failures = [var.pages_origin]
}

run "alert_email_must_look_like_an_email" {
  command = plan

  variables {
    alert_email = "not-an-email"
  }

  expect_failures = [var.alert_email]
}
