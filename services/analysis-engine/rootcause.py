"""
Level 2/3 - Event correlation + root-cause scoring.

Given a cluster of anomalies that happened close together in time,
this module scores every affected service as a *candidate cause* and
explains its reasoning, rather than just naming whichever service is
loudest. That distinction -- correlation vs causation -- is the whole
point of the project.

Scoring signals (each 0..1, combined with weights):
  temporal   - did this service's anomaly happen *first*?
  dependency - do OTHER affected services depend on this one? (topology)
  deploys    - was there a recent deployment to this service?
  errors     - how many ERROR log lines did this service produce?
"""
from datetime import timedelta

from dependency_graph import is_upstream_of, DEPENDS_ON

WEIGHTS = {
    "temporal": 0.30,
    "dependency": 0.25,
    "deploys": 0.25,
    "errors": 0.20,
}


def cluster_anomalies(anomalies, gap_seconds=90):
    """Group a time-ordered list of anomalies into incident clusters: any
    anomaly within `gap_seconds` of the previous one joins the same cluster."""
    if not anomalies:
        return []
    anomalies = sorted(anomalies, key=lambda a: a["ts"])
    clusters = [[anomalies[0]]]
    for a in anomalies[1:]:
        if (a["ts"] - clusters[-1][-1]["ts"]).total_seconds() <= gap_seconds:
            clusters[-1].append(a)
        else:
            clusters.append([a])
    return clusters


def score_candidates(cluster, deployments, error_logs):
    """cluster: list of anomaly dicts. Returns (candidates, timeline, evidence_by_service)."""
    services = sorted({a["service"] for a in cluster})
    incident_start = min(a["ts"] for a in cluster)

    # first-anomaly time per service -> temporal score (earlier = higher)
    first_ts = {s: min(a["ts"] for a in cluster if a["service"] == s) for s in services}
    span = max((t - incident_start).total_seconds() for t in first_ts.values()) or 1.0

    # deployments to any of these services within 10 min before incident start
    recent_deploys = {
        d["service"]: d for d in deployments
        if d["service"] in services
        and 0 <= (incident_start - d["ts"]).total_seconds() <= 600
    }

    # error log counts per service within the incident window
    window_start = incident_start - timedelta(seconds=30)
    window_end = max(a["ts"] for a in cluster) + timedelta(seconds=30)
    error_counts = {s: 0 for s in services}
    for log in error_logs:
        if log["service"] in services and window_start <= log["ts"] <= window_end \
                and log["severity"] == "ERROR":
            error_counts[log["service"]] += 1
    max_errors = max(error_counts.values()) or 1

    candidates = []
    for s in services:
        temporal_score = 1.0 - ((first_ts[s] - incident_start).total_seconds() / span)
        dependency_score = 1.0 if is_upstream_of(s, set(services)) else 0.35
        deploy_score = 1.0 if s in recent_deploys else 0.0
        error_score = error_counts[s] / max_errors

        final = (
            WEIGHTS["temporal"] * temporal_score
            + WEIGHTS["dependency"] * dependency_score
            + WEIGHTS["deploys"] * deploy_score
            + WEIGHTS["errors"] * error_score
        )

        evidence = []
        if temporal_score > 0.8:
            evidence.append(f"Anomaly in {s} was the earliest signal in this cluster")
        if dependency_score == 1.0:
            downstream = [d for d in DEPENDS_ON if s in DEPENDS_ON.get(d, [])]
            if downstream:
                evidence.append(f"{s} is a dependency of {', '.join(downstream)}, "
                                 f"which also showed anomalies")
        if s in recent_deploys:
            dep = recent_deploys[s]
            evidence.append(f"Deployment {dep['version']} to {s} occurred "
                             f"{int((incident_start - dep['ts']).total_seconds())}s before impact")
        if error_counts[s] > 0:
            evidence.append(f"{error_counts[s]} ERROR log lines from {s} during the incident window")
        anomaly_metrics = sorted({a["metric_name"] for a in cluster if a["service"] == s})
        if anomaly_metrics:
            evidence.append(f"Abnormal metric(s) in {s}: {', '.join(anomaly_metrics)}")

        candidates.append({
            "cause": s,
            "score": round(final, 3),
            "evidence": evidence,
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)

    timeline = []
    for a in sorted(cluster, key=lambda a: a["ts"]):
        timeline.append({"ts": a["ts"],
                          "label": f"{a['service']}: anomalous {a['metric_name']} "
                                   f"(value={a['value']}, score={a['score']:.2f})"})
    for s, d in recent_deploys.items():
        timeline.append({"ts": d["ts"], "label": f"Deployment {d['version']} to {s}: {d['description']}"})
    timeline.sort(key=lambda t: t["ts"])

    return candidates, timeline, incident_start
