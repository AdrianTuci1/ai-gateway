#!/usr/bin/env bash
#
# load-deploy-env.sh - turn the deploy secret into environment variables.
#
# The whole deploy environment lives in one Google Secret Manager secret,
# `ai-gateway/deploy-env`, holding a JSON object of KEY -> string. GitHub reads
# it through OIDC, so no credential is stored in repository secrets. This script
# writes the entries to $GITHUB_ENV for the following steps and masks every
# value in the run log.
#
# Required keys: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION,
# TF_STATE_BUCKET. Everything else is passed through untouched.
#
# Usage:
#   ./deploy/ci/load-deploy-env.sh deploy-env.json
#   jq . <deploy-env.json>          # inspect the keys, never paste the values
set -euo pipefail

file=${1:-}
if [ -n "$file" ]; then
  [ -r "$file" ] || { echo "load-deploy-env.sh: cannot read $file" >&2; exit 1; }
  input=$(cat "$file")
else
  input=$(cat)
fi

if ! jq -e 'type == "object"' >/dev/null 2>&1 <<<"$input"; then
  echo "load-deploy-env.sh: the deploy secret must be a JSON object of KEY -> string" >&2
  exit 1
fi

missing=()
for key in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_REGION TF_STATE_BUCKET; do
  value=$(jq -r --arg k "$key" 'if has($k) and (.[$k] != null) then (.[$k] | tostring) else "" end' <<<"$input")
  [ -n "$value" ] || missing+=("$key")
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo "load-deploy-env.sh: the deploy secret is missing ${missing[*]}" >&2
  exit 1
fi

# Mask first, then export: the values below never reach the log in clear.
while IFS= read -r line; do
  [ -n "$line" ] || continue
  printf '::add-mask::%s\n' "$line"
done < <(jq -r '.[] | tostring' <<<"$input")

if [ -n "${GITHUB_ENV:-}" ]; then
  while IFS= read -r key; do
    value=$(jq -r --arg k "$key" '.[$k] | tostring' <<<"$input")
    if [[ "$value" == *$'\n'* ]]; then
      # GITHUB_ENV needs the heredoc form for values that span lines.
      delim="AGW_EOF_$(date +%s%N)"
      printf '%s<<%s\n%s\n%s\n' "$key" "$delim" "$value" "$delim"
    else
      printf '%s=%s\n' "$key" "$value"
    fi
  done < <(jq -r 'keys[]' <<<"$input") >>"$GITHUB_ENV"
else
  echo "load-deploy-env.sh: GITHUB_ENV is not set; nothing exported" >&2
  exit 1
fi

echo "loaded deploy environment: $(jq -r 'keys | join(", ")' <<<"$input")"
