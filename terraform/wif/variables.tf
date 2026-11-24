variable "project_id" {
  type        = string
  description = "Personal GCP project ID (with billing enabled) hosting the WIF pool and billed for Vertex AI inference."
}

variable "github_owner" {
  type        = string
  description = "GitHub account/owner whose repositories are permitted to exchange OIDC tokens."
  default     = "zdenekzed"
}

variable "allowed_repositories" {
  type        = list(string)
  description = <<-EOT
    Optional allowlist of repository names (without owner prefix, e.g. ["gym-jht", "reality-scraper"]).
    When empty (default), any non-fork repository owned by var.github_owner is allowed via
    `assertion.repository_owner == '<github_owner>'`.
    When non-empty, both the OIDC attribute_condition and the IAM principalSet bindings are narrowed
    to those exact repositories.
  EOT
  default     = []
}

variable "create_pool" {
  type        = bool
  description = "Create a new Workload Identity Pool (true) or attach the OIDC provider to an existing pool named var.pool_id (false)."
  default     = true
}

variable "pool_id" {
  type        = string
  description = "Workload Identity Pool ID (4-32 chars, lowercase letters, digits, hyphens)."
  default     = "github-actions"

  validation {
    condition     = can(regex("^[a-z0-9-]{4,32}$", var.pool_id))
    error_message = "pool_id must be 4-32 characters of lowercase letters, digits, and hyphens."
  }
}

variable "provider_id" {
  type        = string
  description = "OIDC Provider ID inside the pool (4-32 chars, lowercase letters, digits, hyphens)."
  default     = "github-oidc-review"

  validation {
    condition     = can(regex("^[a-z0-9-]{4,32}$", var.provider_id))
    error_message = "provider_id must be 4-32 characters of lowercase letters, digits, and hyphens."
  }
}

variable "sa_name" {
  type        = string
  description = "Service account ID (before @) impersonated by the AI code review workflow."
  default     = "agy-code-review"

  validation {
    condition     = can(regex("^[a-z]([a-z0-9-]{4,28})[a-z0-9]$", var.sa_name))
    error_message = "sa_name must be 6-30 characters, start with a letter, and contain only lowercase letters, digits, and hyphens."
  }
}

variable "enable_services" {
  type        = bool
  description = "Enable required GCP APIs (iam, iamcredentials, sts, aiplatform). Never disabled on destroy."
  default     = true
}
