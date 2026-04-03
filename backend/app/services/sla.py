"""SLA threshold evaluation — purely algorithmic, no AI involved."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.run import SlaConfig, SlaResult


def evaluate_sla(
    config: "SlaConfig",
    p50: float | None,
    p95: float | None,
    p99: float | None,
    avg_latency_ms: float | None,
    error_rate_pct: float | None,
) -> "SlaResult":
    """
    Evaluate configured thresholds against actual measured values.

    A threshold passes when actual <= target.  If the corresponding metric
    could not be measured (None), the threshold is automatically marked fail.
    Returns a SlaResult whose overall status is None only when no thresholds
    were actually configured (i.e. the SlaConfig is all-None).
    """
    # Local import keeps heavy schema imports out of module-load time for
    # callers that import this module before the app is fully initialised.
    from app.schemas.run import SlaResult, SlaThresholdResult

    # Map (metric_key, threshold, actual_value) triples.
    checks: list[tuple[str, float | None, float | None]] = [
        ("p50_ms", config.p50_ms, p50),
        ("p95_ms", config.p95_ms, p95),
        ("p99_ms", config.p99_ms, p99),
        ("avg_latency_ms", config.avg_latency_ms, avg_latency_ms),
        ("error_rate_pct", config.error_rate_pct, error_rate_pct),
    ]

    thresholds: list[SlaThresholdResult] = []
    for metric, target, actual in checks:
        if target is None:
            continue  # threshold not configured — skip

        if actual is None:
            # Metric could not be measured (e.g. all requests errored before
            # latency data was recorded).  Treat as automatic fail.
            thresholds.append(
                SlaThresholdResult(
                    metric=metric,
                    target=target,
                    actual=0.0,
                    status="fail",
                    delta=0.0 - target,
                )
            )
        else:
            verdict = "pass" if actual <= target else "fail"
            thresholds.append(
                SlaThresholdResult(
                    metric=metric,
                    target=target,
                    actual=round(actual, 4),
                    status=verdict,
                    delta=round(actual - target, 4),
                )
            )

    if not thresholds:
        overall = None
    else:
        overall = "pass" if all(t.status == "pass" for t in thresholds) else "fail"

    return SlaResult(status=overall, thresholds=thresholds)
