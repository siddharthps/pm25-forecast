# Credentials register

One row per credential this project depends on: what it is, where it lives, when it expires and
how to renew it. **Never the value.** Verify a credential by asking its service who it belongs to,
never by printing it. Dates are America/Chicago.

| Credential | Purpose | Stored in | Expires / rotates | How to renew | Added |
| --- | --- | --- | --- | --- | --- |
| AWS root account | Account-level tasks only (billing, Identity Center) | Owner's password manager; MFA on; **no access keys** | n/a | n/a | 2026-11-18 |
| AWS IAM Identity Center user `siddharthps-pm25` (`AdministratorAccess`) | Owner's day-to-day console and CLI work (profile `pm25`, us-east-1) | Password in the owner's password manager; MFA on; CLI uses short-lived SSO tokens | Each CLI session lasts **8 hours** (permission-set session duration) | `aws sso login --profile pm25` | 2026-11-18 |
| AirNow API key | The AirNow web services (500 requests/hour, D-004). **Not used by the code yet:** T5 reads AirNow's public hourly files, which need no key | Owner's password manager and the repo `.env` (`AIRNOW_API_KEY`; presence checked 2026-11-19). Later SSM Parameter Store, written by the owner via the CLI so the value never enters Terraform state | No expiry stated in the AirNow docs read 2026-11-18 | Re-issue from the AirNow account page | 2026-11-18 |
| AQS Data Mart API key + registered email | Validated history: the city check (T4) and the bulk download (T13) | Owner's password manager and the repo `.env` (`AQS_EMAIL`, `AQS_API_KEY`; presence checked 2026-11-19). The email is personal data, so it's treated as a secret (`SecretStr`) | No expiry stated in the AQS API docs (read 2026-11-18). A reset issues a new key by email | `https://aqs.epa.gov/data/api/signup?email=<your email>` again (a reset key arrives by email); update `.env` | 2026-11-19 |
| v1 IAM user `air-quality-mlops-user`, key …XZ53 (2025) | **Retired**: deactivated 2026-11-18 (last used 2025-08-04) | The old repo's `.env` and the CLI `default` profile, both now dead | **Delete the key and the user on 2026-11-25** if nothing broke | n/a | 2026-11-18 |
| Prefect Cloud API key `pm25-forecast-cli` | Prefect CLI login and deployments (workspace `siddharthpm/default`, the Hobby plan's only one) | Owner's password manager, and the Prefect CLI profile on this PC (`prefect cloud login`, 2026-11-20) | **Expires 2027-02-28**. Renew a week before (reminder: 2027-02-21) | Prefect Cloud → profile → API Keys → create a new key, `prefect cloud login`, then delete the old key | 2026-11-18 |
| Prefect Cloud API key `pm25-forecast-watchdog` | The watchdog Lambda starts the daily deployment when the 06:00 run is missed (D-041). A user key: the Hobby plan has no service accounts | AWS SSM Parameter Store, SecureString `/pm25-forecast/prefect-api-key` (us-east-1), created by the owner in the console, so the value never enters Terraform state. Not kept anywhere else | **Expires 2027-02-28**, the same day as the CLI key, so one renewal covers both (reminder: 2027-02-21) | Prefect Cloud → profile → API Keys → create a new key; Parameter Store → the parameter → Edit → paste the new value; then delete the old key. The next 08:00 check uses it | To create (T9 guide, step 1) |

**The Prefect run holds no credential (D-040).** Its AWS access is the role `pm25-forecast-prefect-run`,
assumed through Prefect Cloud's OIDC provider, with temporary credentials that Prefect injects. No key
to store, expire or rotate. AirNow's hourly files need no key.

To add as they're created: the GitHub fine-grained token for flag issues (T24).
