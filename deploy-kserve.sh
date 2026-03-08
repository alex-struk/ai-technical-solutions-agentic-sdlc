#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="b875cc-dev"
OVERLAY="overlays/prod/kserve"
MODEL_NAME="qwen2.5-3b-instruct-q4_k_m.gguf"
MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/${MODEL_NAME}"
PVC_NAME="llm-models-pvc"
LOADER_POD="model-loader"
ISVC_NAME="qwen25-3b"


# ── Step 0: Patch namespace labels ─────────────────────────────────────────────
echo "==> Patching namespace labels for RHOAI dashboard + KServe..."
if ! oc label namespace "${NAMESPACE}" opendatahub.io/dashboard=true --overwrite 2>/dev/null; then
  echo "    WARNING: Cannot patch namespace labels (requires admin privileges)."
  echo "    Ask a namespace admin to run:"
  echo "      oc label namespace ${NAMESPACE} opendatahub.io/dashboard=true --overwrite"
  echo "      oc label namespace ${NAMESPACE} modelmesh-enabled=false --overwrite"
else
  oc label namespace "${NAMESPACE}" modelmesh-enabled=false --overwrite
fi
echo ""

# Verify labels are correct before proceeding
MODELMESH=$(oc get namespace "${NAMESPACE}" -o jsonpath='{.metadata.labels.modelmesh-enabled}' 2>/dev/null || echo "")
if [ "${MODELMESH}" = "true" ]; then
  echo "    ERROR: modelmesh-enabled=true on namespace — KServe InferenceService will be"
  echo "    routed to ModelMesh instead of KServe. The deployment will proceed but the"
  echo "    InferenceService may not work until this label is fixed."
  echo ""
fi

# ── Step 1: Apply kustomize manifests ──────────────────────────────────────────
echo "==> Applying kustomize manifests..."
oc apply -k "${OVERLAY}"

# ── Step 2: Wait for PVC to bind ──────────────────────────────────────────────
echo "==> Waiting for PVC to bind..."
oc wait --for=jsonpath='{.status.phase}'=Bound \
  "pvc/${PVC_NAME}" -n "${NAMESPACE}" --timeout=120s

# ── Step 3: Check if model already exists on PVC ──────────────────────────────
echo "==> Checking if model already exists on PVC..."

# Spin up a helper pod to check/download the model
cat <<EOF | oc apply -n "${NAMESPACE}" -f -
apiVersion: v1
kind: Pod
metadata:
  name: ${LOADER_POD}
spec:
  containers:
  - name: loader
    image: registry.access.redhat.com/ubi9/ubi:9.4
    command: ["sleep", "infinity"]
    resources:
      requests:
        cpu: 100m
        memory: 256Mi
      limits:
        memory: 512Mi
    volumeMounts:
    - name: models
      mountPath: /mnt/models
  volumes:
  - name: models
    persistentVolumeClaim:
      claimName: ${PVC_NAME}
EOF

echo "==> Waiting for model-loader pod to be ready..."
oc wait --for=condition=Ready "pod/${LOADER_POD}" -n "${NAMESPACE}" --timeout=120s

# Check if model file already exists (and is the expected size)
EXPECTED_SIZE=2104932768  # qwen2.5-3b-instruct-q4_k_m.gguf
ACTUAL_SIZE=$(oc exec "${LOADER_POD}" -n "${NAMESPACE}" -- stat -c%s "/mnt/models/${MODEL_NAME}" 2>/dev/null || echo 0)
if [ "${ACTUAL_SIZE}" -eq "${EXPECTED_SIZE}" ]; then
  echo "==> Model ${MODEL_NAME} already exists on PVC (size verified), skipping."
else
  [ "${ACTUAL_SIZE}" -gt 0 ] && echo "==> Existing file has wrong size (${ACTUAL_SIZE} vs ${EXPECTED_SIZE}), re-downloading..."
  echo "==> Downloading ${MODEL_NAME} from HuggingFace (~2Gi)..."
  oc exec "${LOADER_POD}" -n "${NAMESPACE}" -- \
    curl -L -o "/mnt/models/${MODEL_NAME}" "${MODEL_URL}"
  echo "==> Download complete."
fi

# Verify the file
echo "==> Verifying model file..."
oc exec "${LOADER_POD}" -n "${NAMESPACE}" -- ls -lh "/mnt/models/${MODEL_NAME}"

# ── Step 4: Clean up helper pod ───────────────────────────────────────────────
echo "==> Cleaning up model-loader pod..."
oc delete pod "${LOADER_POD}" -n "${NAMESPACE}" --wait=false

# ── Step 5: Verify InferenceService ───────────────────────────────────────────
echo "==> Waiting for InferenceService to become ready..."
echo "    (this may take a few minutes while the model loads into memory)"

# Poll for readiness — KServe doesn't support oc wait --for=condition=Ready on ISVC
for i in $(seq 1 60); do
  READY=$(oc get inferenceservice "${ISVC_NAME}" -n "${NAMESPACE}" \
    -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "")
  if [ "${READY}" = "True" ]; then
    echo "==> InferenceService ${ISVC_NAME} is Ready!"
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "==> WARNING: InferenceService not ready after 5 minutes."
    echo "    Check logs: oc logs -l serving.kserve.io/inferenceservice=${ISVC_NAME} -n ${NAMESPACE}"
    exit 1
  fi
  sleep 5
done

# ── Step 6: Print endpoint info ───────────────────────────────────────────────
echo ""
echo "============================================================"
URL=$(oc get inferenceservice "${ISVC_NAME}" -n "${NAMESPACE}" \
  -o jsonpath='{.status.url}' 2>/dev/null || echo "")
if [ -n "${URL}" ]; then
  echo "Inference endpoint: ${URL}"
  echo "Chat completions:  ${URL}/v1/chat/completions"
  echo "Health check:      ${URL}/health"
else
  # For RawDeployment, the URL may come from the Route instead
  ROUTE=$(oc get route -n "${NAMESPACE}" -l serving.kserve.io/inferenceservice="${ISVC_NAME}" \
    -o jsonpath='{.items[0].spec.host}' 2>/dev/null || echo "")
  if [ -n "${ROUTE}" ]; then
    echo "Inference endpoint: https://${ROUTE}"
    echo "Chat completions:  https://${ROUTE}/v1/chat/completions"
    echo "Health check:      https://${ROUTE}/health"
  else
    echo "No external route found. Internal service:"
    echo "  http://${ISVC_NAME}-predictor.${NAMESPACE}.svc.cluster.local:8080/v1/chat/completions"
  fi
fi
echo "============================================================"
