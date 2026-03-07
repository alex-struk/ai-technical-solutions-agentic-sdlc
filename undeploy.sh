#!/bin/bash
set -euo pipefail

OVERLAY="${1:-overlays/prod}"
NAMESPACE="fd34fb-prod"

echo "==> Removing all workspace resources from $NAMESPACE..."

oc delete devworkspace my-workspace -n "$NAMESPACE" --ignore-not-found
oc delete route my-workspace-ide -n "$NAMESPACE" --ignore-not-found
oc delete configmap workspace-config -n "$NAMESPACE" --ignore-not-found

# The DevWorkspace operator creates these automatically — clean them up too
DW_ROUTES=$(oc get routes -n "$NAMESPACE" -o name 2>/dev/null | grep workspace || true)
if [ -n "$DW_ROUTES" ]; then
  echo "==> Cleaning up operator-managed routes..."
  echo "$DW_ROUTES" | xargs oc delete -n "$NAMESPACE" --ignore-not-found
fi

DW_SERVICES=$(oc get services -n "$NAMESPACE" -o name 2>/dev/null | grep workspace || true)
if [ -n "$DW_SERVICES" ]; then
  echo "==> Cleaning up operator-managed services..."
  echo "$DW_SERVICES" | xargs oc delete -n "$NAMESPACE" --ignore-not-found
fi

echo ""
echo "==> Undeployment complete. All workspace resources removed from $NAMESPACE."
