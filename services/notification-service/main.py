import asyncio
import random
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from emitter import emit_log, emit_metric


async def metrics_loop():
    while True:
        await asyncio.sleep(2)
        emit_metric(
            cpu_pct=round(random.uniform(10, 25), 1),
            latency_ms=round(random.uniform(5, 20), 1),
            error_rate=0.0,
            memory_mb=round(random.uniform(80, 110), 1),
            conn_pool_pct=0.0,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(metrics_loop())
    yield
    task.cancel()


app = FastAPI(title="Notification Service", lifespan=lifespan)


class Notify(BaseModel):
    order_id: str
    message: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/notify")
async def notify(req: Notify):
    await asyncio.sleep(random.uniform(0.01, 0.03))
    emit_log("INFO", f"Notification sent for order {req.order_id}: {req.message}")
    return {"ok": True}
