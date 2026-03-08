#!/usr/bin/env bash
# Simulate CrashLoopBackOff by injecting a bad command into the deployment.
# The container will immediately exit with code 1, triggering CrashLoopBackOff.
# Restore with: ./restore.sh
set -euo pipefail

NAMESPACE="fd34fb-prod"
DEPLOYMENT="test"

echo "==> Simulating CrashLoopBackOff on deployment/${DEPLOYMENT}..."
echo "    Patching container command to 'exit 1'..."

oc patch deployment "${DEPLOYMENT}" -n "${NAMESPACE}" \
  --type='json' \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/command","value":["sh","-c","exit 1"]}]'

echo ""
echo "Done! The deployment will enter CrashLoopBackOff within ~30 seconds."
echo "The SRE agent should detect this on its next check cycle."
echo ""
echo "To restore: ./restore.sh"
