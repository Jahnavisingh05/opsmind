"""
Level 2 - Intelligence: anomaly detection.

For each service, we look at the last WINDOW_MINUTES of metrics and
fit an IsolationForest over the feature vector
[cpu_pct, latency_ms, error_rate, memory_mb, conn_pool_pct].

IsolationForest isolates points by random recursive splits; points
that isolate in fewer splits (shorter average path length) are more
anomalous. We use it here instead of a fixed threshold because
"normal" CPU/latency drifts by time of day and by service, so a
static cutoff throws too many false positives - the model adapts to
each service's own recent distribution instead.

We only flag anomalies in the most recent RECENT_SECONDS slice, so
that we detect the *onset* of a problem rather than re-flagging the
same anomalous period every cycle.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
from sklearn.ensemble import IsolationForest

FEATURES = ["cpu_pct", "latency_ms", "error_rate", "memory_mb", "conn_pool_pct"]
WINDOW_MINUTES = 6
RECENT_SECONDS = 15  # only act on anomalies from this recent a slice
MIN_SAMPLES = 8


def _to_matrix(rows):
    return np.array([[r[f] or 0.0 for f in FEATURES] for r in rows])


def detect(metrics_rows):
    """
    metrics_rows: list of dict rows from the `metrics` table (recent window).
    Returns: list of dicts {service, metric_name, value, score, ts} for newly
    detected anomalies in the most recent slice.
    """
    by_service = defaultdict(list)
    for r in metrics_rows:
        by_service[r["service"]].append(r)

    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(seconds=RECENT_SECONDS)

    found = []
    for service, rows in by_service.items():
        rows = sorted(rows, key=lambda r: r["ts"])
        if len(rows) < MIN_SAMPLES:
            continue

        X = _to_matrix(rows)
        clf = IsolationForest(n_estimators=150, contamination=0.2, random_state=42)
        clf.fit(X)
        # anomaly score: higher = more anomalous (sklearn's score_samples is
        # the opposite sign, so we negate it)
        raw_scores = -clf.score_samples(X)
        norm_scores = (raw_scores - raw_scores.min()) / (raw_scores.ptp() + 1e-9)

        for row, score in zip(rows, norm_scores):
            if row["ts"] < recent_cutoff:
                continue
            if score < 0.65:
                continue
            # identify which feature deviates most from the service's own median
            medians = np.median(X, axis=0)
            stds = np.std(X, axis=0) + 1e-6
            z = (np.array([row[f] or 0.0 for f in FEATURES]) - medians) / stds
            worst_idx = int(np.argmax(np.abs(z)))
            found.append({
                "service": service,
                "metric_name": FEATURES[worst_idx],
                "value": row[FEATURES[worst_idx]],
                "score": float(score),
                "ts": row["ts"],
            })
    return found
