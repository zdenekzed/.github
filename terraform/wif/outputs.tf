output "gcp_project" {
  description = "Value for GitHub Actions variable GCP_PROJECT."
  value       = var.project_id
}

output "wif_provider" {
  description = "Value for GitHub Actions variable WIF_PROVIDER."
  value       = google_iam_workload_identity_pool_provider.main.name
}

output "wif_service_account" {
  description = "Value for GitHub Actions variable WIF_SERVICE_ACCOUNT."
  value       = google_service_account.main.email
}

output "attribute_condition" {
  description = "Active OIDC attribute condition enforced by GCP."
  value       = local.attribute_condition
}

output "sync_hint" {
  description = "Command to propagate these outputs to GitHub Actions repository variables."
  value       = "./scripts/sync-github-vars.sh"
}
