# zdenekzed/.github

Central GitHub Actions workflows, workflow templates, and Terraform Workload Identity Federation (WIF) configuration for personal `zdenekzed/*` repositories.

## AI Code Review (`antigravity-code-review`)

Provides a reusable pull-request code review workflow backed by [`doitintl/antigravity-code-review`](https://github.com/doitintl/antigravity-code-review) (Google Antigravity SDK on Vertex AI, pull-context review with per-PR cost artifacts).

### Highlights

- **Single source of truth:** `.github/workflows/ai-code-review.yml` is called by thin ~20-line caller workflows in target repositories (and also surfaced in GitHub's *Actions → New workflow* via `workflow-templates/`).
- **Keyless Vertex AI auth (WIF only):** Refuses `GEMINI_API_KEY` / `GOOGLE_API_KEY`. Uses GCP Workload Identity Federation scoped to `assertion.repository_owner == 'zdenekzed'` (or an explicit allowlist).
- **Graceful skip before setup:** If a repository does not have `GCP_PROJECT`, `WIF_PROVIDER`, and `WIF_SERVICE_ACCOUNT` set yet, the `gate` job exits cleanly with a notice rather than failing PR checks.
- **Re-trigger on demand:** Comment `/review` on any PR (restricted to `OWNER`, `MEMBER`, or `COLLABORATOR`).
- **Isolated runtime:** Installs `antigravity-code-review` (pinned by commit SHA) into `${RUNNER_TEMP}/agy-review-venv` outside the checked-out workspace, and checks out `refs/pull/<PR>/head` so both `pull_request` and `/review` comment runs inspect the PR's head commit.

### Onboarding a repository

Add `.github/workflows/ai-code-review.yml` (or pick **AI Code Review (Antigravity)** from the GitHub Actions *New workflow* picker):

```yaml
name: AI code review

on:
  pull_request:
    types: [opened, synchronize, reopened]
  issue_comment:
    types: [created]

concurrency:
  group: ai-review-${{ github.event.pull_request.number || github.event.issue.number }}-${{ github.event_name }}
  cancel-in-progress: true

permissions:
  contents: read
  id-token: write
  pull-requests: write

jobs:
  review:
    uses: zdenekzed/.github/.github/workflows/ai-code-review.yml@main
    with:
      gcp_project: ${{ vars.GCP_PROJECT }}
      wif_provider: ${{ vars.WIF_PROVIDER }}
      wif_service_account: ${{ vars.WIF_SERVICE_ACCOUNT }}
```

### One-time GCP WIF setup

1. Pick or create a personal GCP project with billing enabled.
2. Provision WIF + least-privilege `agy-code-review` service account (`roles/aiplatform.user` only) with versioned GCS remote state:
   ```bash
   cd terraform/wif
   cp terraform.tfvars.example terraform.tfvars
   cp backend.hcl.example backend.hcl
   # edit terraform.tfvars (project_id) and backend.hcl (GCS state bucket)
   terraform init -backend-config=backend.hcl
   terraform apply
   ```
3. Push the resulting values to repository Actions variables:
   ```bash
   ./scripts/sync-github-vars.sh <repo1> <repo2> ...
   # or all non-fork, non-archived repositories:
   ./scripts/sync-github-vars.sh --all-source
   ```
4. Verify least privilege:
   ```bash
   gcloud projects get-iam-policy <PROJECT_ID> \
     --flatten="bindings[].members" \
     --filter="bindings.members:agy-code-review@<PROJECT_ID>.iam.gserviceaccount.com" \
     --format="value(bindings.role)"
   # Expected: roles/aiplatform.user
   ```

## Repository layout

- `.github/workflows/ai-code-review.yml` — reusable `workflow_call` workflow
- `workflow-templates/` — GitHub UI workflow starter template for new repositories
- `terraform/wif/` — shared GCP Workload Identity Federation Terraform module
- `scripts/sync-github-vars.sh` — sets `GCP_PROJECT`, `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT` via `gh variable set`
- `docs/adr/` — architectural decision records
