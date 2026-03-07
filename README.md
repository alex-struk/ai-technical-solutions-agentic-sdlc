# DevWorkspace (VS Code in Browser) on OpenShift

A browser-based VS Code IDE running on OpenShift using the DevWorkspace operator, protected by a connection token.

## Prerequisites

- `oc` CLI authenticated to the OpenShift cluster
- `envsubst` available (part of `gettext` package)
- DevWorkspace operator installed on the cluster (check with `oc api-resources | grep devworkspace`)
- A namespace with `allow-from-openshift-ingress` NetworkPolicy

## Files

- `workspace.yaml` — DevWorkspace definition (IDE container, init container, git project)
- `workspace-route.yaml` — Custom Route to expose the IDE at the root path
- `.env` — Connection token (gitignored, not committed)
- `.gitignore` — Excludes `.env` from version control

## Setup for a new project

### 1. Generate a connection token

```bash
echo "CONNECTION_TOKEN=$(openssl rand -hex 16)" > .env
```

This creates a `.env` file with your secret token. This file is gitignored and must not be committed.

### 2. Update `workspace.yaml`

Replace the following values:

| Field | Description |
|---|---|
| `metadata.namespace` | Your OpenShift namespace (e.g. `abc123-dev`) |
| `projects[0].git.remotes.origin` | Your git repo URL |

The `CONNECTION_TOKEN` value uses a `${CONNECTION_TOKEN}` placeholder that gets substituted at deploy time from `.env`.

### 3. Deploy the workspace

```bash
export $(cat .env | xargs) && envsubst '${CONNECTION_TOKEN}' < workspace.yaml | oc apply -f -
```

The `envsubst` command substitutes only `${CONNECTION_TOKEN}` while leaving other `${}` shell variables in the startup script untouched.

Wait for it to start:

```bash
oc get devworkspaces -w
```

Once the phase shows `Running`, note the DevWorkspace ID from the output (e.g. `workspacec878d71bae4f4e82`).

### 4. Create the custom route

The DevWorkspace operator creates a route at `/che-code/` with a URL rewrite, which breaks VS Code's redirects. A separate route at `/` is needed.

Update `workspace-route.yaml`:

| Field | Description |
|---|---|
| `metadata.namespace` | Your OpenShift namespace |
| `spec.host` | A unique hostname under `*.apps.silver.devops.gov.bc.ca` |
| `spec.to.name` | The service name — use `<devworkspace-id>-service` from the previous step |

```bash
oc apply -f workspace-route.yaml
```

### 5. Access the IDE

Open in your browser:

```
https://<your-route-host>/?tkn=<your-connection-token>
```

The token is saved as a cookie (valid 7 days). After the first visit you can access the URL without the `?tkn=` parameter.

## Redeploying

When you delete and recreate the workspace, the DevWorkspace ID changes, which means the service name changes too. After redeploying:

1. Get the new DevWorkspace ID: `oc get devworkspaces`
2. Update `spec.to.name` in `workspace-route.yaml` to `<new-id>-service`
3. `oc apply -f workspace-route.yaml`

## Gotchas

- **Images must use pinned digests, not `latest` tags** — ACS will block `latest` on this cluster.
- **`CODE_HOST=0.0.0.0`** is required — VS Code defaults to binding on `127.0.0.1`, which is unreachable from the OpenShift router.
- **The init container attribute** (`controller.devfile.io/init-container: true`) must be at the **component level**, not nested inside `container`. On this cluster the operator still runs it as a regular container, so the command includes `&& sleep infinity` to keep it alive after copying files.
- **The operator-managed route breaks VS Code** — it uses a `/che-code/` path prefix with a rewrite, but VS Code redirects to `/` which falls outside that path. The custom route in `workspace-route.yaml` solves this.
- **The DevWorkspace operator does not support `valueFrom` in env vars** — secrets cannot be referenced via `secretKeyRef`. The token is injected at deploy time using `envsubst` from the `.env` file instead.
- **Storage is ephemeral** — all data is lost when the pod restarts. To persist data, remove the `controller.devfile.io/storage-type: ephemeral` attribute and add a PVC-backed volume.
