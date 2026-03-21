import asyncio
import time

import httpx


async def run_benchmark(
    target_url: str,
    method: str,
    num_requests: int,
    concurrency: int,
    headers: dict | None = None,
    body: dict | None = None,
) -> dict:
    """
    Fire num_requests against target_url with bounded concurrency.

    Returns:
        latencies:   per-request latency in milliseconds (one entry per request,
                     including errored ones so callers can correlate with error_count)
        error_count: number of requests that raised a network error or returned 5xx
        total_time:  wall-clock seconds for the entire run
    """
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    error_count = 0
    # Lock guards appends to the shared lists from concurrent tasks.
    lock = asyncio.Lock()

    # A single client is reused across all tasks — connection pooling is
    # handled internally by httpx and is much cheaper than creating a client
    # per request.
    async with httpx.AsyncClient(headers=headers or {}, timeout=30.0) as client:

        async def _single_request() -> None:
            nonlocal error_count
            async with semaphore:
                start = time.perf_counter()
                is_error = False
                try:
                    response = await client.request(
                        method.upper(),
                        target_url,
                        # Send JSON body only for methods that carry a payload.
                        # Sending a body on GET is technically allowed but
                        # confuses many servers and proxies.
                        json=body if method.upper() not in ("GET", "HEAD") else None,
                    )
                    # Treat server-side errors as benchmark failures so callers
                    # can distinguish "request completed" from "request succeeded".
                    if response.status_code >= 500:
                        is_error = True
                except (httpx.RequestError, httpx.HTTPStatusError):
                    # Network-level failures (timeout, connection refused, etc.)
                    is_error = True
                finally:
                    # Record latency regardless of outcome so the distribution
                    # reflects real-world tail behaviour under errors.
                    elapsed_ms = (time.perf_counter() - start) * 1000

                async with lock:
                    latencies.append(elapsed_ms)
                    if is_error:
                        error_count += 1

        wall_start = time.perf_counter()

        # Create all tasks up-front so httpx can pipeline and reuse connections
        # rather than waiting for each semaphore slot to drain before scheduling
        # the next batch.
        await asyncio.gather(*[_single_request() for _ in range(num_requests)])

        total_time = time.perf_counter() - wall_start

    return {
        "latencies": latencies,
        "error_count": error_count,
        "total_time": total_time,
    }
