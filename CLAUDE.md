# BC GOV OPENSHIFT SPECIFICS

- You are working ONLY in `fd34fb-prod` project
- Use `oc` commands to interact with openshift
- Keep track of installation instructions for this project in README.md
- Do not make adhoc direct modifications to remote infrastructure, changes must happen locally first and then deployed to openshift

## Storage

This is the trickiest area. Three types are available:

- **`netapp-file-standard`** — default NFS-based file storage; mountable by multiple pods simultaneously (RWX); no snapshots; more resilient during maintenance. Use for most general application files.
- **`netapp-block-standard`** — iSCSI block storage; higher performance for databases; RWO (one pod at a time only); **cannot be mounted by new pods during maintenance windows** — already-running pods failover fine, but freshly launching pods will fail to start until both NetApp nodes are back.
- **`netapp-file-backup`** — same as file-standard but OCIO backs it up daily.

**Critical storage rules**:

- Minimum PVC size is **20Mi** — anything smaller will fail to provision
- Maximum PVC size is **256Gi** — larger requests fail even if custom quotas allow more
- PVCs can only be **resized upward**, never shrunk; may need pod restart to trigger re-mount
- Only **block volumes support snapshots**
- For large unstructured data (>10Gi or user uploads), use OCIO S3 Object Storage — not NetApp
- All `netapp-*-standard` volumes have deduplication and compression jobs running **nightly at 00:10**

***

## Networking \& Routing

- **Zero-trust network policy by default** — all traffic is blocked unless you explicitly define `NetworkPolicy` objects. You must add `allow-from-openshift-ingress` for your pods to receive ingress traffic.
- Silver uses **standard OpenShift routing only** — HTTP and HTTPS (ports 80/443). There is no support for non-HTTP TCP routing (e.g., you cannot expose Redis, PostgreSQL, or other raw TCP services via a Route).
- **Custom TLS certificates are required** — no wildcard cert is provided by the platform. Request one via iStore (email `CITZIMBSD@gov.bc.ca`).
- Inter-namespace traffic also requires explicit `NetworkPolicy` rules — pods in `dev` cannot talk to `tools` by default.

***

## Images \& Registry

- The internal registry is at `image-registry.apps.silver.devops.gov.bc.ca`.
- Authenticate using `oc whoami -t` as your registry password.
- **Prefer images from the Red Hat registry** via Artifactory at `artifacts.developer.gov.bc.ca/redhat-docker-remote` — they are more OpenShift-compatible and curated .
- **Never use `latest` image tags** in production — ACS will flag this and it causes unpredictable rollout behaviour.
- Do not run containers as root — ACS security policies will block or alert on this.

***

## Pod \& Deployment Behaviour

- **Pods do not restart in a defined order** — if your app has dependencies (e.g., app waits for DB), implement `readinessProbe` and `livenessProbe` properly or your app will crash-loop on restarts .
- **Platform automation will automatically scale down idle workloads** in `dev` and `test` namespaces that have no activity or are consuming resources without justification. Before scaling back up, fix the underlying issue that triggered the scale-down.
- Always set both **CPU/memory requests AND limits** on all containers — pods without them will be rejected or deprioritized by the scheduler.

***

## Databases on Silver

Databases need special attention :

- Use `netapp-block-standard` storage for databases (better IOPS for small transactions/writes)
- Databases must be **highly available** — a single-pod DB is not acceptable for production; use a replicated setup (e.g., Patroni for PostgreSQL)
- Use the community [backup-container](https://github.com/BCDevOps/backup-container) project to implement automated DB backups
- Avoid storing large binary files in the DB — put files in S3 object storage and store only the reference URL in the DB

***

## CI/CD Pipelines

- The platform recommends GitHub Actions with `oc` CLI as the deployment mechanism.

```
- For manual rollouts via `oc`: `oc rollout -n <namespace> latest dc/<name>`
```

- Store your `OC_NAMESPACE` and `OC_TOKEN` as GitHub Secrets; `OC_SERVER` for Silver is `https://api.silver.devops.gov.bc.ca:6443`
- The `tools` namespace is the canonical place to run your CI/CD pipeline builds; promote built images from `tools` → `dev` → `test` → `prod`

***
## Secrets Management

OpenShift Secrets are **base64-encoded, not encrypted at rest in etcd** — though the underlying etcd volume itself is encrypted. Do not treat them as a true secrets vault. For sensitive credentials, consider Vault integration. Secrets are namespace-scoped, so sharing between namespaces requires explicit copying or a shared secrets strategy.

***

## ACS Security Enforcement

Advanced Cluster Security (ACS) actively scans deployments and **will flag or block**:

- Containers running as root
- Missing resource limits
- Use of `latest` image tags
- Images with known critical CVEs
- Violations of network policy baselines