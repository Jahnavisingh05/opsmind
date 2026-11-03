import asyncio
import random
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from emitter import emit_log, emit_metric

USERS = {str(i): {"id": str(i), "name": f"user{i}"} for i in range(1, 51)}


async def metrics_loop():
    while True:
        await asyncio.sleep(2)
        emit_metric(
            cpu_pct=round(random.uniform(20, 40), 1),
            latency_ms=round(random.uniform(15, 45), 1),
            error_rate=0.0,
            memory_mb=round(random.uniform(120, 160), 1),
            conn_pool_pct=round(random.uniform(5, 20), 1),
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(metrics_loop())
    yield
    task.cancel()


app = FastAPI(title="User Service", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/users/{user_id}")
async def get_user(user_id: str):
    await asyncio.sleep(random.uniform(0.01, 0.04))
    user = USERS.get(user_id)
    if not user:
        emit_log("WARN", f"User {user_id} not found", error_type="NOT_FOUND")
        raise HTTPException(status_code=404, detail="user not found")
    return user
