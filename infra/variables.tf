variable "region" {
  description = "AWS region for every resource (D-018)."
  type        = string
  default     = "us-east-1"
}

variable "name_suffix" {
  description = "Suffix that makes the global bucket names unique (same as the T0c state bucket)."
  type        = string
  default     = "65bc08"

  validation {
    condition     = can(regex("^[a-z0-9]{4,12}$", var.name_suffix))
    error_message = "name_suffix must be 4-12 lower-case letters or digits."
  }
}

variable "pages_origin" {
  description = "The GitHub Pages origin allowed to fetch the public JSON (CORS)."
  type        = string
  default     = "https://siddharthps.github.io"

  validation {
    condition     = can(regex("^https://[a-z0-9.-]+$", var.pages_origin))
    error_message = "pages_origin must be an https origin with no path or trailing slash."
  }
}

variable "alert_email" {
  description = "Owner's email for alerts (SNS, T9). Set in the gitignored terraform.tfvars only."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must be an email address."
  }
}

variable "raw_noncurrent_days" {
  description = "Days to keep a superseded version of a raw/ download before it expires."
  type        = number
  default     = 30
}

variable "prefect_account_id" {
  description = "Prefect Cloud account ID (a UUID) that the Prefect run role trusts (D-040)."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.prefect_account_id))
    error_message = "prefect_account_id must be a lower-case UUID (Prefect Cloud → account settings)."
  }
}
