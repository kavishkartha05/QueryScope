import numpy as np


def compute_metrics(
    latencies: list[float],
    total_time: float,
    num_requests: int,
    error_count: int,
) -> dict:
    """
    Compute summary statistics from raw benchmark results.

    Args:
        latencies:    per-request latency in milliseconds
        total_time:   wall-clock duration of the entire run in seconds
        num_requests: total requests attempted (denominator for error_rate)
        error_count:  number of failed requests

    Returns a dict ready to unpack into a Metrics ORM row.
    """
    arr = np.array(latencies, dtype=float)

    # np.percentile interpolates between samples, which gives more accurate
    # tail estimates than a nearest-rank approximation, especially for small
    # num_requests values.
    p50, p95, p99 = (float(np.percentile(arr, q)) for q in (50, 95, 99))

    # throughput counts all attempts (including errors) — consistent with how
    # load-testing tools like wrk and k6 report req/s.
    throughput = num_requests / total_time

    # 0.0–1.0 fraction; caller validates num_requests >= 1 so no ZeroDivision.
    error_rate = error_count / num_requests

    return {
        "p50": p50,
        "p95": p95,
        "p99": p99,
        "throughput": throughput,
        "error_rate": error_rate,
    }
