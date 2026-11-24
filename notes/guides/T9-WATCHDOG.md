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

Then check what each schedule will really send. The drill (step 7) invokes the Lambda
directly, so it can't test this step:

```bash
AWS_PROFILE=pm25 MSYS_NO_PATHCONV=1 aws scheduler get-schedule --group-name pm25-forecast \
  --name pm25-forecast-watchdog-retry --query Target.Input --output text
```

Expect `{"mode":"retry","scheduled_time":"<aws.scheduler.scheduled-time>"}` with the
**angle brackets as they are**. If it shows `\u003c` instead, the scheduler would send the
placeholder itself instead of the time. That happened on 2026-11-21. Repeat with
`pm25-forecast-watchdog-verify`.

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

## 7b. One test through the real scheduler (5 min)

The drill above calls the Lambda directly, so it skips the scheduler. On 2026-11-21 the
scheduler turned out to send its placeholder unsubstituted (#75), and only the real 08:00
check showed it. So after any change to the schedules, create a **one-time** schedule a few
minutes ahead. It fires once, runs a drill verify through the real scheduler, then deletes
itself.

Replace **TODAY** with today's date and **HH:MM** with a time about 10 minutes away (Chicago
time; AWS refuses one in the past):

```bash
AWS_PROFILE=pm25 MSYS_NO_PATHCONV=1 aws scheduler create-schedule --region us-east-1 \
  --name pm25-forecast-watchdog-e2e --group-name pm25-forecast \
  --schedule-expression "at(TODAYTHH:MM:00)" --schedule-expression-timezone America/Chicago \
  --flexible-time-window Mode=OFF --action-after-completion DELETE \
  --target '{"Arn":"arn:aws:lambda:us-east-1:<ACCOUNT>:function:pm25-forecast-watchdog","RoleArn":"arn:aws:iam::<ACCOUNT>:role/pm25-forecast-watchdog-scheduler","Input":"{\"mode\":\"verify\",\"scheduled_time\":\"<aws.scheduler.scheduled-time>\",\"drill\":true}"}'
```

`<ACCOUNT>` is the AWS account ID (it appears in `terraform output alerts_topic_arn`).

**Expect:** no email. A minute after the time, the watchdog's log has one line,
`watchdog {"mode": "verify", "target_day": "<tomorrow>", "record": "present"}`, which only a
substituted time can produce. `aws scheduler list-schedules --group-name pm25-forecast` lists
only the two real schedules again. A DRILL email instead means the substitution failed, and
the email names what the watchdog received.

## 8. From then on

**After any change to the handler or `uv.lock`:** rebuild the zip (step 4), then `plan`. It
shows 1 change, the Lambda's code. Apply it as in step 5.

Every day at 08:00 and 09:00 Chicago the watchdog checks the record. On a normal day it's silent.
You get an email only when the 06:00 run was missed (and what the retry did), when the record is
still missing at 09:00, once a month above 300 Prefect minutes, or when the watchdog itself fails.

## 9. The weekly lock run (#113, D-058; owner, about 30 min)

From #113 on, the watchdog also starts `uv-lock-upgrade.yml` on Mondays at 08:00 Chicago and
checks the run at 09:00, and the workflow has no GitHub cron. It needs a GitHub token in SSM.
Do this **after #113's PR is merged**, from an up-to-date `main`. Until the apply, nothing starts
the lock run (at most one missed Monday).

**Golden rule, as for the Prefect key:** the token goes **only** into the AWS console box.

1. **Create the token** (5 min, in the browser). GitHub → Settings → Developer settings →
   Personal access tokens → **Fine-grained tokens** → **Generate new token**.
   - Name `pm25-forecast-watchdog-lock`. Expiration: **custom, 2027-02-28**, the Prefect keys'
     day, so one renewal covers all three (TOKENS.md).
   - Repository access: **Only select repositories** → `siddharthps/pm25-forecast`.
   - Repository permissions: **Actions: Read and write** (Metadata: read is added for you).
     Nothing else.
   - **Generate**, copy it, keep the tab open.
2. **Put it in Parameter Store** (3 min): as step 2, with Name `/pm25-forecast/github-lock-token`,
   SecureString, `alias/aws/ssm`. Paste, **Create parameter**, close the GitHub tab.
3. **Rebuild the zip, plan and apply** (5 min): steps 4 and 5. The plan shows 3 changes: the
   Lambda (its code and three new settings, `GITHUB_TOKEN_PARAMETER`, `GITHUB_REPO`,
   `LOCK_WORKFLOW`), the watchdog role's policy (the token's parameter, and
   `reports/lock-runs/`) and the role's description. Nothing is destroyed (applied 2026-11-24).
4. **The drill** (10 min). Replace **MONDAY** with the coming Monday (`YYYY-MM-DD`). In winter
   08:00 and 09:00 Chicago are `14:00Z` and `15:00Z`. A drill keeps its own marker, so it never
   uses up that Monday's real run.
   1. **08:00 → one real lock run.**
      `{"mode":"retry","scheduled_time":"MONDAYT14:00:00Z","drill":true}`. Expect
      `"lock": "dispatched"` and a `lock_run_id`. In GitHub → Actions, a **uv lock upgrade** run
      starts; if the lock changes, it opens or refreshes the lock PR with CI on it (#43's last
      box). The forecast half also runs as a drill for Monday's target day: as in step 7.3, one
      Prefect run that stops as too early, and its DRILL email.
   2. **The same call again → nothing.** Expect `"lock": "already dispatched"` and no new run.
   3. **09:00 with the run finished → silent for the lock.** Once the run has finished:
      `{"mode":"verify","scheduled_time":"MONDAYT15:00:00Z","drill":true}`. Expect
      `"lock": "succeeded"` and no lock email. (The forecast half emails "DRILL forecast for …
      still missing", because Monday's forecast doesn't exist yet. That one is expected.)
   4. **09:00 with no run → one email.** The same verify for the Monday after (MONDAY + 7 days).
      Expect `"lock": "missing"` and an email "DRILL weekly lock run missing".
5. **The first real Monday:** silent if all is well. At 09:00 a failed, cancelled or unfinished
   run emails its state and link; a missing run or a refused dispatch emails how to start it by
   hand (`gh workflow run uv-lock-upgrade.yml --ref main`).

---

**"Error acquiring the state lock"** (412 PreconditionFailed): an earlier `apply` stopped and
left its lock (2026-11-24). First check that nothing else is running (no `terraform` process)
and that the change didn't land, then release that one lock by the ID the error prints, and
apply again:

```bash
AWS_PROFILE=pm25 terraform -chdir=infra force-unlock -force <Lock Info ID>
```

**If something fails:** copy me the error's first lines, never a key. To undo everything, run
`terraform -chdir=infra destroy` with `-target` on the 13 resources, and delete the parameter in
the console; ask me first.
