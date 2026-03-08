#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="b875cc-dev"
OVERLAY="overlays/prod/kserve"

echo "==> Deleting KServe resources..."
oc delete -k "${OVERLAY}" --ignore-not-found

echo "==> Cleaning up model-loader pod if still running..."
oc delete pod model-loader -n "${NAMESPACE}" --ignore-not-found

echo ""
echo "KServe resources removed from ${NAMESPACE}."
echo ""
echo "Note: Namespace labels (opendatahub.io/dashboard, modelmesh-enabled) were NOT reverted."
echo "The PVC (llm-models-pvc) with downloaded models was deleted."
echo "To revert namespace labels manually:"
echo "  oc label namespace ${NAMESPACE} opendatahub.io/dashboard- modelmesh-enabled=true --overwrite"
