# DevWorkspace (VS Code in Browser) on OpenShift

A browser-based VS Code IDE running on OpenShift using the DevWorkspace operator and che-code, managed with Kustomize.

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
├── undeploy.sh                  # Full cleanup script
├── .gitignore
└── CLAUDE.md
```

## Setup

### 1. Generate a connection token

```bash
echo "CONNECTION_TOKEN=$(openssl rand -hex 16)" > overlays/prod/.env
echo "SERVICE_NAME=placeholder" >> overlays/prod/.env
```

This creates a `.env` file with your secret token. This file is gitignored and must not be committed.

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

### 4. Undeploy

```bash
./undeploy.sh
```

Removes the DevWorkspace, custom route, ConfigMap, and any operator-managed routes/services.

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

Then deploy with `./deploy.sh overlays/dev` and undeploy with `./undeploy.sh overlays/dev`.

## How it works

The workspace runs two containers:

1. **che-code-injector** (init) — copies the che-code VS Code server binaries into a shared `/checode` volume
2. **tooling** — runs the VS Code server using the universal developer image, serving the IDE on port 3100

The startup script in the tooling container:
- Registers the container user in `/etc/passwd` (required for OpenShift's arbitrary UID)
- Generates a kubeconfig from the pod's service account for Kubernetes API access
- Injects VS Code user settings to force a plain bash terminal profile (see gotchas below)
- Starts `machine-exec` for terminal support
- Launches the VS Code server with connection token auth

Kustomize `replacements` inject the connection token from `overlays/prod/.env` into the workspace spec without needing `envsubst`.

## Gotchas

- **No Eclipse Che / Dev Spaces on this cluster** — only the bare DevWorkspace Operator is installed. The che-code image expects a full Che stack (dashboard, plugin registry, telemetry). Several Che env vars are stubbed with empty values in the workspace spec to prevent extension crashes. These stubs are harmless.
- **Terminal requires settings override** — without a full Che installation, che-code's custom terminal environment provider returns null, crashing `resolveWithEnvironment`. The startup script injects VS Code user settings that force a plain `/bin/bash` terminal profile, bypassing the Che provider entirely.
- **`--force-disable-user-env` is required** — without this flag, the VS Code server tries to resolve shell environment via a method that fails in this setup.
- **Images must use pinned digests, not `latest` tags** — ACS will block `latest` on this cluster.
- **`CODE_HOST=0.0.0.0`** is required — VS Code defaults to binding on `127.0.0.1`, which is unreachable from the OpenShift router.
- **The init container attribute** (`controller.devfile.io/init-container: true`) must be at the **component level**, not nested inside `container`. On this cluster the operator still runs it as a regular container, so the command includes `&& sleep infinity` to keep it alive after copying files.
- **The operator-managed route breaks VS Code** — it uses a `/che-code/` path prefix with a rewrite, but VS Code redirects to `/` which falls outside that path. The custom route solves this.
- **The DevWorkspace operator does not support `valueFrom` in env vars** — the devfile v2 `env` schema only has `name` and `value`. The token is injected via Kustomize `replacements` from a ConfigMap generated from the `.env` file.
- **Storage is ephemeral** — all data is lost when the pod restarts. To persist data, remove the `controller.devfile.io/storage-type: ephemeral` attribute and add a PVC-backed volume.
- **The route service name changes on every redeploy** — the DevWorkspace ID (and thus service name) changes each time. The deploy script handles this automatically.
