terraform {
  required_version = ">= 1.6.0"

  # Partial GCS backend — pass bucket & prefix via gitignored backend.hcl:
  #   terraform init -backend-config=backend.hcl
  backend "gcs" {}

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0.0"
    }
  }
}

provider "google" {
  project = var.project_id
}
