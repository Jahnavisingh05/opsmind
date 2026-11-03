import asyncio
import os
import random
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from emitter import emit_log, emit_metric, emit_deployment, new_request_id

USER_SVC = os.environ.get("USER_SVC_URL", "http://user-service:8000")
PAYMENT_SVC = os.environ.get("PAYMENT_SVC_URL", "http://payment-service:8000")
NOTIF_SVC = os.environ.get("NOTIF_SVC_URL", "http://notification-service:8000")

STATE = {
    "mode": "normal",     # normal | bad_deploy
    "requests": 0,
    "errors": 0,
}

client = httpx.AsyncClient(timeout=5.0)


async def metrics_loop():
    while True:
        await asyncio.sleep(2)
        error_rate = STATE["errors"] / max(STATE["requests"], 1)
        base_cpu = random.uniform(30, 50)
        base_latency = random.uniform(50, 120)

        cpu = base_cpu
        latency = base_latency
        if STATE["mode"] == "bad_deploy":
            cpu += random.uniform(10, 20)
            latency += random.uniform(200, 500)

        emit_metric(
            cpu_pct=round(cpu, 1),
            latency_ms=round(latency, 1),
            error_rate=round(error_rate, 3),
            memory_mb=round(random.uniform(150, 220), 1),
            conn_pool_pct=0.0,
        )
        STATE["requests"] = int(STATE["requests"] * 0.5)
        STATE["errors"] = int(STATE["errors"] * 0.5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(metrics_loop())
    yield
    task.cancel()


app = FastAPI(title="Order Service", lifespan=lifespan)


class CreateOrder(BaseModel):
    user_id: str
    amount: float


@app.get("/health")
def health():
    return {"status": "ok", "mode": STATE["mode"]}


@app.post("/admin/fault")
def set_fault(mode: str):
    STATE["mode"] = mode
    emit_log("WARN", f"Fault injected: mode={mode}", error_type="FAULT_INJECTION")
    return {"ok": True, "mode": mode}


@app.post("/admin/reset")
def reset_fault():
    STATE["mode"] = "normal"
    emit_log("INFO", "Fault cleared, service back to normal")
    return {"ok": True}


@app.post("/admin/deploy")
def deploy(version: str, description: str = ""):
    emit_deployment(version, description)
    emit_log("INFO", f"Deployed {version}: {description}")
    return {"ok": True}


@app.post("/orders")
async def create_order(req: CreateOrder):
    STATE["requests"] += 1
    request_id = new_request_id()

    # simulate a "bad deployment" that directly raises the order-service error rate
    if STATE["mode"] == "bad_deploy" and random.random() < 0.45:
        STATE["errors"] += 1
        emit_log("ERROR", "Unhandled exception in order validation (regression in v2.4.1)",
                  error_type="APP_EXCEPTION", request_id=request_id)
        raise HTTPException(status_code=500, detail="internal error creating order")

    try:
        resp = await client.get(f"{USER_SVC}/users/{req.user_id}")
        resp.raise_for_status()
    except httpx.HTTPError:
        STATE["errors"] += 1
        emit_log("ERROR", f"User lookup failed for {req.user_id}", error_type="USER_LOOKUP_FAILED",
                  request_id=request_id)
        raise HTTPException(status_code=502, detail="user lookup failed")

    order_id = new_request_id()
    try:
        resp = await client.post(f"{PAYMENT_SVC}/charge",
                                  json={"order_id": order_id, "amount": req.amount})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        STATE["errors"] += 1
        emit_log("ERROR", f"Payment failed for order {order_id}: {e}",
                  error_type="PAYMENT_FAILED", request_id=request_id)
        raise HTTPException(status_code=502, detail="payment failed")

    try:
        await client.post(f"{NOTIF_SVC}/notify",
                           json={"order_id": order_id, "message": "Order confirmed"})
    except httpx.HTTPError:
        pass  # notifications are best-effort, not critical path

    emit_log("INFO", f"Order {order_id} created for user {req.user_id}", request_id=request_id)
    return {"ok": True, "order_id": order_id}
