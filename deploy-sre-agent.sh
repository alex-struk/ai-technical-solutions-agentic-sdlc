#!/usr/bin/env bash
# Deploy the SRE Agent: AutoGen + MCP servers + Tekton pipeline
# Remove with: ./undeploy-sre-agent.sh
set -euo pipefail

NAMESPACE="fd34fb-prod"
OVERLAY="overlays/prod/sre-agent"
ENV_FILE="${OVERLAY}/.env"

# ── Step 1: Check prerequisites ──────────────────────────────────────────────
if [ ! -f "${ENV_FILE}" ]; then
  echo "ERROR: ${ENV_FILE} not found."
  echo ""
  echo "Create it with:"
  echo "  cat > ${ENV_FILE} <<EOF"
  echo "  GITHUB_TOKEN=ghp_your_token_here"
  echo "  LLM_API_KEY=your_llama_api_key_here"
  echo "  EOF"
  echo ""
  echo "Get LLM_API_KEY from: oc get secret llama-api-key -n b875cc-dev -o jsonpath='{.data.LLAMA_API_KEY}' | base64 -d"
  exit 1
fi

echo "==> Checking .env has required keys..."
for key in GITHUB_TOKEN LLM_API_KEY; do
  if ! grep -q "^${key}=" "${ENV_FILE}"; then
    echo "ERROR: ${ENV_FILE} is missing ${key}"
    exit 1
  fi
done

# ── Step 2: Apply kustomize manifests ────────────────────────────────────────
echo "==> Applying SRE Agent manifests..."
oc apply -k "${OVERLAY}"

# ── Step 3: Wait for deployments ─────────────────────────────────────────────
echo "==> Waiting for k8s-mcp-server to be ready..."
oc rollout status deployment/k8s-mcp-server -n "${NAMESPACE}" --timeout=120s

echo "==> Waiting for sre-agent to be ready..."
oc rollout status deployment/sre-agent -n "${NAMESPACE}" --timeout=180s

# ── Step 4: Print status ─────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "SRE Agent deployed successfully!"
echo ""
echo "Components:"
echo "  - sre-agent:      Deployment (AutoGen + GitHub MCP)"
echo "  - k8s-mcp-server: Deployment (Kubernetes MCP via SSE)"
echo "  - sre-remediation: Tekton Pipeline (with ApprovalTask)"
echo ""
echo "View logs:"
echo "  oc logs -f deployment/sre-agent -n ${NAMESPACE}"
echo ""
echo "View k8s-mcp-server logs:"
echo "  oc logs -f deployment/k8s-mcp-server -n ${NAMESPACE}"
echo ""
echo "View pending approvals:"
echo "  oc get pipelineruns -n ${NAMESPACE} -l app=sre-agent"
echo "============================================================"
