#!/usr/bin/env bash
# Simulate OOMKilled by setting an extremely low memory limit.
# The Node.js process will exceed 32Mi on startup and get killed.
# Restore with: ./restore.sh
set -euo pipefail

NAMESPACE="fd34fb-prod"
DEPLOYMENT="test"

echo "==> Simulating OOMKilled on deployment/${DEPLOYMENT}..."
echo "    Setting memory limit to 32Mi (too low for Node.js)..."

oc patch deployment "${DEPLOYMENT}" -n "${NAMESPACE}" \
  --type='json' \
  -p='[
    {"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"32Mi"},
    {"op":"replace","path":"/spec/template/spec/containers/0/resources/requests/memory","value":"32Mi"}
  ]'

echo ""
echo "Done! The pod will be OOMKilled within ~30 seconds."
echo "The SRE agent should detect this on its next check cycle."
echo ""
echo "To restore: ./restore.sh"
