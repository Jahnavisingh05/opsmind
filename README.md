# OpsMind — AI Incident Investigation & Root-Cause Analysis Platform

A self-contained microservices stack that generates its own traffic, injects
realistic production incidents, detects anomalies with ML, correlates them
across services, scores root-cause candidates using service topology, and
uses an LLM to turn the evidence into a readable incident report.

Everything below is real, runnable code — not a mockup.

## Quick start

```bash
cd opsmind
cp .env.example .env          # optional: add ANTHROPIC_API_KEY for real LLM summaries
docker compose up --build
```

Then open:
- **Dashboard:** http://localhost:3000
- **API gateway:** http://localhost:8080/api/overview
- **Ingestion service:** http://localhost:8001/health
- **Analysis engine:** http://localhost:8006/health
- **GenAI service:** http://localhost:8007/health

Give it **2–3 minutes**. The traffic generator warms up, runs ~60s of normal
traffic, then injects one of four incident scenarios (DB overload, memory
leak, bad deployment, network latency) for ~90s. The analysis engine polls
every 10s, so you'll typically see your first incident card within the first
injected scenario window.

No `ANTHROPIC_API_KEY` is required to see the whole pipeline work —
`genai-service` falls back to a deterministic templated summary built from
the same evidence an LLM would get. Add the key to get real natural-language
reports.

## What's actually happening (Level 1 → 2 → 3)

```
user-service, payment-service, notification-service   <- business microservices
              ↑ orchestrated by
        order-service  ───────────────► ingestion-service ──► Postgres
              ↑                                                   │
      traffic-generator                                           │
   (load + fault injection)                                       ▼
                                                            analysis-engine
                                                     (Isolation Forest anomaly
                                                      detection → event
                                                      correlation → topology-
                                                      aware root-cause scoring)
                                                                    │
                                                                    ▼
                                                            genai-service
                                                    (LLM incident summary +
                                                     investigation steps)
                                                                    │
                                                                    ▼
                                              api-gateway  ──►  dashboard
```

| Level | Component | What it does |
|---|---|---|
| 🟢 1 — Engineering | `user/order/payment/notification-service`, `ingestion-service`, Postgres, Docker Compose | A real distributed system with a dependency chain (`order → user/payment/notification`) and an HTTP-based telemetry pipeline instead of a static dataset |
| 🟡 2 — Intelligence | `analysis-engine/anomaly_detector.py` | `IsolationForest` fit per-service on a rolling metrics window flags CPU/latency/error-rate/memory/connection-pool outliers |
| 🟡 2 — Intelligence | `analysis-engine/rootcause.py` | Clusters anomalies by time proximity, then scores every affected service as a **candidate cause** using temporal order, service-dependency topology, recent deployments, and error-log volume — this is the "correlation ≠ causation" piece |
| 🔴 3 — AI | `genai-service` | Takes the *already-computed* evidence and produces a natural-language root-cause narrative + investigation checklist (falls back to a template if no API key is set) |

### The four injected incident scenarios
`traffic-generator` cycles through these automatically, exactly matching the
spec:
1. **`db_latency`** — payment-service simulates DB latency + connection-pool exhaustion → cascades into order-service errors
2. **`memory_leak`** — payment-service memory climbs until simulated OOM/restart
3. **`bad_deploy`** — order-service "deploys" v2.4.1 and starts throwing exceptions directly (no downstream cause — tests that your root-cause engine doesn't always blame payment-service)
4. **`network_latency`** — payment-service simulates gateway timeouts

### Root-cause scoring formula
```
score = 0.30·temporal_proximity + 0.25·dependency_topology
      + 0.25·recent_deployment  + 0.20·error_log_volume
```
See `services/analysis-engine/rootcause.py` for the full implementation and
the evidence strings it generates (these are what the dashboard and the
GenAI prompt both consume).

## Suggested build order (if you want to build this yourself, incrementally)

1. **Postgres + schema** (`init-db/01_schema.sql`) — get the data model right first.
2. **ingestion-service** — the one thing everything else depends on.
3. **user/payment/notification/order-service** — get normal traffic flowing end-to-end (`POST /orders`) before adding any faults.
4. **traffic-generator** — confirm you can see `logs` and `metrics` rows accumulating in Postgres (`docker exec -it <postgres-container> psql -U opsmind -d opsmind -c "select * from metrics order by ts desc limit 10;"`).
5. **Fault injection** (`/admin/fault`, `/admin/deploy` endpoints) — trigger scenarios manually with `curl` before wiring the generator's automatic cycle.
6. **anomaly_detector.py** — validate in isolation: pull rows for one service, run `detect()`, check it fires during an injected fault and stays quiet during normal traffic.
7. **rootcause.py** — unit-test `cluster_anomalies` and `score_candidates` with a hand-built fake anomaly list before trusting it on live data.
8. **analysis-engine/main.py** — wire the loop, confirm rows appear in `incidents`.
9. **genai-service** — test with `curl -X POST localhost:8007/summarize -d '{...}'` using a fake payload before relying on the analysis-engine to call it.
10. **api-gateway + dashboard** — last, once there's real data to display.

This mirrors exactly how the "why" of the architecture would come up in an
interview: you can explain what you validated at each stage, not just what
the final diagram looks like.

## Interview talking points this project actually supports
- **Correlation vs. causation:** `rootcause.py`'s scoring is the direct answer to "how did you avoid just blaming whichever service was loudest?"
- **Why IsolationForest:** unsupervised, no labeled incident data needed, adapts per-service instead of a fixed threshold — but be ready to explain its weakness (needs enough recent samples; contamination parameter is a guess, not learned).
- **Why keep GenAI out of the detection path:** hallucination risk — the LLM only narrates evidence the deterministic engine already trusts, and `genai-service/main.py`'s prompt explicitly tells the model to treat evidence as data, not instructions (worth discussing prompt-injection-via-logs even though this version doesn't feed raw log text into the prompt).
- **Scaling to 100 services:** the dependency graph and windowed queries stay O(services × window), but you'd want to replace polling with a message bus (Kafka) so analysis-engine reacts to events instead of scanning Postgres every 10s — call this out as the natural v2.
- **Zero-downtime deploys:** the `/admin/deploy` + `/admin/fault` split mirrors how you'd instrument a real canary — deployment events are recorded independently of whether they caused a fault.

## Extending toward the "advanced version" in the spec
- Swap Postgres polling for **Kafka** topics (`logs`, `metrics`, `deployments`) and make `analysis-engine` a consumer.
- Add **Prometheus + Grafana** by having each service expose `/metrics` in Prometheus format instead of (or alongside) pushing to `ingestion-service`.
- Replace the static `dependency_graph.py` with a graph built from real trace spans (OpenTelemetry).
- Rebuild `dashboard/` as a proper Vite + React app (the current one is deliberately dependency-free vanilla JS/HTML so `docker compose up` has zero extra build steps) — component boundaries would map directly to the sections already in `index.html` (overview cards, incident list, incident detail modal).
- Try **One-Class SVM** alongside IsolationForest and compare false-positive rates as a genuine "which model did you pick and why" story.

## Useful commands

```bash
# Manually trigger fault (bypasses the traffic-generator's automatic cycle)
curl -X POST "http://localhost:8003/admin/fault?mode=db_latency"
curl -X POST "http://localhost:8003/admin/reset"

# Force an analysis cycle immediately instead of waiting up to 10s
curl -X POST http://localhost:8006/run-now

# Inspect the DB directly
docker compose exec postgres psql -U opsmind -d opsmind

# Tail one service's logs
docker compose logs -f payment-service
```
