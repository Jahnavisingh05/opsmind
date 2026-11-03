import os
from datetime import datetime, timezone
from typing import Optional

import psycopg
from fastapi import FastAPI
from pydantic import BaseModel

DB_DSN = os.environ.get("DATABASE_URL", "postgresql://opsmind:opsmind@postgres:5432/opsmind")

app = FastAPI(title="OpsMind Ingestion Service")


def get_conn():
    return psycopg.connect(DB_DSN, autocommit=True)


class LogEvent(BaseModel):
    service: str
    severity: str
    message: str
    error_type: Optional[str] = None
    request_id: Optional[str] = None


class MetricEvent(BaseModel):
    service: str
    cpu_pct: float
    latency_ms: float
    error_rate: float
    memory_mb: float
    conn_pool_pct: float


class DeploymentEvent(BaseModel):
    service: str
    version: str
    description: Optional[str] = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/logs")
def ingest_log(ev: LogEvent):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO logs (ts, service, severity, error_type, message, request_id)
               VALUES (now(), %s, %s, %s, %s, %s)""",
            (ev.service, ev.severity, ev.error_type, ev.message, ev.request_id),
        )
    return {"ok": True}


@app.post("/metrics")
def ingest_metric(ev: MetricEvent):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO metrics (ts, service, cpu_pct, latency_ms, error_rate, memory_mb, conn_pool_pct)
               VALUES (now(), %s, %s, %s, %s, %s, %s)""",
            (ev.service, ev.cpu_pct, ev.latency_ms, ev.error_rate, ev.memory_mb, ev.conn_pool_pct),
        )
    return {"ok": True}


@app.post("/deployments")
def ingest_deployment(ev: DeploymentEvent):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO deployments (ts, service, version, description)
               VALUES (now(), %s, %s, %s)""",
            (ev.service, ev.version, ev.description),
        )
    return {"ok": True}
