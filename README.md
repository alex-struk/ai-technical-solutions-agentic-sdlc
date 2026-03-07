# DevWorkspace (VS Code in Browser) on OpenShift

A browser-based VS Code IDE running on OpenShift using the DevWorkspace operator, managed with Kustomize.

## Prerequisites

- `oc` CLI authenticated to the OpenShift cluster
- DevWorkspace operator installed on the cluster (check with `oc api-resources | grep devworkspace`)
- A namespace with `allow-from-openshift-ingress` NetworkPolicy

## Project Structure

```
├── base/                        # Base resources (environment-agnostic)
│   ├── kustomization.yaml
│   ├── workspace.yaml           # DevWorkspace definition
│   └── workspace-route.yaml     # Route to expose the IDE
├── overlays/
│   └── prod/                    # Production overlay
│       ├── kustomization.yaml   # Namespace, token injection, service name
│       └── .env                 # CONNECTION_TOKEN and SERVICE_NAME (gitignored)
├── deploy.sh                    # Two-phase deploy script
├── .gitignore
└── CLAUDE.md
```

## Setup

### 1. Generate a connection token

```bash
echo "CONNECTION_TOKEN=$(openssl rand -hex 16)" > overlays/prod/.env
echo "SERVICE_NAME=placeholder" >> overlays/prod/.env
```

### 2. Configure your overlay

Edit `overlays/prod/kustomization.yaml` if you need to change the namespace (default: `fd34fb-prod`).

Edit `base/workspace.yaml` to change:
- `projects[0].git.remotes.origin` — your git repo URL

Edit `base/workspace-route.yaml` to change:
- `spec.host` — your route hostname under `*.apps.silver.devops.gov.bc.ca`

### 3. Deploy

```bash
./deploy.sh
```

The script handles everything in two phases:
1. Deploys the DevWorkspace and waits for it to start
2. Reads the DevWorkspace ID, updates the route's service name, and re-applies

The final output includes the full URL with token.

### Manual deploy (without script)

```bash
# Phase 1: Deploy workspace
oc apply -k overlays/prod/

# Wait for workspace
oc wait --for=jsonpath='{.status.phase}'=Running devworkspace/my-workspace -n fd34fb-prod --timeout=300s

# Get service name
DW_ID=$(oc get devworkspace my-workspace -n fd34fb-prod -o jsonpath='{.status.devworkspaceId}')

# Phase 2: Update .env and re-apply
sed -i "s/^SERVICE_NAME=.*/SERVICE_NAME=${DW_ID}-service/" overlays/prod/.env
oc apply -k overlays/prod/
```

## Adding new environments

Create a new overlay directory:

```bash
mkdir -p overlays/dev
```

Add a `kustomization.yaml` that references `../../base` and set the appropriate namespace:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: fd34fb-dev
resources:
  - ../../base
# ... same replacements pattern as prod
```

Then deploy with `./deploy.sh overlays/dev`.

## Gotchas

- **Images must use pinned digests, not `latest` tags** — ACS will block `latest` on this cluster.
- **`CODE_HOST=0.0.0.0`** is required — VS Code defaults to binding on `127.0.0.1`, which is unreachable from the OpenShift router.
- **The init container attribute** (`controller.devfile.io/init-container: true`) must be at the **component level**, not nested inside `container`. On this cluster the operator still runs it as a regular container, so the command includes `&& sleep infinity` to keep it alive after copying files.
- **The operator-managed route breaks VS Code** — it uses a `/che-code/` path prefix with a rewrite, but VS Code redirects to `/` which falls outside that path. The custom route solves this.
- **The DevWorkspace operator does not support `valueFrom` in env vars** — secrets cannot be referenced via `secretKeyRef`. The token is injected via Kustomize `replacements` from a ConfigMap generated from the `.env` file.
- **Storage is ephemeral** — all data is lost when the pod restarts. To persist data, remove the `controller.devfile.io/storage-type: ephemeral` attribute and add a PVC-backed volume.
- **The route service name changes on every redeploy** — the DevWorkspace ID (and thus service name) changes each time. The deploy script handles this automatically.
