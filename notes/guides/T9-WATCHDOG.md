# T9: Setting up the watchdog (owner, about 40 min)

Written 2026-11-20 for #16 (D-023: you run each new tool the first time). The design is in
[D-041](../DECISIONS.md). Do these **after the T9 PR is merged**, from an up-to-date `main`.

Commands are bash. In Claude Code, type each one after `!` so its output lands in the chat. Run
every command from the repo folder (`cd ~/code/pm25-forecast`). On Windows, start every `prefect`
command with `PYTHONUTF8=1` (T8 guide).

**Golden rule:** the new Prefect key goes **only** into the AWS console box in step 2. Never into
the chat, a file or a command.

---

## 1. Create the watchdog's Prefect key (3 min, in the browser)

1. In Prefect Cloud: your profile (bottom left) → **API Keys** → **Create API key**.
2. Name: `pm25-forecast-watchdog`. Expiration: **2027-02-28**, the same day as the CLI key, so
   one renewal covers both (TOKENS.md).
3. Copy the key, and keep the tab open for step 2. Don't save it in the password manager: SSM is
   its only home, and renewing means making a new one.

## 2. Put the key in AWS Parameter Store (3 min, in the browser)

1. Open the AWS console, region **us-east-1 (N. Virginia)** → **Systems Manager** →
   **Parameter Store** → **Create parameter**.
2. Name: `/pm25-forecast/prefect-api-key` (exactly, with the leading slash).
3. Tier **Standard**, type **SecureString**, KMS key **`alias/aws/ssm`** (the default).
4. Value: paste the key. **Create parameter**. Close the Prefect tab.

Terraform never sees this value: it only knows the parameter's name.

## 3. Add two IDs to `infra/terraform.tfvars` (2 min)

Neither is secret, but like the account ID they only go in the gitignored tfvars.

- **Workspace ID:** in the Prefect URL, the part after `/workspace/`.
- **Deployment ID:**

  ```bash
  PYTHONUTF8=1 uv run prefect deployment inspect daily-forecast/daily-forecast
  ```

  Copy the top-level `'id'`.

Add, with your values:

```hcl
prefect_workspace_id  = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
prefect_deployment_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

## 4. Build the Lambda's zip (1 min)

```bash
uv run python -m airwatch.watchdog.build
```

It prints `infra/build/watchdog.zip`, its size (a few MB) and a SHA-256. Running it again gives
the same SHA-256.

## 5. Plan and apply (5 min)

```bash
aws sso login --profile pm25
AWS_PROFILE=pm25 terraform -chdir=infra plan -out=tfplan
```

Check that the last line says **`Plan: 13 to add, 0 to change, 0 to destroy.`** The 13 are:

- `aws_sns_topic.alerts` and `aws_sns_topic_subscription.owner_email`;
- `aws_iam_role.watchdog` and `aws_iam_role_policy.watchdog`;
- `aws_cloudwatch_log_group.watchdog`, `aws_lambda_function.watchdog` and
  `aws_lambda_function_event_invoke_config.watchdog`;
- `aws_cloudwatch_metric_alarm.watchdog_errors`;
- `aws_iam_role.scheduler` and `aws_iam_role_policy.scheduler`;
- `aws_scheduler_schedule_group.watchdog`, and `aws_scheduler_schedule.watchdog["retry"]` and
  `["verify"]`.

Stop and ask if anything says *change* or *destroy*. Then:

```bash
AWS_PROFILE=pm25 terraform -chdir=infra apply tfplan
rm infra/tfplan
AWS_PROFILE=pm25 terraform -chdir=infra plan
```

The second `plan` should say **No changes**.

## 6. Confirm the email subscription (2 min, within 48 hours)

AWS emails "AWS Notification - Subscription Confirmation" to your alert address. Click **Confirm
subscription**. Until you do, no alert reaches you, and AWS deletes an unconfirmed subscription
after 48 hours (then re-run `apply` to get a new link).

## 7. The drill (10 min)

Each step invokes the Lambda by hand with a test event marked `"drill": true`. A drill uses its
own Prefect idempotency key and says DRILL in its emails. A drill retry must target a day whose
06:00 forecast hasn't been issued, so the run it starts stops as too early and can't publish.

In the events below, replace **TODAY** and **TOMORROW** with the real dates (`YYYY-MM-DD`,
Chicago). `14:00Z` and `15:00Z` are 08:00 and 09:00 Chicago in winter.

The invoke command (each step changes only the `--payload`). `MSYS_NO_PATHCONV=1` stops Git
Bash from rewriting an argument that starts with `/` into a Windows path (2026-11-20: it hid
the SSM parameter from a name filter):

```bash
AWS_PROFILE=pm25 MSYS_NO_PATHCONV=1 aws lambda invoke --function-name pm25-forecast-watchdog \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode":"verify","scheduled_time":"TODAYT15:00:00Z","drill":true}' \
  infra/build/drill-out.json && cat infra/build/drill-out.json
```

1. **Record present → nothing.** The payload above, after today's 06:00 run. Expect
   `"record": "present"`, and **no email**.
2. **Record missing at 09:00 → one email.**
   `{"mode":"verify","scheduled_time":"TOMORROWT15:00:00Z","drill":true}`. Expect
   `"record": "missing"` and an email "DRILL forecast for … still missing". Nothing is started.
3. **Record missing at 08:00 → one Prefect run and one email.**
   `{"mode":"retry","scheduled_time":"TOMORROWT14:00:00Z","drill":true}`. Expect
   `"retry": "started"` and an email "DRILL forecast for … missed, retry started (run name)".
   In Prefect Cloud, that run (tagged `watchdog`, `drill`) ends **Failed** with "issue time … not
   reached". That's the intended safe stop: it wrote no record and no public file, only its
   compute minutes.
4. **The same call again → no second run.** Repeat step 3. Expect `"retry": "already started"`
   and an email saying so. Prefect returned the first run instead of making a new one.
5. **Logs:** tell me, and I'll read them, or:

   ```bash
   AWS_PROFILE=pm25 MSYS_NO_PATHCONV=1 aws logs tail /aws/lambda/pm25-forecast-watchdog --since 30m
   ```

   Expect one `watchdog {...}` line per invoke, and no key.

Then `rm infra/build/drill-out.json`.

## 8. From then on

**After any change to the handler or `uv.lock`:** rebuild the zip (step 4), then `plan`. It
shows 1 change, the Lambda's code. Apply it as in step 5.

Every day at 08:00 and 09:00 Chicago the watchdog checks the record. On a normal day it's silent.
You get an email only when the 06:00 run was missed (and what the retry did), when the record is
still missing at 09:00, once a month above 300 Prefect minutes, or when the watchdog itself fails.

---

**If something fails:** copy me the error's first lines, never a key. To undo everything, run
`terraform -chdir=infra destroy` with `-target` on the 13 resources, and delete the parameter in
the console; ask me first.
