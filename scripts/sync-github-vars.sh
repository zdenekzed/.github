#!/usr/bin/env bash
set -euo pipefail

# Syncs GCP_PROJECT, WIF_PROVIDER, and WIF_SERVICE_ACCOUNT GitHub Actions variables
# from Terraform outputs to target repositories under GITHUB_OWNER.
#
# Usage:
#   ./scripts/sync-github-vars.sh repo-a repo-b        # explicit repositories
#   ./scripts/sync-github-vars.sh --all-source         # all non-fork, non-archived repos

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="${SCRIPT_DIR}/../terraform/wif"
OWNER="${GITHUB_OWNER:-zdenekzed}"

if ! command -v terraform >/dev/null 2>&1; then
  echo "ERROR: terraform not found in PATH" >&2
  exit 1
fi
if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh CLI not found in PATH" >&2
  exit 1
fi

if [ "$#" -eq 0 ]; then
  echo "Usage: $0 <repo1> [repo2 ...] | --all-source" >&2
  exit 1
fi

REPOS=()
if [ "$1" = "--all-source" ]; then
  while IFS= read -r name; do
    [ -n "${name}" ] && [ "${name}" != ".github" ] && REPOS+=("${name}")
  done < <(gh repo list "${OWNER}" --source --no-archived --limit 100 --json name --jq '.[].name')
else
  REPOS=("$@")
fi

if [ "${#REPOS[@]}" -eq 0 ]; then
  echo "No target repositories found." >&2
  exit 1
fi

GCP_PROJECT="$(terraform -chdir="${TF_DIR}" output -raw gcp_project)"
WIF_PROVIDER="$(terraform -chdir="${TF_DIR}" output -raw wif_provider)"
WIF_SERVICE_ACCOUNT="$(terraform -chdir="${TF_DIR}" output -raw wif_service_account)"

if [ -z "${GCP_PROJECT}" ] || [ -z "${WIF_PROVIDER}" ] || [ -z "${WIF_SERVICE_ACCOUNT}" ]; then
  echo "ERROR: Missing Terraform outputs in ${TF_DIR}. Run 'terraform -chdir=${TF_DIR} apply' first." >&2
  exit 1
fi

echo "Applying WIF variables from project '${GCP_PROJECT}':"
echo "  WIF_PROVIDER:        ${WIF_PROVIDER}"
echo "  WIF_SERVICE_ACCOUNT: ${WIF_SERVICE_ACCOUNT}"
echo

for repo in "${REPOS[@]}"; do
  full="${OWNER}/${repo}"
  echo "==> ${full}"
  gh variable set GCP_PROJECT --repo "${full}" --body "${GCP_PROJECT}"
  gh variable set WIF_PROVIDER --repo "${full}" --body "${WIF_PROVIDER}"
  gh variable set WIF_SERVICE_ACCOUNT --repo "${full}" --body "${WIF_SERVICE_ACCOUNT}"
done

echo
echo "Done. Re-run any PR review by commenting '/review' on the pull request."
