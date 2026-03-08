#!/usr/bin/env bash
# Remove the fallback llama.cpp Deployment (plain Kubernetes, not KServe).
set -euo pipefail

NAMESPACE="b875cc-dev"
OVERLAY="overlays/prod/kserve/fallback"

echo "==> Deleting fallback deployment resources..."
oc delete -k "${OVERLAY}" --ignore-not-found

echo "==> Deleting API key secret..."
oc delete secret llama-api-key -n "${NAMESPACE}" --ignore-not-found

echo ""
echo "Fallback deployment removed from ${NAMESPACE}."
echo "Note: llm-models-pvc (shared with KServe setup) was NOT deleted."
