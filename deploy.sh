#!/bin/bash
set -euo pipefail

OVERLAY="${1:-overlays/prod}"
NAMESPACE="fd34fb-prod"
ENV_FILE="$OVERLAY/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: $ENV_FILE not found. Create it with CONNECTION_TOKEN=<your-token>"
  exit 1
fi

echo "==> Phase 1: Deploying DevWorkspace..."
# Set a placeholder service name for the initial deploy (route will be updated in phase 2)
sed -i 's/^SERVICE_NAME=.*/SERVICE_NAME=placeholder/' "$ENV_FILE"
# Apply only the workspace (skip the route for now)
oc apply -k "$OVERLAY" --server-side=true 2>/dev/null || oc apply -k "$OVERLAY"

echo "==> Waiting for DevWorkspace to start..."
oc wait --for=jsonpath='{.status.phase}'=Running devworkspace/my-workspace -n "$NAMESPACE" --timeout=300s

# Get the DevWorkspace ID and derive the service name
DW_ID=$(oc get devworkspace my-workspace -n "$NAMESPACE" -o jsonpath='{.status.devworkspaceId}')
SERVICE_NAME="${DW_ID}-service"
echo "    DevWorkspace ID: $DW_ID"
echo "    Service name:    $SERVICE_NAME"

echo "==> Phase 2: Updating route with service name..."
sed -i "s/^SERVICE_NAME=.*/SERVICE_NAME=$SERVICE_NAME/" "$ENV_FILE"
oc apply -k "$OVERLAY" --server-side=true 2>/dev/null || oc apply -k "$OVERLAY"

TOKEN=$(grep '^CONNECTION_TOKEN=' "$ENV_FILE" | cut -d= -f2)
ROUTE_HOST=$(oc get route my-workspace-ide -n "$NAMESPACE" -o jsonpath='{.spec.host}')

echo ""
echo "==> Deployment complete!"
echo "    URL: https://${ROUTE_HOST}/?tkn=${TOKEN}"
