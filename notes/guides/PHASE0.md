# Phase 0: Owner setup guides (T0a–T0d)

Written 2026-11-18. Work through these in any order; each takes 15–40 minutes. Tick the boxes in
[tasks/todo.md](../../tasks/todo.md) as you go.

**Golden rule for every step:** never paste a key, password or token into the chat, a file in the
repo, or a screenshot. Keep them in a password manager. When I need to know a credential works, I
ask the service who it belongs to; I never look at the value.

---

## T0a: AirNow API account (about 15 min)

1. Go to **<https://docs.airnowapi.org>**, choose **Log In**, then the option to **request a new
   account**. Use your own email. The account is free.
2. Confirm the email, log in, and find your **API key** (on your account page). Save it in your
   password manager as "AirNow API key".
3. While logged in, open these pages and **copy the facts below into a short note** (in your words
   or as quotes, but not the key). Paste that note to me, and I'll record it in D-004.
   - Web services → **"By hourly data geographic bounding box"** docs → the **rate limit**
     (requests per hour) and **how far back** it can return data.
   - The same for **"By daily data geographic bounding box"**.
   - **File Products** → which hourly or daily files exist and **how far back** they go.
   - **Data Use Guidelines** (a PDF linked from the FAQ) → may derived values (daily means,
     forecast errors) be shown on a public website? What attribution wording is required? Any
     "preliminary data" disclaimer?
4. Done when: the key is saved, and I have your note.

## T0b: Prefect Cloud (about 15 min)

1. Go to **<https://app.prefect.cloud>** and sign up on the **Hobby (free)** plan. If it asks for a
   credit card, stop and tell me; the pricing page doesn't say it needs one.
2. Create a **workspace** named `pm25-forecast`.
3. **Work Pools → + (create) → "Prefect Managed"**, named `managed-pool`. This is where the daily
   run will execute.
4. **Profile (your avatar) → API Keys → Create**, named `pm25-forecast-cli`. **Set an expiry**
   (for example 90 days) and note the date. Save the key in your password manager.
5. Tell me the **expiry date** (not the key). I'll add it to `notes/TOKENS.md`. We'll log the CLI
   in during T8, together.

## T0c: AWS clean-up, your own login, billing alarm (about 40 min)

Your v1 `.env` holds long-lived AWS access keys from 2025. The aim is to replace them with a
short-lived login for you and narrow, purpose-built access for the pipeline (created later by
Terraform).

### 1. A billing alarm first (5 min)

AWS console → **Billing and Cost Management → Budgets → Create budget → "Use a template" → Monthly
cost budget**. Amount **$5.00**, with your email as recipient. Create it. This is success criterion
7's safety net.

### 2. A short-lived login for yourself (20 min)

The industry-standard way is **IAM Identity Center** (free):

1. Console → **IAM Identity Center → Enable** (choose the region **us-east-1** if asked).
2. **Users → Add user**: yourself.
3. **Permission sets → Create → Predefined → `AdministratorAccess`** (this is for *you* setting
   things up; the pipeline gets far narrower rights later).
4. **AWS accounts →** select your account → **Assign users** → you → that permission set.
5. Accept the invitation email and set a password plus MFA.
6. On this PC, in a terminal: `aws configure sso`, using the **start URL** shown in Identity
   Center, region `us-east-1`, profile name `pm25`.
7. Test: `aws sts get-caller-identity --profile pm25`. It should show your SSO role. Tell me it
   worked (no need to paste the output).

### 3. Retire the v1 keys (10 min, only after step 2 works)

1. Console → **IAM → Users →** the user whose key is in the v1 `.env` → **Security credentials →
   Access keys**.
2. Check **"Last used"**. If anything other than the old project used it recently, stop and tell
   me.
3. **Deactivate** the key (not delete yet). After a week with nothing broken, **delete** it.
4. Tell me when it's deactivated. I'll then stop using the old `default` profile entirely.

### 4. Terraform and the state bucket (I can do these for you)

- **Install Terraform v1.17.2:** `winget` isn't available here, so it's the official zip from
  `releases.hashicorp.com`, with its SHA256 checksum verified, placed in `~/.local/bin` (already
  on your PATH). I can do this with your go-ahead.
- **State bucket:** once your `pm25` profile works, I'll give you three commands to create one
  private, versioned bucket for Terraform's state. Everything else will come from Terraform in
  T3b.
- **v1 buckets:** with your `pm25` profile, I'll list the old buckets' names and sizes (a read-only
  command) so we can decide their fate in T30.

## T0d: The GitHub repo (I do this, after your go-ahead)

I'll run, as `siddharthps`:

- `gh repo create siddharthps/pm25-forecast --public` with the description below
- Branch protection on `main`: PR required, CI must pass, no force pushes
- Secret scanning + push protection, and Dependabot alerts
- GitHub Pages source: GitHub Actions

Proposed description: *"Live next-day PM2.5 forecasts for a US metro, with an honest public track
record. Prefect · MLflow · Evidently · AWS · Terraform."*
