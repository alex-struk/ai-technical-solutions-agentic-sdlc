# KServe Namespace Label Issue — b875cc-dev

## Problem

The `b875cc-dev` namespace has `modelmesh-enabled=true` and is missing `opendatahub.io/dashboard=true`. This prevents KServe from reconciling our `InferenceService` resources.

## Current Labels

```
modelmesh-enabled=true          # routes to ModelMesh (wrong)
opendatahub.io/dashboard        # missing (namespace invisible to RHOAI dashboard)
```

## Required Labels

```
modelmesh-enabled=false          # routes to KServe single-model serving
opendatahub.io/dashboard=true    # makes project visible in RHOAI dashboard
```

## Impact

- The `InferenceService` resource (`qwen25-3b`) is created but has no `.status` section — the KServe controller never reconciles it
- No predictor pod is created, no endpoint is generated
- The `serving.kserve.io/deploymentMode: RawDeployment` annotation on the InferenceService does NOT override the namespace label on RHOAI/ODH (unlike upstream KServe)
- The existing `llm-server` Deployment (plain Kubernetes, not KServe) is **unaffected** by this label change

## Fix Required (Admin Action)

Namespace labels are cluster-scoped — the `admin` role on the namespace is insufficient. A platform admin or someone with cluster-level namespace patch permissions must run:

```bash
oc label namespace b875cc-dev modelmesh-enabled=false --overwrite
oc label namespace b875cc-dev opendatahub.io/dashboard=true --overwrite
```

### Who Can Do This

Someone from `b875cc-dev` role bindings with platform-level access

## What Happens After the Fix

1. KServe controller picks up `qwen25-3b` InferenceService
2. Predictor pod is created with the llama.cpp ServingRuntime
3. Model loads from `llm-models-pvc` (already downloaded and verified)
4. Endpoint becomes available at `/v1/chat/completions`
5. Namespace appears in the RHOAI dashboard under "Data Science Projects"

## Verification

After the labels are changed, run:

```bash
# Check if KServe reconciled the InferenceService
oc get inferenceservice qwen25-3b -n b875cc-dev

# Check for predictor pod
oc get pods -n b875cc-dev -l serving.kserve.io/inferenceservice=qwen25-3b

# If no pods appear, delete and recreate the ISVC to force re-reconciliation
oc delete inferenceservice qwen25-3b -n b875cc-dev
oc apply -k overlays/prod/kserve
```

## Investigation Log

- Confirmed `oc auth can-i patch namespaces` returns `no` for Alex
- Confirmed `RawDeployment` annotation does not override namespace label on RHOAI (tested by deleting/recreating ISVC — still no status)
- Cannot access KServe controller logs (operator namespaces are forbidden)
- The `odh.inferenceservice.finalizers` finalizer is added (ODH controller sees the resource) but no further reconciliation occurs
