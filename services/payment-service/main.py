import asyncio
import os
import random
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from emitter import emit_log, emit_metric, emit_deployment

SERVICE = "payment-service"

# ---- mutable fault state, changed by the traffic-generator / admin API ----
STATE = {
    "mode": "normal",       # normal | db_latency | memory_leak | network_latency
    "started_at": time.time(),
    "requests": 0,
    "errors": 0,
    "conn_pool_used": 0,
    "conn_pool_max": 20,
    "memory_mb": 180.0,
}


async def metrics_loop():
    while True:
        await asyncio.sleep(2)
        mode = STATE["mode"]
        base_cpu = random.uniform(35, 55)
        base_latency = random.uniform(60, 140)
        error_rate = STATE["errors"] / max(STATE["requests"], 1)
        conn_pool_pct = (STATE["conn_pool_used"] / STATE["conn_pool_max"]) * 100

        cpu = base_cpu
        latency = base_latency
        memory = STATE["memory_mb"]

        if mode == "db_latency":
            latency = base_latency + random.uniform(1800, 2600)
            cpu = base_cpu + random.uniform(20, 35)
        elif mode == "memory_leak":
            STATE["memory_mb"] += random.uniform(15, 30)
            memory = STATE["memory_mb"]
            cpu = base_cpu + random.uniform(5, 15)
        elif mode == "network_latency":
            latency = base_latency + random.uniform(600, 1400)

        emit_metric(
            cpu_pct=round(cpu, 1),
            latency_ms=round(latency, 1),
            error_rate=round(error_rate, 3),
            memory_mb=round(memory, 1),
            conn_pool_pct=round(conn_pool_pct, 1),
        )
        # decay error/request counters so error_rate reflects recent window
        STATE["requests"] = int(STATE["requests"] * 0.5)
        STATE["errors"] = int(STATE["errors"] * 0.5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(metrics_loop())
    yield
    task.cancel()


app = FastAPI(title="Payment Service", lifespan=lifespan)


class ChargeRequest(BaseModel):
    order_id: str
    amount: float


@app.get("/health")
def health():
    return {"status": "ok", "mode": STATE["mode"]}


@app.post("/admin/fault")
def set_fault(mode: str):
    STATE["mode"] = mode
    if mode == "memory_leak":
        STATE["memory_mb"] = 180.0
    emit_log("WARN", f"Fault injected: mode={mode}", error_type="FAULT_INJECTION")
    return {"ok": True, "mode": mode}


@app.post("/admin/reset")
def reset_fault():
    STATE["mode"] = "normal"
    STATE["memory_mb"] = 180.0
    STATE["conn_pool_used"] = 0
    emit_log("INFO", "Fault cleared, service back to normal")
    return {"ok": True}


@app.post("/admin/deploy")
def deploy(version: str, description: str = ""):
    emit_deployment(version, description)
    emit_log("INFO", f"Deployed {version}: {description}")
    return {"ok": True}


@app.post("/charge")
async def charge(req: ChargeRequest):
    STATE["requests"] += 1
    request_id = None

    if STATE["mode"] == "db_latency":
        STATE["conn_pool_used"] = min(STATE["conn_pool_max"], STATE["conn_pool_used"] + 2)
        await asyncio.sleep(random.uniform(1.8, 2.8))
        if STATE["conn_pool_used"] >= STATE["conn_pool_max"]:
            STATE["errors"] += 1
            emit_log("ERROR", "Database connection timeout", error_type="DB_TIMEOUT",
                      request_id=request_id)
            raise HTTPException(status_code=504, detail="database connection timeout")

    elif STATE["mode"] == "network_latency":
        await asyncio.sleep(random.uniform(0.6, 1.4))
        if random.random() < 0.4:
            STATE["errors"] += 1
            emit_log("ERROR", "Payment gateway timeout", error_type="NETWORK_TIMEOUT",
                      request_id=request_id)
            raise HTTPException(status_code=504, detail="payment gateway timeout")

    elif STATE["mode"] == "memory_leak" and STATE["memory_mb"] > 900:
        STATE["errors"] += 1
        emit_log("ERROR", "Container OOM - restarting", error_type="OOM_KILL",
                  request_id=request_id)
        STATE["memory_mb"] = 180.0
        raise HTTPException(status_code=503, detail="service restarting")

    else:
        await asyncio.sleep(random.uniform(0.03, 0.09))

    STATE["conn_pool_used"] = max(0, STATE["conn_pool_used"] - 1)
    emit_log("INFO", f"Charged order {req.order_id} amount={req.amount}")
    return {"ok": True, "order_id": req.order_id, "charged": req.amount}
