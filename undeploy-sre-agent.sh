#!/usr/bin/env bash
# Remove the SRE Agent and all its components
set -euo pipefail

NAMESPACE="fd34fb-prod"
OVERLAY="overlays/prod/sre-agent"

echo "==> Removing SRE Agent components..."
oc delete -k "${OVERLAY}" --ignore-not-found

echo "==> Cleaning up any leftover PipelineRuns..."
oc delete pipelineruns -n "${NAMESPACE}" -l app=sre-agent --ignore-not-found

echo ""
echo "SRE Agent removed successfully."
