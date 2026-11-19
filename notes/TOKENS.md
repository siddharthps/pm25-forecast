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
| Prefect Cloud API key `pm25-forecast-cli` | Prefect CLI login and deployments (workspace `pm25-forecast`, Hobby plan) | Owner's password manager; later a Prefect CLI profile on this PC (T8) | **Expires 2027-02-28**. Renew a week before (reminder: 2027-02-21) | Prefect Cloud → profile → API Keys → create a new key, `prefect cloud login`, then delete the old key | 2026-11-18 |

To add as they're created: pipeline AWS access (D-024, T8), the
watchdog's Prefect key in SSM (T9), the GitHub fine-grained token for flag issues (T24).
