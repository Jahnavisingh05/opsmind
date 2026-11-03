"""
Shared helper used by every business microservice to push structured
logs and metrics to the ingestion-service over HTTP.

In a "real" deployment this would be replaced by a Fluentd/Vector
sidecar or a Kafka producer -- HTTP keeps the MVP dependency-free.
"""
import os
import time
import uuid
import httpx

INGESTION_URL = os.environ.get("INGESTION_URL", "http://ingestion-service:8000")
SERVICE_NAME = os.environ.get("SERVICE_NAME", "unknown-service")

_client = httpx.Client(timeout=2.0)


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def emit_log(severity: str, message: str, error_type: str | None = None,
             request_id: str | None = None):
    payload = {
        "service": SERVICE_NAME,
        "severity": severity,
        "error_type": error_type,
        "message": message,
        "request_id": request_id or new_request_id(),
    }
    try:
        _client.post(f"{INGESTION_URL}/logs", json=payload)
    except Exception:
        pass  # never let telemetry take the request down


def emit_metric(cpu_pct: float, latency_ms: float, error_rate: float,
                 memory_mb: float, conn_pool_pct: float):
    payload = {
        "service": SERVICE_NAME,
        "cpu_pct": cpu_pct,
        "latency_ms": latency_ms,
        "error_rate": error_rate,
        "memory_mb": memory_mb,
        "conn_pool_pct": conn_pool_pct,
    }
    try:
        _client.post(f"{INGESTION_URL}/metrics", json=payload)
    except Exception:
        pass


def emit_deployment(version: str, description: str):
    payload = {"service": SERVICE_NAME, "version": version, "description": description}
    try:
        _client.post(f"{INGESTION_URL}/deployments", json=payload)
    except Exception:
        pass
