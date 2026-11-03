import asyncio
import os
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

import db
from anomaly_detector import detect
from rootcause import cluster_anomalies, score_candidates

GENAI_URL = os.environ.get("GENAI_URL", "http://genai-service:8000")
CYCLE_SECONDS = int(os.environ.get("CYCLE_SECONDS", "10"))

_last_run_info = {"last_run": None, "anomalies_found": 0, "incidents_created": 0}


async def call_genai(incident_id, root_cause_service, root_cause_label, candidates, timeline):
    payload = {
        "incident_id": incident_id,
        "root_cause_service": root_cause_service,
        "confidence": candidates[0]["score"] if candidates else 0,
        "candidates": candidates,
        "timeline": [{"ts": t["ts"].isoformat(), "label": t["label"]} for t in timeline],
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{GENAI_URL}/summarize", json=payload)
            resp.raise_for_status()
            data = resp.json()
            db.attach_ai_report(incident_id, data["summary"], data["investigation_steps"])
    except Exception as e:
        db.attach_ai_report(
            incident_id,
            f"(GenAI layer unavailable: {e}) Root cause candidate: {root_cause_service}.",
            ["Check GENAI_URL / ANTHROPIC_API_KEY configuration", "Review evidence in the dashboard"],
        )


async def run_cycle():
    metrics_rows = db.recent_metrics(minutes=6)
    new_anomalies = detect(metrics_rows)
    for a in new_anomalies:
        db.insert_anomaly(a["service"], a["metric_name"], a["value"], a["score"])
    _last_run_info["anomalies_found"] = len(new_anomalies)

    pending = db.unconsumed_anomalies(minutes=10)
    if not pending:
        db.auto_resolve_stale_incidents()
        return

    clusters = cluster_anomalies(pending, gap_seconds=90)
    deployments = db.recent_deployments(minutes=15)
    error_logs = db.recent_logs(minutes=10, severity="ERROR")

    created = 0
    for cluster in clusters:
        if len(cluster) < 2 and not db.has_recent_open_incident(minutes=1):
            # a single lone anomaly isn't enough signal yet - wait for corroboration
            continue

        candidates, timeline, incident_start = score_candidates(cluster, deployments, error_logs)
        if db.has_recent_open_incident(minutes=2):
            db.mark_anomalies_consumed([a["id"] for a in cluster])
            continue

        top = candidates[0]
        affected_services = sorted({a["service"] for a in cluster})
        incident_id = db.create_incident(
            started_at=incident_start,
            primary_service=affected_services[-1] if affected_services else None,
            root_cause_service=top["cause"],
            root_cause_label=f"{top['cause']} degradation",
            confidence=round(top["score"] * 100, 1),
            candidates=candidates,
            timeline=timeline,
        )
        db.mark_anomalies_consumed([a["id"] for a in cluster])
        created += 1
        await call_genai(incident_id, top["cause"], top["cause"], candidates, timeline)

    _last_run_info["incidents_created"] = created
    db.auto_resolve_stale_incidents()


async def loop_forever():
    await asyncio.sleep(15)  # let the stack warm up and produce initial metrics
    while True:
        try:
            await run_cycle()
        except Exception as e:
            print(f"[analysis-engine] cycle error: {e}")
        _last_run_info["last_run"] = time.time()
        await asyncio.sleep(CYCLE_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(loop_forever())
    yield
    task.cancel()


app = FastAPI(title="OpsMind Analysis Engine", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", **_last_run_info}


@app.post("/run-now")
async def run_now():
    await run_cycle()
    return {"ok": True, **_last_run_info}
