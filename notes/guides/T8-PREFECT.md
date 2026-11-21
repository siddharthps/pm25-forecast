# T8: The first Prefect deploy (owner, about 30 min)

Written 2026-11-20 for #15 (D-023: you run each new tool the first time). The design is in
[D-040](../DECISIONS.md). Do these **after the T8 PR is merged**: every run clones `main`, so the
flow has to be there first.

Commands are bash. In Claude Code, type each one after `!` so its output lands in the chat. Run
every command from the repo folder (`cd ~/code/pm25-forecast`).

**On Windows, start every `prefect` command with `PYTHONUTF8=1`.** The Prefect CLI prints
characters the Windows console's default encoding (cp1252) can't show, and crashes on them.
Sometimes it crashes after the action has already happened (2026-11-20: the run was created).

**Golden rule:** never paste the Prefect API key into the chat or a file. Paste it only into the
login prompt in step 3.

---

## 1. Find your Prefect account ID (2 min)

1. Open <https://app.prefect.cloud> and log in.
2. Look at the address bar. It reads
   `app.prefect.cloud/account/<ACCOUNT-ID>/workspace/<WORKSPACE-ID>/…`.
3. Copy the part after `/account/`. It's a UUID (8-4-4-4-12 letters and digits). It isn't a
   secret, but it only goes in the gitignored `infra/terraform.tfvars`.
4. Add this line to `infra/terraform.tfvars`, with your value:

   ```hcl
   prefect_account_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
   ```

## 2. Create the keyless AWS role (Terraform, 5 min)

```bash
aws sso login --profile pm25
AWS_PROFILE=pm25 terraform -chdir=infra plan -out=tfplan
```

Check that the plan's last line says **`Plan: 3 to add, 0 to change, 0 to destroy.`** The three
are:

- `aws_iam_openid_connect_provider.prefect`;
- `aws_iam_role.prefect_run`;
- `aws_iam_role_policy_attachment.prefect_run_pipeline`.

Stop and ask if anything says *change* or *destroy*. Then:

```bash
AWS_PROFILE=pm25 terraform -chdir=infra apply tfplan
AWS_PROFILE=pm25 terraform -chdir=infra output prefect_run_role_arn
rm infra/tfplan
```

Keep the role ARN (`arn:aws:iam::…:role/pm25-forecast-prefect-run`) for step 5.

## 3. Log the Prefect CLI in (2 min)

```bash
PYTHONUTF8=1 uv run prefect cloud login
```

Choose **Paste an API key**, then paste the `pm25-forecast-cli` key from your password manager
(TOKENS.md). Pick the workspace if asked (ours is `siddharthpm/default`). Check it with:

```bash
PYTHONUTF8=1 uv run prefect cloud workspace ls
```

## 4. Create the managed work pool (2 min)

```bash
PYTHONUTF8=1 uv run prefect work-pool create managed-pool --type prefect:managed
PYTHONUTF8=1 uv run prefect work-pool inspect managed-pool
```

If `create` says the pool **already exists**, that's fine: a Prefect Cloud workspace can come with
one (ours did). Go on to `inspect`.

In the `inspect` output, under `base_job_template` → `variables` → `properties`, check that
**`image`** and **`env`** are listed. The deployment sets both. Paste me that `properties` part
(it holds no secrets) so I can record it.

## 5. Turn on keyless AWS for the pool (3 min, in the browser)

1. In Prefect Cloud: **Work Pools → managed-pool → ⋯ → Edit**.
2. Open **Federated Identity**. Set **AWS Role ARN** to the ARN from step 2, and **AWS Region
   Name** to `us-east-1`.
3. Save.

## 6. Deploy (2 min)

```bash
PYTHONUTF8=1 uv run prefect --no-prompt deploy --all
PYTHONUTF8=1 uv run prefect deployment ls
```

Expect one deployment, `daily-forecast/daily-forecast`. In the UI, its **Schedules** should show
`0 6 * * *` in America/Chicago, active.

## 7. A manual dry run (5 min)

A manual run uses the deployment's parameters, so it's a dry run: no record, no public file.

```bash
PYTHONUTF8=1 uv run prefect deployment run daily-forecast/daily-forecast
```

It prints the run's name and ID, then returns. Don't add `--watch`, which crashed on Windows;
tell me the run's name and I'll follow it. Expect the run to end **Completed**, with log lines
like:

- `2026-11-21: dry run, 10 monitor(s) forecast; nothing written`;
- `compute: this run about N min; this month N of 500 free min (alert line 300)`.

If tomorrow's record already exists, the run reuses it and doesn't fetch AirNow. To test the
download too, do a second dry run for a past day that has no record:

```bash
PYTHONUTF8=1 uv run prefect deployment run daily-forecast/daily-forecast --param target_day=2026-11-19
```

Then tell me, and I'll check, using reads only:

- the S3 ledger entry under `reports/compute/`;
- that no new record or public file appeared;
- that the run's logs show no key or token.

Also note the run's minutes on Prefect's **usage** page (Settings → Usage, or similar), so we can
compare it with the ledger's estimate.

## 8. The first scheduled run

The next 06:00 Chicago run publishes the next day's forecast on its own. The morning after, I'll
check the new record in S3 and the live page.

---

**If something fails:** copy me the error's first lines, never a key. A failed deploy creates
nothing that costs money. To undo the AWS part, run `terraform -chdir=infra destroy` with
`-target` on the three resources; ask me first.
