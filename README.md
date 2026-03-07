# Agentic SDLC on OpenShift

Developer tooling on OpenShift, managed with Kustomize. Includes:
- **DevWorkspace** — browser-based VS Code IDE (che-code)
- **Red Hat Developer Hub** — Backstage-based internal developer portal (RHDH v1.9.0)

## Prerequisites

- `oc` CLI authenticated to the OpenShift cluster
- `helm` CLI (for re-templating RHDH chart updates)
- DevWorkspace operator installed on the cluster (check with `oc api-resources | grep devworkspace`)
- A namespace with `allow-from-openshift-ingress` NetworkPolicy

## Project Structure

```
├── base/
│   ├── kustomization.yaml
│   ├── workspace.yaml              # DevWorkspace definition
│   ├── workspace-route.yaml        # Route to expose the IDE
│   └── rhdh/                       # Red Hat Developer Hub
│       ├── kustomization.yaml
│       ├── rhdh-manifests.yaml     # Helm-templated RHDH manifests
│       └── network-policy.yaml     # Ingress + RHDH→PostgreSQL policies
├── overlays/
│   └── prod/
│       ├── kustomization.yaml      # DevWorkspace overlay (namespace, token, service name)
│       ├── .env                    # CONNECTION_TOKEN and SERVICE_NAME (gitignored)
│       └── rhdh/
│           └── kustomization.yaml  # RHDH overlay (namespace)
├── deploy.sh                       # DevWorkspace deploy script
├── deploy-rhdh.sh                  # RHDH deploy script
├── undeploy.sh                     # DevWorkspace cleanup script
├── .gitignore
└── CLAUDE.md
```

## DevWorkspace Setup

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

## Red Hat Developer Hub (RHDH)

RHDH is deployed using Helm-templated manifests managed via Kustomize, keeping it consistent with the rest of the project.

### Deploy

```bash
./deploy-rhdh.sh
```

This applies the Kustomize overlay, waits for PostgreSQL and the Developer Hub to become ready, and prints the URL.

**URL:** `https://rhdh-developer-hub-fd34fb-prod.apps.silver.devops.gov.bc.ca/`

### How it was generated

The manifests in `base/rhdh/rhdh-manifests.yaml` were generated with `helm template` (not `helm install`) to keep everything in git:

```bash
helm repo add openshift-helm-charts https://charts.openshift.io/
helm template rhdh openshift-helm-charts/redhat-developer-hub \
  --version 1.9.0 \
  --namespace fd34fb-prod \
  --set global.clusterRouterBase=apps.silver.devops.gov.bc.ca \
  > base/rhdh/rhdh-manifests.yaml
```

After templating, the following manual edits were applied:
- Removed the Helm test Pod (uses `latest` tag, blocked by ACS)
- Cleared `CATALOG_INDEX_IMAGE` (skopeo inside the init container can't auth to `registry.redhat.io` without a pull secret mounted in the pod)
- Fixed PostgreSQL env vars for RHEL image compatibility (Bitnami `POSTGRES_*` → RHEL `POSTGRESQL_*`)
- App-config uses `postgres` superuser for DB connections (Backstage needs `CREATE DATABASE` privileges for per-plugin databases)

### Upgrading RHDH

To upgrade, re-run `helm template` with the new `--version`, re-apply the manual edits listed above, and redeploy:

```bash
helm template rhdh openshift-helm-charts/redhat-developer-hub \
  --version <new-version> \
  --namespace fd34fb-prod \
  --set global.clusterRouterBase=apps.silver.devops.gov.bc.ca \
  > base/rhdh/rhdh-manifests.yaml
# Re-apply manual edits (see above), then:
./deploy-rhdh.sh
```

### RHDH Gotchas

- **RHEL PostgreSQL image uses different env vars than Bitnami** — the Helm chart templates Bitnami-style `POSTGRES_USER`/`POSTGRES_PASSWORD` but the actual image (`rhel9/postgresql-15`) requires `POSTGRESQL_USER`/`POSTGRESQL_PASSWORD`/`POSTGRESQL_DATABASE`. The manifests have been patched accordingly.
- **Backstage needs superuser DB access** — each plugin creates its own database at startup. The `bn_backstage` user created by `POSTGRESQL_USER` doesn't have `CREATEDB` privileges, so the app-config connects as `postgres` with `POSTGRESQL_ADMIN_PASSWORD`.
- **Plugin catalog index requires registry auth** — the init container uses `skopeo` to pull the plugin catalog index from `registry.redhat.io`. Without a pull secret mounted inside the pod, this fails. `CATALOG_INDEX_IMAGE` is set to empty to skip this step (node-level pull secrets only work for kubelet image pulls, not in-container skopeo).
- **NetworkPolicy is required** — zero-trust networking on this cluster means both ingress to RHDH and RHDH→PostgreSQL traffic must be explicitly allowed. The `network-policy.yaml` handles both.

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

## How DevWorkspace works

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

## DevWorkspace Gotchas

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
