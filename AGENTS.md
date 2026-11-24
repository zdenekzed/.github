# AGENTS.md

Single instruction file for AI agents working in `zdenekzed/.github`. `CLAUDE.md` and `GEMINI.md` point here.

## What this repository is

Public central repository for personal `zdenekzed/*` GitHub Actions reusable workflows, workflow templates, and shared GCP Workload Identity Federation (WIF) Terraform configuration powering AI PR reviews (`doitintl/antigravity-code-review`).

## Rules (non-negotiable)

1. **Public repository hygiene:** Never commit private repository names, personal GCP project IDs/numbers, Terraform state (`*.tfstate`), `terraform.tfvars`, or credentials.
2. **Personal git identity only:** Use personal git identity (`user.email` = personal Gmail, never an employer email).
3. **Pin external dependencies:** Pin all third-party GitHub Actions and `doitintl/antigravity-code-review` git references to full 40-character commit SHAs.
4. **Keyless auth only:** Never introduce `GEMINI_API_KEY` or `GOOGLE_API_KEY` fallback paths; Vertex AI auth stays WIF-only with `roles/aiplatform.user`.

## Validation commands

```bash
terraform -chdir=terraform/wif fmt -check
terraform -chdir=terraform/wif init -backend=false
terraform -chdir=terraform/wif validate
bash -n scripts/sync-github-vars.sh
python3 -m py_compile scripts/run_review.py tests/test_run_review.py
```
