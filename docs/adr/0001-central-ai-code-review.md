# ADR-0001: Central AI code review workflow and shared WIF for personal repositories

- **Status:** Accepted
- **Date:** 2026-11-24

## Context

[`doitintl/antigravity-code-review`](https://github.com/doitintl/antigravity-code-review) implements a pull-context AI PR reviewer on top of the Google Antigravity SDK and Vertex AI, with per-PR cost tracking (`review-cost.json`). At commit `8ef939d8cfb683bf998020dc6007e95b2971bd26` it does not yet ship a standalone Marketplace Action (`action.yml` / `@v1` tag) and requires:

1. Keyless GCP Workload Identity Federation (WIF) to Vertex AI (`GOOGLE_CLOUD_LOCATION=global`, `roles/aiplatform.user`).
2. Installing and running `python -m antigravity_code_review.review` with `GH_TOKEN`.

Because `zdenekzed` is a personal GitHub account (not a GitHub Organization), organization-level Actions variables and org-level required workflows are unavailable. Duplicating the full ~140-line workflow across every repository would make version bumps and bug fixes brittle.

## Decision

1. **Central public repository `zdenekzed/.github`:** Host a single reusable workflow (`.github/workflows/ai-code-review.yml`) triggered via `workflow_call`, plus a GitHub starter template (`workflow-templates/ai-code-review.yml`). Because the repository is public, both public and private repositories under `zdenekzed` can call it.
2. **Thin callers in target repositories:** Each target repository adds a ~25-line `.github/workflows/ai-code-review.yml` passing `vars.GCP_PROJECT`, `vars.WIF_PROVIDER`, and `vars.WIF_SERVICE_ACCOUNT` explicitly as inputs (GitHub Actions does not implicitly forward caller `vars` to `workflow_call`).
3. **Pinned upstream SHA and isolated venv:** Pin `doitintl/antigravity-code-review` to commit `8ef939d8cfb683bf998020dc6007e95b2971bd26` and install it into `${RUNNER_TEMP}/agy-review-venv` so the checked-out repository workspace stays untouched.
4. **Explicit PR head checkout:** Check out `refs/pull/<PR>/head` so both `pull_request` events and `/review` `issue_comment` re-triggers inspect the PR's head revision rather than the default branch.
5. **Graceful skip when unconfigured:** If any of `GCP_PROJECT`, `WIF_PROVIDER`, or `WIF_SERVICE_ACCOUNT` is empty, the `gate` job skips cleanly with a notice rather than failing CI checks before GCP WIF is bootstrapped.
6. **Owner-scoped shared WIF Terraform module (`terraform/wif/`):** Use one personal GCP project and WIF provider with `attribute_condition = "assertion.repository_owner == 'zdenekzed'"` (optionally narrowed by `allowed_repositories`) and a single least-privilege service account holding only `roles/aiplatform.user`.

## Consequences

- Updating the reviewer SHA, Python version, or action pins happens in one place (`zdenekzed/.github`).
- Private repository names and GCP project identifiers never appear in the public `.github` repository.
- Per-repository billing separation is traded for single-project simplicity on a personal account; cost per PR remains visible in the review comment and uploaded `review-cost-pr-<N>` artifact.
