"""
Static service dependency graph. In a larger system this would be
derived from service-mesh telemetry (e.g. Istio) or an OpenTelemetry
trace graph; a static map is enough to demonstrate topology-aware
root-cause scoring here.

Edge A -> B means "A calls B" / "A depends on B". If B fails, A is a
likely downstream victim, not the root cause.
"""

DEPENDS_ON = {
    "order-service": ["user-service", "payment-service", "notification-service"],
    "payment-service": [],
    "user-service": [],
    "notification-service": [],
}

# reverse map: who depends on me (i.e. who would I take down if I fail)
DEPENDENTS_OF: dict[str, list[str]] = {svc: [] for svc in DEPENDS_ON}
for svc, deps in DEPENDS_ON.items():
    for dep in deps:
        DEPENDENTS_OF.setdefault(dep, []).append(svc)


def is_upstream_of(candidate: str, affected_services: set[str]) -> bool:
    """True if `candidate` has at least one dependent inside affected_services."""
    return any(dep in affected_services for dep in DEPENDENTS_OF.get(candidate, []))
