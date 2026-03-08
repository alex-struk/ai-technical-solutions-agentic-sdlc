#!/usr/bin/env bash
# Fallback deployment: plain Deployment + Service + Route for llama.cpp
# Use this while KServe is blocked by the modelmesh-enabled namespace label.
# Remove with: ./undeploy-kserve-fallback.sh
set -euo pipefail

NAMESPACE="b875cc-dev"
OVERLAY="overlays/prod/kserve/fallback"
SECRET_NAME="llama-api-key"
DEPLOYMENT_NAME="qwen25-3b-llama"

# ── Step 1: Create API key secret if it doesn't exist ─────────────────────────
if oc get secret "${SECRET_NAME}" -n "${NAMESPACE}" &>/dev/null; then
  echo "==> Secret ${SECRET_NAME} already exists, skipping."
else
  API_KEY=$(openssl rand -hex 32)
  echo "==> Creating API key secret..."
  oc create secret generic "${SECRET_NAME}" \
    --from-literal=LLAMA_API_KEY="${API_KEY}" \
    -n "${NAMESPACE}"
  echo ""
  echo "    ┌─────────────────────────────────────────────────────────┐"
  echo "    │ API Key (save this for Continue.dev / client config):   │"
  echo "    │ ${API_KEY} │"
  echo "    └─────────────────────────────────────────────────────────┘"
  echo ""
fi

# ── Step 2: Apply kustomize manifests ──────────────────────────────────────────
echo "==> Applying fallback deployment manifests..."
oc apply -k "${OVERLAY}"

# ── Step 3: Wait for deployment to roll out ───────────────────────────────────
echo "==> Waiting for deployment to be ready (model loading may take a few minutes)..."
oc rollout status "deployment/${DEPLOYMENT_NAME}" -n "${NAMESPACE}" --timeout=300s

# ── Step 4: Print endpoint info ───────────────────────────────────────────────
ROUTE_HOST=$(oc get route "${DEPLOYMENT_NAME}" -n "${NAMESPACE}" \
  -o jsonpath='{.spec.host}' 2>/dev/null || echo "")

echo ""
echo "============================================================"
if [ -n "${ROUTE_HOST}" ]; then
  echo "Inference endpoint: https://${ROUTE_HOST}"
  echo "Chat completions:  https://${ROUTE_HOST}/v1/chat/completions"
  echo "Health check:      https://${ROUTE_HOST}/health"
  echo ""
  echo "Test with:"
  echo "  curl https://${ROUTE_HOST}/v1/chat/completions \\"
  echo "    -H 'Content-Type: application/json' \\"
  echo "    -H 'Authorization: Bearer <your-api-key>' \\"
  echo "    -d '{\"messages\":[{\"role\":\"user\",\"content\":\"Hello!\"}],\"max_tokens\":50}'"
else
  echo "No route found. Internal service:"
  echo "  http://${DEPLOYMENT_NAME}.${NAMESPACE}.svc.cluster.local:8080/v1/chat/completions"
fi
echo "============================================================"
