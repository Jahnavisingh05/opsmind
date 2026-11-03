"""
Continuously drives traffic through order-service, and on a timer
injects one of the four incident scenarios described in the OpsMind
spec, then resets back to normal. This is what turns the stack into
a living, self-generating incident dataset instead of a static demo.
"""
import asyncio
import os
import random
import time

import httpx

ORDER_SVC = os.environ.get("ORDER_SVC_URL", "http://order-service:8000")
PAYMENT_SVC = os.environ.get("PAYMENT_SVC_URL", "http://payment-service:8000")

SCENARIOS = ["db_latency", "memory_leak", "bad_deploy", "network_latency"]


async def send_orders(client: httpx.AsyncClient, n: int):
    tasks = []
    for _ in range(n):
        user_id = str(random.randint(1, 50))
        amount = round(random.uniform(5, 500), 2)
        tasks.append(client.post(f"{ORDER_SVC}/orders",
                                  json={"user_id": user_id, "amount": amount}))
    await asyncio.gather(*tasks, return_exceptions=True)


async def reset_all(client: httpx.AsyncClient):
    for url in (f"{ORDER_SVC}/admin/reset", f"{PAYMENT_SVC}/admin/reset"):
        try:
            await client.post(url)
        except httpx.HTTPError:
            pass


async def trigger_incident(client: httpx.AsyncClient, scenario: str):
    print(f"[traffic-gen] >>> injecting incident: {scenario}")
    if scenario == "bad_deploy":
        await client.post(f"{ORDER_SVC}/admin/deploy",
                           params={"version": "v2.4.1",
                                   "description": "refactor order validation logic"})
        await client.post(f"{ORDER_SVC}/admin/fault", params={"mode": "bad_deploy"})
    elif scenario == "db_latency":
        await client.post(f"{PAYMENT_SVC}/admin/deploy",
                           params={"version": "v1.9.0", "description": "add loyalty-points query"})
        await client.post(f"{PAYMENT_SVC}/admin/fault", params={"mode": "db_latency"})
    elif scenario == "memory_leak":
        await client.post(f"{PAYMENT_SVC}/admin/fault", params={"mode": "memory_leak"})
    elif scenario == "network_latency":
        await client.post(f"{PAYMENT_SVC}/admin/fault", params={"mode": "network_latency"})


async def main():
    async with httpx.AsyncClient(timeout=5.0) as client:
        # wait for stack to be up
        await asyncio.sleep(int(os.environ.get("STARTUP_DELAY", "8")))

        cycle = 0
        incident_duration = int(os.environ.get("INCIDENT_DURATION_SEC", "90"))
        normal_duration = int(os.environ.get("NORMAL_DURATION_SEC", "60"))

        while True:
            cycle += 1
            print(f"[traffic-gen] cycle {cycle}: normal traffic for {normal_duration}s")
            t_end = time.time() + normal_duration
            while time.time() < t_end:
                await send_orders(client, n=random.randint(3, 8))
                await asyncio.sleep(1)

            scenario = random.choice(SCENARIOS)
            await trigger_incident(client, scenario)

            t_end = time.time() + incident_duration
            while time.time() < t_end:
                await send_orders(client, n=random.randint(3, 8))
                await asyncio.sleep(1)

            print("[traffic-gen] <<< resolving incident, resetting to normal")
            await reset_all(client)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
