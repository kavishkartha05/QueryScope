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


async def run_llm_benchmark(
    endpoint_url: str,
    api_key: str,
    model: str,
    prompt: str,
    num_requests: int,
    concurrency: int,
) -> dict:
    """
    Benchmark an OpenAI-compatible streaming LLM endpoint.

    Measures time-to-first-token (TTFT) and total generation time per request
    by consuming the SSE stream and timestamping the first and last chunks.

    Returns:
        ttft_latencies:        ms from request send to first streamed chunk
        total_latencies:       ms from request send to last chunk
        tokens_per_second_list: chunks/sec per request (chunk count is a proxy
                                for tokens — actual tokenisation isn't available
                                without a tokeniser; chunk count is close enough
                                for relative comparisons between runs)
        error_count:           requests that failed or returned non-2xx
        total_wall_time:       wall-clock seconds for the entire run
    """
    semaphore = asyncio.Semaphore(concurrency)
    ttft_latencies: list[float] = []
    total_latencies: list[float] = []
    tokens_per_second_list: list[float] = []
    error_count = 0
    lock = asyncio.Lock()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }

    # LLM endpoints can be slow — 120 s covers long generations without
    # hanging forever on a stalled connection.
    async with httpx.AsyncClient(headers=headers, timeout=120.0) as client:

        async def _single_llm_request() -> None:
            nonlocal error_count
            async with semaphore:
                start = time.perf_counter()
                ttft_ms: float | None = None
                chunk_count = 0
                is_error = False

                try:
                    # stream=True keeps the response body open so we can
                    # timestamp individual SSE chunks as they arrive.
                    async with client.stream("POST", endpoint_url, json=payload) as response:
                        if response.status_code >= 400:
                            is_error = True
                        else:
                            async for chunk in response.aiter_bytes():
                                if chunk:
                                    if ttft_ms is None:
                                        # First non-empty chunk = first token arrived.
                                        ttft_ms = (time.perf_counter() - start) * 1000
                                    chunk_count += 1
                except (httpx.RequestError, httpx.HTTPStatusError):
                    is_error = True

                total_ms = (time.perf_counter() - start) * 1000
                total_secs = total_ms / 1000

                async with lock:
                    if is_error or ttft_ms is None:
                        error_count += 1
                        # Still record sentinel values so list lengths stay
                        # aligned with num_requests for easier post-processing.
                        ttft_latencies.append(0.0)
                        total_latencies.append(total_ms)
                        tokens_per_second_list.append(0.0)
                    else:
                        ttft_latencies.append(ttft_ms)
                        total_latencies.append(total_ms)
                        # Avoid ZeroDivision on pathologically fast responses.
                        tps = chunk_count / total_secs if total_secs > 0 else 0.0
                        tokens_per_second_list.append(tps)

        wall_start = time.perf_counter()
        await asyncio.gather(*[_single_llm_request() for _ in range(num_requests)])
        total_wall_time = time.perf_counter() - wall_start

    return {
        "ttft_latencies": ttft_latencies,
        "total_latencies": total_latencies,
        "tokens_per_second_list": tokens_per_second_list,
        "error_count": error_count,
        "total_wall_time": total_wall_time,
    }
