#!/usr/bin/env bash
# Restore the deployment to its previous working state.
# Undoes changes from simulate-crashloop.sh or simulate-oom.sh.
set -euo pipefail

NAMESPACE="fd34fb-prod"
DEPLOYMENT="test"

echo "==> Rolling back deployment/${DEPLOYMENT} to previous revision..."
oc rollout undo deployment/"${DEPLOYMENT}" -n "${NAMESPACE}"

echo "==> Waiting for rollout to complete..."
oc rollout status deployment/"${DEPLOYMENT}" -n "${NAMESPACE}" --timeout=120s

echo ""
echo "Deployment restored successfully."
echo "Check status: oc get pods -n ${NAMESPACE} -l app=${DEPLOYMENT}"
