# infra/: AirWatch AWS base (Terraform)

Everything AWS for this project is defined here (D-018). CI checks it offline: format, validate,
and `terraform test` with a mock AWS provider. **CI never has AWS credentials.** The owner runs
`plan` and `apply` from this PC (D-023).

## What it creates (T3b, #8)

| Resource | Why |
| --- | --- |
| Private bucket `pm25-forecast-data-65bc08` | `raw/`, `records/`, `models/`, `reports/`. All four public-access blocks on, ACLs off, versioned, SSE-S3, TLS only |
| Lifecycle on the private bucket | Superseded versions under `raw/` expire after 30 days. `records/`, `models/` and `reports/` keep every version. Failed multipart uploads are cleaned up after 7 days |
| Public bucket `pm25-forecast-public-65bc08` | Derived JSON for the page only (D-012, D-028). Anonymous `GetObject` on objects, no listing, ACLs still blocked, CORS for `https://siddharthps.github.io` only, TLS only, versioned (old versions expire after 30 days) |
| IAM policy `pm25-forecast-pipeline` | Read/write on the private prefixes, put `*.json` on the public bucket, **no deletes**. Attached to the Prefect run role (T8) |
| Watchdog (T9, #16): Lambda `pm25-forecast-watchdog`, two EventBridge schedules (08:00 and 09:00 America/Chicago, group `pm25-forecast`), SNS topic `pm25-forecast-alerts` with the owner's email, an alarm on the Lambda's errors, a 30-day log group, and two roles | The backup trigger (D-011, D-041). If the record is missing it starts one Prefect run, then emails. It also emails once a month above 300 Prefect minutes. The Lambda may list `records/` and the ledger, read the ledger, create the alert marker, read one SSM parameter and publish to the one topic. No deletes. The Prefect key's SSM parameter is created by the owner, not Terraform. Free tier |
| OIDC provider `api.prefect.cloud/oidc-provider` and role `pm25-forecast-prefect-run` (T8, #15) | Keyless AWS access for Prefect Managed runs: web identity federation, trusted only for our Prefect account and the `prefect-cloud` audience, 1-hour sessions, only the pipeline policy (D-040). Free |

State lives in `s3://pm25-forecast-tfstate-65bc08/pm25-forecast/base.tfstate` (created in T0c),
with S3-native locking.

## Cost estimate

Prices are from the AWS Pricing API (us-east-1, looked up 2026-11-18).

| Item | Assumption | Price | Per month |
| --- | --- | --- | --- |
| S3 Standard storage | about 2 GB (AQS history, models, reports) | $0.023 per GB-month | about $0.05 |
| PUT/LIST requests | about 3,000 (daily writes, lock checks) | $0.005 per 1,000 | about $0.02 |
| GET requests | about 30,000 (page views, pipeline reads) | $0.004 per 10,000 | about $0.01 |
| Data out | well under 1 GB of JSON | inside AWS's 100 GB/month free allowance | $0 |
| IAM policy | | free | $0 |
| Watchdog (T9) | about 60 Lambda runs and schedule invocations, a few emails, under 1 MB of logs | inside the free tiers: Lambda 1M requests, Scheduler 14M invocations, SNS 1,000 emails, CloudWatch 10 alarms and 5 GB of logs, SSM standard parameters free (pricing pages, read 2026-11-20) | $0 |

The total is **under $0.10 a month**, well inside the $5 budget alarm (success criterion 7).

## First apply: step by step (owner)

PowerShell, from the repo root (`cd ~/code/pm25-forecast` first: every command assumes it).
**In bash** (Git Bash, or the `!` prefix in Claude Code), use
`cp` instead of `Copy-Item`, and put the profile in front of each command, because each `!`
command may start a fresh shell:

```bash
aws sso login --profile pm25
cp infra/terraform.tfvars.example infra/terraform.tfvars
AWS_PROFILE=pm25 terraform -chdir=infra init
AWS_PROFILE=pm25 terraform -chdir=infra plan -out=tfplan
AWS_PROFILE=pm25 terraform -chdir=infra apply tfplan
```

1. **Log in** (an 8-hour session):

   ```powershell
   aws sso login --profile pm25
   $env:AWS_PROFILE = "pm25"
   ```

2. **Your alert email.** Copy the example file, then edit `infra/terraform.tfvars` and put your
   email in. That file is gitignored, so it never gets committed.

   ```powershell
   Copy-Item infra/terraform.tfvars.example infra/terraform.tfvars
   ```

3. **Init**, which connects to the state bucket:

   ```powershell
   terraform -chdir=infra init
   ```

4. **Plan.** This changes nothing; it only shows what would be created.

   ```powershell
   terraform -chdir=infra plan -out=tfplan
   ```

   Check that the last line says **`Plan: 16 to add, 0 to change, 0 to destroy.`** and that every
   resource name starts with `pm25-forecast`. Stop and ask if anything says *change* or *destroy*.

5. **Apply exactly that plan:**

   ```powershell
   terraform -chdir=infra apply tfplan
   ```

6. **Check it worked.** The agent can also run these for you (they only read):

   ```powershell
   terraform -chdir=infra plan          # expect: "No changes."
   aws s3api get-bucket-versioning --bucket pm25-forecast-data-65bc08     # "Status": "Enabled"
   aws s3api get-public-access-block --bucket pm25-forecast-data-65bc08   # all four true
   ```

`tfplan` is gitignored too (a saved plan can hold sensitive values). Delete it after the apply.

## Changing things later

Edit the `.tf` files on a branch. CI runs the format, validation and mock tests. Then run
`plan` and `apply` as in steps 1, 3, 4 and 5, and check that `plan` shows "No changes" afterwards.

**Since T9, build the watchdog's zip before every `plan`:** `uv run python -m airwatch.watchdog.build`.
Terraform hashes `infra/build/watchdog.zip`, and a fresh checkout doesn't have it. The build is
reproducible, so an unchanged handler and lock give the same zip and no change in the plan.
