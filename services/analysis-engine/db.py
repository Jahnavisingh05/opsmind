import os
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

DB_DSN = os.environ.get("DATABASE_URL", "postgresql://opsmind:opsmind@postgres:5432/opsmind")


def get_conn():
    return psycopg.connect(DB_DSN, autocommit=True, row_factory=dict_row)


def recent_metrics(minutes: int):
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM metrics WHERE ts >= %s ORDER BY ts ASC", (since,)
        ).fetchall()


def recent_logs(minutes: int, severity: str | None = None):
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    q = "SELECT * FROM logs WHERE ts >= %s"
    params = [since]
    if severity:
        q += " AND severity = %s"
        params.append(severity)
    q += " ORDER BY ts ASC"
    with get_conn() as conn:
        return conn.execute(q, params).fetchall()


def recent_deployments(minutes: int):
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM deployments WHERE ts >= %s ORDER BY ts ASC", (since,)
        ).fetchall()


def insert_anomaly(service, metric_name, value, score):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO anomalies (ts, service, metric_name, value, score, consumed)
               VALUES (now(), %s, %s, %s, %s, FALSE)""",
            (service, metric_name, value, score),
        )


def unconsumed_anomalies(minutes: int):
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM anomalies WHERE ts >= %s AND consumed = FALSE ORDER BY ts ASC",
            (since,),
        ).fetchall()


def mark_anomalies_consumed(ids: list[int]):
    if not ids:
        return
    with get_conn() as conn:
        conn.execute("UPDATE anomalies SET consumed = TRUE WHERE id = ANY(%s)", (ids,))


def has_recent_open_incident(minutes: int = 5) -> bool:
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM incidents WHERE status = 'OPEN' AND detected_at >= %s LIMIT 1",
            (since,),
        ).fetchone()
        return row is not None


def create_incident(started_at, primary_service, root_cause_service, root_cause_label,
                     confidence, candidates: list[dict], timeline: list[dict]):
    with get_conn() as conn:
        row = conn.execute(
            """INSERT INTO incidents (started_at, primary_service, root_cause_service,
                                        root_cause_label, confidence, severity, status)
               VALUES (%s, %s, %s, %s, %s, 'CRITICAL', 'OPEN') RETURNING id""",
            (started_at, primary_service, root_cause_service, root_cause_label, confidence),
        ).fetchone()
        incident_id = row["id"]
        for c in candidates:
            conn.execute(
                """INSERT INTO incident_candidates (incident_id, candidate_cause, score, evidence)
                   VALUES (%s, %s, %s, %s)""",
                (incident_id, c["cause"], c["score"], Json(c["evidence"])),
            )
        for t in timeline:
            conn.execute(
                "INSERT INTO incident_timeline (incident_id, ts, label) VALUES (%s, %s, %s)",
                (incident_id, t["ts"], t["label"]),
            )
        return incident_id


def attach_ai_report(incident_id, summary, steps):
    with get_conn() as conn:
        conn.execute(
            """UPDATE incidents SET ai_summary = %s, ai_investigation_steps = %s
               WHERE id = %s""",
            (summary, Json(steps), incident_id),
        )


def auto_resolve_stale_incidents(minutes: int = 10):
    """Close incidents that have had no new anomalies for a while."""
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    with get_conn() as conn:
        conn.execute(
            """UPDATE incidents SET status = 'RESOLVED'
               WHERE status = 'OPEN' AND detected_at < %s""",
            (since,),
        )
