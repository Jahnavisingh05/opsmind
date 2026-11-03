import os
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row

DB_DSN = os.environ.get("DATABASE_URL", "postgresql://opsmind:opsmind@postgres:5432/opsmind")

app = FastAPI(title="OpsMind API Gateway")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_conn():
    return psycopg.connect(DB_DSN, autocommit=True, row_factory=dict_row)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/overview")
def overview():
    with get_conn() as conn:
        active = conn.execute("SELECT count(*) c FROM incidents WHERE status='OPEN'").fetchone()["c"]
        services = conn.execute("SELECT count(DISTINCT service) c FROM metrics WHERE ts >= now() - interval '5 minutes'").fetchone()["c"]
        err = conn.execute(
            "SELECT avg(error_rate) a FROM metrics WHERE ts >= now() - interval '2 minutes'"
        ).fetchone()["a"] or 0
        health_score = max(0, round(100 - (err * 100 * 1.5) - (active * 15)))
        return {
            "active_incidents": active,
            "services": services,
            "error_rate_pct": round(err * 100, 1),
            "system_health_pct": health_score,
        }


@app.get("/api/incidents")
def list_incidents(status: str | None = None, limit: int = 25):
    q = "SELECT * FROM incidents"
    params = []
    if status:
        q += " WHERE status = %s"
        params.append(status)
    q += " ORDER BY detected_at DESC LIMIT %s"
    params.append(limit)
    with get_conn() as conn:
        return conn.execute(q, params).fetchall()


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: int):
    with get_conn() as conn:
        incident = conn.execute("SELECT * FROM incidents WHERE id = %s", (incident_id,)).fetchone()
        if not incident:
            return {"error": "not found"}
        candidates = conn.execute(
            "SELECT * FROM incident_candidates WHERE incident_id = %s ORDER BY score DESC",
            (incident_id,),
        ).fetchall()
        timeline = conn.execute(
            "SELECT * FROM incident_timeline WHERE incident_id = %s ORDER BY ts ASC",
            (incident_id,),
        ).fetchall()
        return {"incident": incident, "candidates": candidates, "timeline": timeline}


@app.get("/api/metrics/latest")
def latest_metrics():
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT ON (service) service, ts, cpu_pct, latency_ms, error_rate,
                      memory_mb, conn_pool_pct
               FROM metrics ORDER BY service, ts DESC"""
        ).fetchall()
        return rows


@app.get("/api/metrics/series")
def metrics_series(service: str, minutes: int = 20):
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM metrics WHERE service = %s AND ts >= %s ORDER BY ts ASC",
            (service, since),
        ).fetchall()
