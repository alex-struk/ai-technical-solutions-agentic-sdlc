#!/bin/bash
set -euo pipefail

NAMESPACE="fd34fb-prod"

echo "==> Stopping workspace..."
oc patch devworkspace my-workspace -n "$NAMESPACE" --type=merge -p '{"spec":{"started":false}}'
oc wait --for=jsonpath='{.status.phase}'=Stopped devworkspace/my-workspace -n "$NAMESPACE" --timeout=120s

echo "==> Starting workspace..."
oc patch devworkspace my-workspace -n "$NAMESPACE" --type=merge -p '{"spec":{"started":true}}'
oc wait --for=jsonpath='{.status.phase}'=Running devworkspace/my-workspace -n "$NAMESPACE" --timeout=300s

OVERLAY="${1:-overlays/prod}"
ENV_FILE="$OVERLAY/.env"
TOKEN=$(grep '^CONNECTION_TOKEN=' "$ENV_FILE" | cut -d= -f2)
ROUTE_HOST=$(oc get route my-workspace-ide -n "$NAMESPACE" -o jsonpath='{.spec.host}')

echo ""
echo "==> Workspace restarted!"
echo "    URL: https://${ROUTE_HOST}/?tkn=${TOKEN}"
