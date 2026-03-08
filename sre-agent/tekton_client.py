"""Tekton PipelineRun creation for remediation approval workflows."""

import os
import logging
import uuid
from datetime import datetime, timezone

from kubernetes import client, config

logger = logging.getLogger(__name__)

PIPELINE_NAME = "sre-remediation"


def _get_k8s_client():
    """Get a Kubernetes API client using in-cluster config."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CustomObjectsApi()


def create_remediation_run(
    incident_id: str,
    action_type: str,
    target_resource: str,
    description: str,
) -> str | None:
    """Create a Tekton PipelineRun for remediation with approval gate.

    Returns the PipelineRun name if created, None on failure.
    """
    namespace = os.environ.get("TARGET_NAMESPACE", "fd34fb-prod")
    run_name = f"sre-remediation-{incident_id[:8]}-{uuid.uuid4().hex[:6]}"

    pipeline_run = {
        "apiVersion": "tekton.dev/v1",
        "kind": "PipelineRun",
        "metadata": {
            "name": run_name,
            "namespace": namespace,
            "labels": {
                "app": "sre-agent",
                "incident-id": incident_id[:63],
            },
        },
        "spec": {
            "pipelineRef": {"name": PIPELINE_NAME},
            "params": [
                {"name": "incident-id", "value": incident_id},
                {"name": "action-type", "value": action_type},
                {"name": "target-resource", "value": target_resource},
                {"name": "description", "value": description},
            ],
        },
    }

    try:
        api = _get_k8s_client()
        result = api.create_namespaced_custom_object(
            group="tekton.dev",
            version="v1",
            namespace=namespace,
            plural="pipelineruns",
            body=pipeline_run,
        )
        logger.info(
            "Created PipelineRun %s for incident %s", run_name, incident_id
        )
        return run_name
    except Exception:
        logger.exception("Failed to create PipelineRun for incident %s", incident_id)
        return None


def check_pipeline_run_status(run_name: str) -> str:
    """Check the status of a PipelineRun.

    Returns: 'pending', 'approved', 'rejected', 'running', 'succeeded', 'failed', 'unknown'
    """
    namespace = os.environ.get("TARGET_NAMESPACE", "fd34fb-prod")
    try:
        api = _get_k8s_client()
        result = api.get_namespaced_custom_object(
            group="tekton.dev",
            version="v1",
            namespace=namespace,
            plural="pipelineruns",
            name=run_name,
        )
        conditions = result.get("status", {}).get("conditions", [])
        if not conditions:
            return "pending"

        latest = conditions[-1]
        status = latest.get("status", "Unknown")
        reason = latest.get("reason", "")

        if status == "True":
            return "succeeded"
        elif status == "False":
            if "rejected" in reason.lower():
                return "rejected"
            return "failed"
        else:
            if "approv" in reason.lower():
                return "pending"
            return "running"
    except Exception:
        logger.exception("Failed to check PipelineRun %s", run_name)
        return "unknown"


def generate_incident_id(deployment: str, issue_type: str) -> str:
    """Generate a deterministic incident ID for deduplication."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return f"{issue_type}-{deployment}-{ts}"
