# b875cc-dev Namespace Assessment

Assessment date: 2026-03-06

## Overview

The `b875cc-dev` namespace on OpenShift Silver hosts the **CITZ IMB AI** platform — a full-stack AI application managed via ArgoCD/Helm (`citz-imb-ai` app). It includes an LLM serving layer, a FastAPI backend, frontend UIs, Airflow for orchestration, Neo4j graph database, and supporting databases.

## LLM Server

A custom llama.cpp-based server runs multiple GGUF models concurrently on different ports.

- **Deployment**: `llm-server` (1 replica)
- **Image**: `b875cc-tools/llm-server-imagestream:372` (built in `b875cc-tools`, not accessible to us)
- **Route**: `citz-imb-ai-llm-server-route-b875cc-dev.apps.silver.devops.gov.bc.ca` (edge TLS, exposes port 8090)
- **Resources**: requests 50m CPU / 256Mi memory, limit 16Gi memory
- **Models volume**: `emptyDir` — models are downloaded at startup, not persisted across restarts
- **Service**: `llm-server-svc` exposes ports 8090–8096

### Served Models

| Port | Model | Status |
|------|-------|--------|
| 8090 | `qwen2.5-3b-instruct-q4_k_m.gguf` | Online |
| 8092 | `GLM-4.1V-9B-Thinking-Q4_K_M.gguf` | Online |
| 8093 | `Kimi-VL-A3B-Thinking-2506-Q4_K_M.gguf` | Not ready |
| 8095 | `qwen2-0_5b-instruct-q4_k_m.gguf` | Online |
| 8097 | `Qwen3VL-8B-Instruct-Q4_K_M.gguf` | Not ready |

All models expose OpenAI-compatible endpoints at `/v1/chat/completions` and `/health`.

### Configuration

Controlled via `llm-server-secret`:

| Key | Size | Purpose |
|-----|------|---------|
| `MODEL_SOURCE_DIR` | 7 bytes | Directory or URL for model downloads |
| `DOWNLOAD_MODELS` | 4 bytes | Flag to trigger model download on startup |
| `MODELS` | 9 bytes | Model list/config |
| `LLM_CONTEXT_SIZE` | 4 bytes | Context window size |

## OpenShift AI / KServe

- **ServingRuntime**: `openvino` exists (OpenVINO Model Server) but `modelmesh-serving-openvino` is **scaled to 0** — unused
- **InferenceService**: none deployed — KServe single-model serving is not in use
- The namespace has `opendatahub.io/dashboard` labels so resources appear in the OpenShift AI dashboard

## Application Stack

### Backend & Frontend

| Component | Type | Replicas | Notes |
|-----------|------|----------|-------|
| `ai-fastapi` | Deployment | 1 | FastAPI backend, restarted on AWS cred rotation |
| `ai-frontend` | Deployment | 1 | Main frontend UI |
| `ai-frontend-analytics` | Deployment | 1 | Analytics/feedback frontend |

### Orchestration

| Component | Type | Notes |
|-----------|------|-------|
| `airflow-web-deployment` | Deployment | Airflow web UI |
| `airflow-scheduler` | Deployment | Airflow scheduler (31 restarts in 57d) |
| `airflow-postgres` | DeploymentConfig | PostgreSQL 13 for Airflow metadata |
| `airflow-logs-purge` | CronJob | Daily at 07:00 UTC |

### Databases

| Component | Type | Storage |
|-----------|------|---------|
| `neo4j` | Deployment | `neo4j-pvc` 8Gi RWX + `neo4j-backup` 8Gi RWX |
| `airflow-postgres` | DeploymentConfig | `airflow-postgres` 512Mi RWO |
| `trulens` | DeploymentConfig | `trulens` 1Gi RWO (PostgreSQL 13, LLM evaluation tracking) |
| `superset-db` | (service only) | `superset-db` 1Gi RWO |
| `diffgram-postgresql` | (service only) | `diffgram-postgresql` 5Gi RWO |

### Notebooks (OpenShift AI Workbenches)

| Name | Storage | Status |
|------|---------|--------|
| `ai-dev` | 120Gi `netapp-file-standard` | **Running** (1/1) |
| `ai-dev-3` | 100Gi | Scaled to 0 |
| `ai-dev-bigboy` | 120Gi | Scaled to 0 |
| `ai-dev-py-3-11` | 50Gi | Scaled to 0 |

## Secrets

### AWS Credentials

- **`aws-creds`**: `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` — rotated every 2 days by `update-aws-creds` CronJob
- Rotation pulls from AWS Parameter Store (`/iam_users/bedrock_keys`) — these are for **AWS Bedrock**, not S3 model storage
- After rotation, `ai-fastapi` deployment is automatically restarted

### Other Notable Secrets

| Secret | Purpose |
|--------|---------|
| `llm-server-secret` | LLM server model config |
| `model-serving-etcd` | ModelMesh etcd credentials |
| `model-serving-proxy-tls` | ModelMesh TLS cert |
| `rabbitmq-secret` | RabbitMQ credentials |
| `superset-secret` | Superset config (9 keys) |

## Networking

### Network Policies

| Policy | Scope |
|--------|-------|
| `allow-from-openshift-ingress` | Allows ingress traffic to all pods |
| `allow-same-namespace` | Allows intra-namespace traffic |
| `platform-services-controlled-default` | Platform default |
| `ai-dev-*-ctrl-np` / `ai-dev-*-oauth-np` | Per-notebook network policies |

### Routes

| Route | Service | TLS |
|-------|---------|-----|
| `citz-imb-ai-llm-server-route` | `llm-server-svc:8090` | edge/Redirect |
| `citz-imb-ai-backend-route` | `citz-imb-ai-backend-svc:10000` | edge/Redirect |
| `citz-imb-ai-frontend-route` | `citz-imb-ai-frontend-svc:8080` | edge/Redirect |
| `ai-feedback` | `citz-imb-ai-frontend-analytics-svc:11000` | edge |
| `citz-imb-ai-airflow-web-route` | `citz-imb-ai-airflow-web-svc:13000` | edge/Redirect |
| `ai-dev` | `ai-dev-tls` | reencrypt/Redirect |
| `neo4j` | `neo4j-service:tcp-bolt` | edge/None |

## Resource Quotas & Usage

| Resource | Used | Limit | Available |
|----------|------|-------|-----------|
| Long-running pods | 10 | 100 | 90 |
| CPU requests | 9.4 cores | 16 cores | ~6.6 cores |
| Memory requests | ~68Gi | 128Gi | ~60Gi |
| PVCs | 15 | 60 | 45 |
| PVC storage | ~416Gi | 512Gi | ~96Gi |
| Block storage PVCs | 0 | 60 | 60 |

## Management

- **GitOps**: Managed by ArgoCD (`citz-imb-ai` Helm chart)
- **Service Account**: `b875cc-vault` used by llm-server, CronJobs, and workbenches
- **Image builds**: Happen in `b875cc-tools` namespace (we do not have access)
- **CI/CD labels**: `devops.gov.bc.ca/gitops-app-shared: citz-imb-ai`
