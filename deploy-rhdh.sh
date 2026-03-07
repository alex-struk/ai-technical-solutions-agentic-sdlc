#!/bin/bash
set -euo pipefail

OVERLAY="${1:-overlays/prod/rhdh}"
NAMESPACE="fd34fb-prod"

echo "==> Deploying Red Hat Developer Hub..."
oc apply -k "$OVERLAY" --server-side=true 2>/dev/null || oc apply -k "$OVERLAY"

echo "==> Waiting for PostgreSQL to be ready..."
oc rollout status statefulset/rhdh-postgresql -n "$NAMESPACE" --timeout=300s

echo "==> Restarting Developer Hub to pick up config changes..."
oc rollout restart deployment/rhdh-developer-hub -n "$NAMESPACE"

echo "==> Waiting for Developer Hub to be ready..."
oc rollout status deployment/rhdh-developer-hub -n "$NAMESPACE" --timeout=600s

ROUTE_HOST=$(oc get route rhdh-developer-hub -n "$NAMESPACE" -o jsonpath='{.spec.host}')

echo ""
echo "==> Deployment complete!"
echo "    URL: https://${ROUTE_HOST}"
