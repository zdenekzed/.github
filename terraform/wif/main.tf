data "google_project" "main" {
  project_id = var.project_id
}

locals {
  scoped_repos = [for r in var.allowed_repositories : "${var.github_owner}/${r}"]

  # Security boundary: without attribute_condition, any GitHub repository could exchange a token.
  attribute_condition = length(local.scoped_repos) == 0 ? (
    "assertion.repository_owner == '${var.github_owner}'"
    ) : (
    "assertion.repository_owner == '${var.github_owner}' && assertion.repository in [${join(", ", [for r in local.scoped_repos : "'${r}'"])}]"
  )

  pool_resource_prefix = "principalSet://iam.googleapis.com/projects/${data.google_project.main.number}/locations/global/workloadIdentityPools/${var.pool_id}"

  # Either one owner-wide principalSet or one principalSet per explicitly allowlisted repo.
  principal_sets = length(local.scoped_repos) == 0 ? toset([
    "${local.pool_resource_prefix}/attribute.repository_owner/${var.github_owner}"
    ]) : toset([
    for r in local.scoped_repos : "${local.pool_resource_prefix}/attribute.repository/${r}"
  ])

  services = toset([
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "aiplatform.googleapis.com",
  ])
}

resource "google_project_service" "main" {
  for_each = var.enable_services ? local.services : toset([])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_iam_workload_identity_pool" "main" {
  count = var.create_pool ? 1 : 0

  project                   = var.project_id
  workload_identity_pool_id = var.pool_id
  display_name              = "GitHub Actions"
  description               = "Keyless OIDC federation for ${var.github_owner}/* GitHub Actions workflows."

  depends_on = [google_project_service.main]
}

resource "google_iam_workload_identity_pool_provider" "main" {
  project                            = var.project_id
  workload_identity_pool_id          = var.create_pool ? google_iam_workload_identity_pool.main[0].workload_identity_pool_id : var.pool_id
  workload_identity_pool_provider_id = var.provider_id
  display_name                       = "GitHub OIDC (${var.github_owner})"

  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
    "attribute.ref"              = "assertion.ref"
  }

  attribute_condition = local.attribute_condition

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "main" {
  project      = var.project_id
  account_id   = var.sa_name
  display_name = "Antigravity code review (${var.github_owner}/*)"
  description  = "Keyless identity for GitHub Actions AI code review on Vertex AI. Holds only roles/aiplatform.user."

  depends_on = [google_project_service.main]
}

# Least privilege: additive _member so existing IAM bindings are never clobbered.
resource "google_project_iam_member" "aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.main.email}"
}

resource "google_service_account_iam_member" "workload_identity_user" {
  for_each = local.principal_sets

  service_account_id = google_service_account.main.name
  role               = "roles/iam.workloadIdentityUser"
  member             = each.value

  depends_on = [google_iam_workload_identity_pool_provider.main]
}
