# Agentic SDLC on OpenShift

Developer tooling on OpenShift, managed with Kustomize. Includes:
- **DevWorkspace** — browser-based VS Code IDE (che-code)
- **Red Hat Developer Hub** — Backstage-based internal developer portal (RHDH v1.9.0)
- **KServe Model Serving** — LLM inference via llama.cpp on OpenShift AI (`b875cc-dev`)
- **SRE Agent** — agentic SRE system using AutoGen + MCP servers + Tekton for automated incident response

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
│   ├── rhdh/                       # Red Hat Developer Hub
│   │   ├── kustomization.yaml
│   │   ├── rhdh-manifests.yaml     # Helm-templated RHDH manifests
│   │   ├── network-policy.yaml     # Ingress + RHDH→PostgreSQL policies
│   │   └── users.yaml              # Catalog user entities (login allowlist)
│   └── kserve/                     # KServe model serving (b875cc-dev)
│       ├── kustomization.yaml
│       ├── pvc.yaml                # PVC for GGUF model storage
│       ├── serving-runtime.yaml    # llama.cpp ServingRuntime
│       ├── inference-service.yaml  # InferenceService for qwen2.5-3b
│       └── fallback/               # Plain Deployment fallback (no KServe CRDs)
│           ├── kustomization.yaml
│           └── deployment.yaml     # Deployment + Service + Route
│   └── sre-agent/                  # Agentic SRE system
│       ├── kustomization.yaml
│       ├── deployment.yaml         # SRE agent (AutoGen + GitHub MCP)
│       ├── k8s-mcp-server.yaml     # Kubernetes MCP server (SSE)
│       ├── rbac.yaml               # ServiceAccount + read-only Role
│       ├── configmap.yaml          # Agent configuration
│       ├── network-policy.yaml     # Agent → MCP server traffic
│       └── tekton-pipeline.yaml    # Remediation pipeline with ApprovalTask
├── overlays/
│   └── prod/
│       ├── kustomization.yaml      # DevWorkspace overlay (namespace, token, service name)
│       ├── .env                    # CONNECTION_TOKEN and SERVICE_NAME (gitignored)
│       ├── rhdh/
│       │   ├── kustomization.yaml  # RHDH overlay (namespace, secrets, patches)
│       │   └── .env                # GITHUB_CLIENT_ID, SECRET, PAT (gitignored)
│       ├── kserve/
│       │   └── kustomization.yaml  # KServe overlay (namespace: b875cc-dev)
│       └── sre-agent/
│           ├── kustomization.yaml  # SRE agent overlay (namespace: fd34fb-prod)
│           └── .env                # GITHUB_TOKEN, LLM_API_KEY (gitignored)
├── sre-agent/                      # SRE agent source code
│   ├── agent.py                    # Main AutoGen agent loop
│   ├── mcp_setup.py                # MCP server connections (k8s SSE + GitHub STDIO)
│   ├── llm_config.py               # LLM client (OpenAI-compatible → qwen2.5-3b)
│   ├── tekton_client.py            # Tekton PipelineRun creation
│   ├── prompts.py                  # System prompts and issue/PR templates
│   ├── requirements.txt            # Python dependencies
│   ├── Dockerfile                  # UBI9 Python 3.11 + github-mcp-server binary
│   └── test-scenarios/             # Scripts to simulate incidents
│       ├── simulate-crashloop.sh   # Inject CrashLoopBackOff
│       ├── simulate-oom.sh         # Inject OOMKilled
│       └── restore.sh              # Rollback to working state
├── templates/                      # RHDH software templates
│   └── hello-world/
│       ├── template.yaml           # Template definition (scaffolder)
│       └── skeleton/               # Skeleton files for new projects
│           ├── index.js
│           ├── package.json
│           ├── Dockerfile
│           └── catalog-info.yaml
├── deploy.sh                       # DevWorkspace deploy script
├── deploy-rhdh.sh                  # RHDH deploy script
├── deploy-kserve.sh                # KServe model serving deploy script
├── deploy-sre-agent.sh             # SRE agent deploy script
├── undeploy.sh                     # DevWorkspace cleanup script
├── undeploy-kserve.sh              # KServe cleanup script
├── undeploy-sre-agent.sh           # SRE agent cleanup script
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

### GitHub Authentication Setup

RHDH uses GitHub OAuth for login and a Personal Access Token (PAT) for scaffolder repo creation.

#### 1. Create a GitHub OAuth App

Go to **GitHub > Settings > Developer settings > OAuth Apps > New OAuth App**:

| Field | Value |
|---|---|
| Application name | `RHDH fd34fb-prod` |
| Homepage URL | `https://rhdh-developer-hub-fd34fb-prod.apps.silver.devops.gov.bc.ca` |
| Authorization callback URL | `https://rhdh-developer-hub-fd34fb-prod.apps.silver.devops.gov.bc.ca/api/auth/github/handler/frame` |

Enable "Expire user authorization tokens" for short-lived token security.

#### 2. Create a GitHub PAT

Create a PAT at **GitHub > Settings > Developer settings > Personal access tokens** with `repo` scope. This is used by the scaffolder to create repos — it's separate from user login auth.

#### 3. Configure credentials

Add your credentials to `overlays/prod/rhdh/.env` (gitignored):

```bash
GITHUB_CLIENT_ID=<your-oauth-app-client-id>
GITHUB_CLIENT_SECRET=<your-oauth-app-client-secret>
GITHUB_INTEGRATION_TOKEN=<your-pat>
```

The overlay's `secretGenerator` creates a Kubernetes Secret from this file and injects it into the Deployment via `envFrom`.

#### 4. Manage allowed users

Only GitHub users with a matching `User` entity in the catalog can sign in (via `usernameMatchingUserEntityName` resolver). Edit `base/rhdh/users.yaml` to add or remove users:

```yaml
apiVersion: backstage.io/v1alpha1
kind: User
metadata:
  name: github-username  # must match GitHub username exactly
spec:
  profile:
    displayName: Display Name
  memberOf: [team]
```

After editing, redeploy with `./deploy-rhdh.sh`.

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
- Added GitHub auth provider, integrations, `signInPage`, and catalog config to the app-config ConfigMap
- Added `catalog-entities` volume mount for the users allowlist ConfigMap

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
- **GitHub auth uses `usernameMatchingUserEntityName`** — this acts as an allowlist. Only GitHub users with a matching `User` entity in `base/rhdh/users.yaml` can sign in. The `metadata.name` must match the GitHub username exactly (case-sensitive).
- **Credentials are in `.env`, not the manifests** — `overlays/prod/rhdh/.env` is gitignored and contains `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, and `GITHUB_INTEGRATION_TOKEN`. Kustomize `secretGenerator` creates a Secret from it and the overlay patches `envFrom` onto the Deployment.

## Software Templates

RHDH uses Backstage software templates to scaffold new projects. Templates are registered in the catalog via `url` type locations pointing to `template.yaml` files in this repo.

### Available Templates

| Template | Description |
|---|---|
| `hello-world` | Simple Node.js Express service with a Dockerfile ready for OpenShift |

### How it works

1. The `template.yaml` defines the scaffolder wizard (input parameters, steps, outputs)
2. The `skeleton/` directory contains the templated files that get scaffolded into a new repo
3. The scaffolder uses the `GITHUB_INTEGRATION_TOKEN` to create the new repo on GitHub
4. A `catalog-info.yaml` is included so the new component auto-registers in the RHDH catalog

### Adding a new template

1. Create a new directory under `templates/<template-name>/`
2. Add a `template.yaml` and a `skeleton/` directory with your scaffolded files
3. Register the template in the catalog config inside `base/rhdh/rhdh-manifests.yaml` under `catalog.locations`:
   ```yaml
   - type: url
     target: https://github.com/alex-struk/ai-technical-solutions-agentic-sdlc/blob/master/templates/<template-name>/template.yaml
     rules:
       - allow: [Template]
   ```
4. Redeploy with `./deploy-rhdh.sh`

> **Note:** In the future, templates should be moved to a dedicated repository (e.g., `software-templates`) to separate infrastructure configuration from template definitions. This is the standard Backstage pattern and allows templates to be versioned and managed independently.

## KServe Model Serving (OpenShift AI)

LLM models are served via KServe `InferenceService` with a llama.cpp `ServingRuntime`, deployed to the `b875cc-dev` namespace. Models are stored on a PVC (no S3 required).

**Namespace**: `b875cc-dev` (OpenShift AI with KServe single-model serving)

### Deploy

```bash
./deploy-kserve.sh
```

The script:
1. Patches namespace labels for RHOAI dashboard visibility and KServe mode (requires admin — warns if insufficient permissions)
2. Applies kustomize manifests (PVC, ServingRuntime, InferenceService)
3. Loads the GGUF model into the PVC via a temporary helper pod:
   - Skips if model already exists on PVC (verified by file size)
   - Downloads from HuggingFace (~2Gi) on first deploy
4. Waits for the InferenceService to become ready and prints the endpoint URL

### Undeploy

```bash
./undeploy-kserve.sh
```

Removes the InferenceService, ServingRuntime, and PVC (including downloaded models). Namespace labels are not reverted automatically.

### Served Models

| InferenceService | Model | Runtime | Resources |
|---|---|---|---|
| `qwen25-3b` | `qwen2.5-3b-instruct-q4_k_m.gguf` | `llamacpp-runtime` | 1 CPU / 6-8Gi mem |

### Adding a new model

1. Add a new `InferenceService` YAML in `base/kserve/` referencing the model file and runtime
2. Add it to `base/kserve/kustomization.yaml`
3. Update the `MODEL_NAME` and `MODEL_URL` in `deploy-kserve.sh` (or extend it to support multiple models)
4. Run `./deploy-kserve.sh`

### Testing

```bash
curl https://<inference-endpoint>/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Hello!"}
    ],
    "max_tokens": 100
  }'
```

### Fallback: Plain Deployment (no KServe)

KServe requires namespace labels (`modelmesh-enabled=false`) that need platform admin access. While waiting for that, the fallback deployment runs llama.cpp as a plain Kubernetes Deployment with API key auth.

```bash
# Deploy (creates API key secret, Deployment, Service, Route)
./deploy-kserve-fallback.sh

# Remove (does NOT delete the shared llm-models-pvc)
./undeploy-kserve-fallback.sh
```

The deploy script prints the API key on first run — save it for client config. The endpoint uses the same `llm-models-pvc` as the KServe setup.

**Endpoint**: `https://qwen25-3b-llama-b875cc-dev.apps.silver.devops.gov.bc.ca/v1/chat/completions`

All requests require `Authorization: Bearer <api-key>`. Requests without a valid key get `{"detail":"Invalid API key"}`.

Once KServe is unblocked (namespace labels fixed), remove the fallback with `./undeploy-kserve-fallback.sh` and re-run `./deploy-kserve.sh`.

### KServe Gotchas

- **No Knative Serving on this cluster** — must use `RawDeployment` mode (annotation `serving.kserve.io/deploymentMode: RawDeployment`). Serverless auto-scale-to-zero is not available.
- **Namespace labels are critical** — `opendatahub.io/dashboard=true` makes the project visible in RHOAI dashboard; `modelmesh-enabled=false` routes to KServe instead of ModelMesh. The deploy script attempts to set these but **requires admin privileges**. If you see a permissions error, ask a namespace admin to run: `oc label namespace b875cc-dev opendatahub.io/dashboard=true modelmesh-enabled=false --overwrite`
- **ACS blocks `latest` image tags** — the llama.cpp image is pinned by SHA digest, not by tag.
- **PVC storage, not S3** — models are stored on a `netapp-file-standard` RWX PVC (`llm-models-pvc`). The helper pod downloads from HuggingFace on first deploy; subsequent deploys skip the download if the file already exists.
- **Each model gets its own pod** — unlike the existing `llm-server` which runs 5 models in one pod, each `InferenceService` gets dedicated resources. This prevents OOM issues.
- **The existing `llm-server` is unaffected** — it's a plain Kubernetes Deployment (not a KServe resource), so changing namespace labels and deploying InferenceServices has no impact on it.

## SRE Agent (Agentic Incident Response)

An automated Site Reliability Engineering agent that monitors deployments, detects issues, analyzes root causes using the local LLM, and creates GitHub issues/PRs with proposed fixes. Uses Tekton ApprovalTasks for human-in-the-loop remediation.

### Architecture

```
fd34fb-prod namespace
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│  ┌─────────────────────┐     SSE      ┌──────────────────────┐  │
│  │   sre-agent          │────────────>│ kubernetes-mcp-server │  │
│  │   (AutoGen Python)   │             │ (pod/log/event tools) │  │
│  │                      │  STDIO      └──────────────────────┘  │
│  │   includes:          │──────┐                                 │
│  │   github-mcp-server  │      │       ┌──────────────────────┐  │
│  │   (binary, in-proc)  │<─────┘       │ Tekton Pipeline      │  │
│  │                      │──creates────>│ ApprovalTask →       │  │
│  │                      │  PipelineRun │ RemediationTask      │  │
│  └──────────┬───────────┘              └──────────────────────┘  │
│             │                                                    │
│             │ monitors    ┌──────────────────────┐               │
│             └────────────>│ test (hello-world)   │               │
│                           └──────────────────────┘               │
└──────────────────────────────────────────────────────────────────┘
              │ HTTPS (via routes)
              └──────────> LLM (phi4-mini-llama in b875cc-dev)
```

**Components:**
- **sre-agent** — AutoGen-based Python agent with monitoring loop (configurable interval, default 60s)
- **kubernetes-mcp-server** — [MCP server](https://github.com/manusa/kubernetes-mcp-server) exposing Kubernetes tools (pod status, logs, events) via SSE
- **github-mcp-server** — [GitHub MCP server](https://github.com/github/github-mcp-server) for issue/PR creation, runs as STDIO subprocess inside the agent container
- **sre-remediation** — Tekton Pipeline with ApprovalTask gate, then remediation Task (restart/rollback/scale)

**Data flow:**
1. Agent polls pod status, events, and logs via kubernetes-mcp-server
2. When an issue is detected (CrashLoopBackOff, OOMKilled, etc.), diagnostic context is sent to Phi-4 Mini for analysis
3. LLM returns structured JSON with root cause, severity, and suggested fix
4. Agent creates a GitHub issue with the full incident report
5. For actionable fixes, a Tekton PipelineRun is created with an ApprovalTask
6. After human approval (in OpenShift Pipelines console), the remediation executes

### Deploy

#### 1. Configure credentials

```bash
# Get the LLM API key from the existing secret
LLM_KEY=$(oc get secret llama-api-key -n b875cc-dev -o jsonpath='{.data.LLAMA_API_KEY}' | base64 -d)

# Reuse the GitHub PAT from the workspace overlay (needs repo scope)
GITHUB_KEY=$(grep GITHUB_TOKEN overlays/prod/.env | cut -d= -f2)

cat > overlays/prod/sre-agent/.env <<EOF
GITHUB_TOKEN=${GITHUB_KEY}
LLM_API_KEY=${LLM_KEY}
EOF
```

#### 2. Build and push the agent image

```bash
podman build -t ghcr.io/strukalex/sre-agent:v0.1 sre-agent/
podman push ghcr.io/strukalex/sre-agent:v0.1
```

After pushing, update `base/sre-agent/deployment.yaml` with the image digest for ACS compliance.

#### 3. Deploy

```bash
./deploy-sre-agent.sh
```

This deploys the agent, kubernetes-mcp-server, RBAC, NetworkPolicy, and Tekton pipeline. The script validates that `.env` exists and has the required keys.

#### 4. Verify

```bash
# Check agent logs
oc logs -f deployment/sre-agent -n fd34fb-prod

# Check MCP server logs
oc logs -f deployment/k8s-mcp-server -n fd34fb-prod

# View pending remediation approvals
oc get pipelineruns -n fd34fb-prod -l app=sre-agent
```

#### 5. Undeploy

```bash
./undeploy-sre-agent.sh
```

### Configuration

All configuration is in `base/sre-agent/configmap.yaml`:

| Variable | Default | Description |
|---|---|---|
| `CHECK_INTERVAL` | `60` | Seconds between monitoring checks |
| `TARGET_NAMESPACE` | `fd34fb-prod` | Namespace to monitor |
| `TARGET_DEPLOYMENT` | `test` | Deployment name to monitor |
| `HEALTH_ENDPOINT` | `https://test-fd34fb-prod.apps.silver.devops.gov.bc.ca/health` | App health endpoint |
| `LLM_ENDPOINT` | `https://phi4-mini-llama-b875cc-dev.apps.silver.devops.gov.bc.ca/v1/chat/completions` | LLM API endpoint |
| `LLM_MODEL` | `microsoft_Phi-4-mini-instruct-Q4_K_M` | Model identifier |
| `GITHUB_REPO` | `strukalex/rhdh-test` | Target repo for issues/PRs |
| `K8S_MCP_URL` | `http://k8s-mcp-server:8080/sse` | Kubernetes MCP server SSE endpoint |
| `INCIDENT_COOLDOWN_MINUTES` | `30` | Minutes before re-alerting on same issue type |

### Testing with Simulated Incidents

Scripts in `sre-agent/test-scenarios/` inject failures into the target deployment:

```bash
# Simulate CrashLoopBackOff (bad container command)
./sre-agent/test-scenarios/simulate-crashloop.sh

# Simulate OOMKilled (32Mi memory limit)
./sre-agent/test-scenarios/simulate-oom.sh

# Restore to previous working state
./sre-agent/test-scenarios/restore.sh
```

After injecting a failure, watch the agent logs to see it detect the issue, query the LLM, create a GitHub issue, and trigger a Tekton PipelineRun for approval.

### Approving Remediations

When the agent detects an actionable issue, it creates a Tekton PipelineRun with an ApprovalTask. To approve:

1. Go to the OpenShift Console → Pipelines → PipelineRuns (namespace `fd34fb-prod`)
2. Find the run labeled `app=sre-agent`
3. Review the incident description and approve or reject
4. On approval, the remediation task executes (restart, rollback, or scale)

### SRE Agent Gotchas

- **kagent requires cluster-admin for CRDs** — since we don't have cluster-admin on BC Gov Silver, we use AutoGen (the framework kagent wraps) directly as a Python library. Same MCP tool connectivity, no CRDs needed.
- **LLM quality is limited (3.8B model)** — Phi-4 Mini is capable for its size but the agent still uses structured prompts with JSON schema and few-shot examples to ensure consistent output. If JSON parsing fails, it falls back to raw text in the GitHub issue. Upgrading to a larger model (e.g., 8B+) will further improve analysis quality.
- **No Prometheus MCP** — querying OpenShift's built-in Prometheus requires `cluster-monitoring-view` ClusterRole, which we don't have. The agent monitors via the Kubernetes API (pod status, events, logs) instead. Ask the platform team for `cluster-monitoring-view` to enable metric-based monitoring in a future iteration.
- **No webhook-driven alerts** — Alertmanager config is cluster-scoped. The agent polls on a configurable interval instead.
- **The agent calls the LLM via the external route** — it goes through HTTPS ingress rather than cross-namespace service networking. This avoids needing NetworkPolicy in `b875cc-dev` but adds ~10ms latency per request.
- **GitHub MCP server runs as a subprocess** — the binary is bundled in the agent container image and launched via STDIO transport. This avoids deploying it as a separate container.
- **Incident cooldown prevents duplicate issues** — the agent tracks incidents in-memory with a 30-minute cooldown per incident type. If the agent pod restarts, cooldown state is lost and it may re-file an issue.
- **Tekton ApprovalTask approvers are hardcoded** — edit `base/sre-agent/tekton-pipeline.yaml` to change the list of approvers.

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
- **Idle timeout is currently disabled** (`-1`) — the workspace will never auto-stop. This should be changed to a reasonable value (e.g., `8h`) once RHDH is fully working, to avoid wasting cluster resources.
- **The route service name changes on every redeploy** — the DevWorkspace ID (and thus service name) changes each time. The deploy script handles this automatically.
