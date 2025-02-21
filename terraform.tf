terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 4.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

#############################
# Variables
#############################

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP region for Cloud Run service"
  type        = string
  default     = "europe-west4"
}

variable "repo_owner" {
  description = "GitHub repository owner"
  type        = string
}

variable "repo_name" {
  description = "GitHub repository name"
  type        = string
}

variable "send_project_breakdown" {
  description = "Non-secret variable: true/false to include project breakdown table in main message"
  type        = string
  default     = "true"
}

variable "send_thread_details" {
  description = "Non-secret variable: true/false to send detailed thread messages for each project"
  type        = string
  default     = "true"
}

# Provide secret values via variables or other secure means
variable "slack_api_token_value" {
  description = "The Slack Bot API token"
  type        = string
}

variable "slack_channel_id_value" {
  description = "The Slack Channel ID (or user ID) where messages will be sent"
  type        = string
}

variable "billing_sa_file_path" {
  description = "Path to the Google Service Account JSON file for billing"
  type        = string
}

# Service account email to be used for OIDC authentication by Cloud Scheduler
variable "scheduler_service_account_email" {
  description = "Email of the service account used by Cloud Scheduler for OIDC authentication"
  type        = string
}

#############################
# Secret Manager Resources
#############################

resource "google_secret_manager_secret" "slack_api_token" {
  secret_id = "SLACK_API_TOKEN"
  replication {
    automatic = true
  }
}

resource "google_secret_manager_secret_version" "slack_api_token_version" {
  secret      = google_secret_manager_secret.slack_api_token.id
  secret_data = var.slack_api_token_value
}

resource "google_secret_manager_secret" "slack_channel_id" {
  secret_id = "SLACK_CHANNEL_ID"
  replication {
    automatic = true
  }
}

resource "google_secret_manager_secret_version" "slack_channel_id_version" {
  secret      = google_secret_manager_secret.slack_channel_id.id
  secret_data = var.slack_channel_id_value
}

resource "google_secret_manager_secret" "billing_sa" {
  secret_id = "billing-sa-json"
  replication {
    automatic = true
  }
}

resource "google_secret_manager_secret_version" "billing_sa_version" {
  secret      = google_secret_manager_secret.billing_sa.id
  secret_data = file(var.billing_sa_file_path)
}

#############################
# Cloud Run Service (V2)
#############################

resource "google_cloud_run_v2_service" "service" {
  name     = "gcp-billing-reporter"
  location = var.region

  template {
    containers {
      image = "ghcr.io/${var.repo_owner}/${var.repo_name}:latest"

      # Non-secret environment variables
      env {
        name  = "SEND_PROJECT_BREAKDOWN"
        value = var.send_project_breakdown
      }
      env {
        name  = "SEND_THREAD_DETAILS"
        value = var.send_thread_details
      }

      # Secret environment variables from Secret Manager
      env {
        name = "SLACK_API_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.slack_api_token.secret_id
            version = google_secret_manager_secret_version.slack_api_token_version.secret_data_version
          }
        }
      }
      env {
        name = "SLACK_CHANNEL_ID"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.slack_channel_id.secret_id
            version = google_secret_manager_secret_version.slack_channel_id_version.secret_data_version
          }
        }
      }

      # Mount the service account file via a volume mount
      volume_mounts {
        name       = "billing-sa-volume"
        mount_path = "/var/secrets/billing-sa"
        read_only  = true
      }
    }

    volumes {
      name = "billing-sa-volume"
      secret {
        secret = google_secret_manager_secret.billing_sa.secret_id

        items {
          key  = "billing-sa.json"
          path = "billing-sa.json"
        }
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }
}

#############################
# (Optional) IAM Binding
#############################

resource "google_cloud_run_v2_service_iam_member" "invoker" {
  service  = google_cloud_run_v2_service.service.name
  location = google_cloud_run_v2_service.service.location
  role     = "roles/run.invoker"
  member   = "allUsers"  # Adjust as necessary (e.g., a specific service account)
}

#############################
# Cloud Scheduler Job
#############################

resource "google_cloud_scheduler_job" "daily_job" {
  name        = "gcp-billing-reporter-scheduler"
  description = "Trigger the GCP Billing Reporter Cloud Run service once a day"
  schedule    = "0 9 * * *"  # Daily at 09:00 UTC
  time_zone   = "UTC"

  http_target {
    http_method = "GET"
    uri         = google_cloud_run_v2_service.service.uri

    oidc_token {
      service_account_email = var.scheduler_service_account_email
    }
  }
}
