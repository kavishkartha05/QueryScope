"""
Seed demo runs (access_code_id NULL) and a demo baseline. Safe to run repeatedly.

Run from the backend/ directory:

    python scripts/seed_demo.py [--target-url URL] [--index]

Idempotency:
  - Each demo run has a fixed UUID derived from its name; existing rows are
    left untouched, so re-running never duplicates or rewrites them.
  - The baseline flag is only set when no demo baseline exists, so a baseline
    an admin pinned later is never overridden.

--index also writes each newly created run to Azure AI Search as a demo
document (needs AZURE_SEARCH_* and OPENAI_API_KEY). Without it, the runs exist
in Postgres only and diagnose will not find them semantically.
"""
import argparse
import asyncio
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from sqlalchemy import select  # noqa: E402

from app.core.db import AsyncSessionLocal  # noqa: E402
from app.models.run import Metrics, Run, RunStatus  # noqa: E402
from app.services.aggregator import compute_metrics  # noqa: E402

_NAMESPACE = uuid.UUID("5f1d6a52-2f0c-4a53-9d6e-0d7c2f6f0a11")

# (name, days_ago, requests, concurrency, median_ms, spread_ms, error_count, is_baseline)
_SCENARIOS = [
    ("healthy-baseline", 6, 200, 10, 120.0, 25.0, 0, True),
    ("steady-state", 4, 200, 10, 126.0, 28.0, 1, False),
    ("slow-database-regression", 2, 200, 10, 310.0, 90.0, 4, False),
    ("error-burst", 1, 200, 10, 140.0, 40.0, 38, False),
]


def _latencies(name: str, count: int, median: float, spread: float) -> list[float]:
    # Seeded per scenario so the data is identical on every machine and run.
    rng = random.Random(name)
    values = []
    for _ in range(count):
        # Log-normal gives the long right tail real latency data has.
        sample = median * rng.lognormvariate(0.0, spread / (median * 2.0))
        values.append(round(sample, 3))
    return values


async def seed(target_url: str, index: bool) -> None:
    created = []
    async with AsyncSessionLocal() as session:
        existing_baseline = await session.execute(
            select(Run.id).where(Run.access_code_id.is_(None), Run.is_baseline.is_(True))
        )
        has_baseline = existing_baseline.first() is not None
        now = datetime.now(timezone.utc)

        for name, days_ago, requests, conc, median, spread, errors, wants_baseline in _SCENARIOS:
            run_id = uuid.uuid5(_NAMESPACE, name)
            if await session.get(Run, run_id) is not None:
                print(f"skip   {name} (already present)")
                continue

            latencies = _latencies(name, requests, median, spread)
            total_time = sum(latencies) / 1000.0 / conc
            agg = compute_metrics(latencies, total_time, requests, errors)

            set_baseline = wants_baseline and not has_baseline
            if set_baseline:
                has_baseline = True
            run = Run(
                id=run_id,
                target_url=target_url,
                method="GET",
                num_requests=requests,
                concurrency=conc,
                status=RunStatus.done,
                created_at=now - timedelta(days=days_ago),
                is_baseline=set_baseline,
                access_code_id=None,
            )
            session.add(run)
            # Flush so the runs row exists before the metrics FK row is added.
            await session.flush()
            session.add(Metrics(run_id=run_id, latencies=latencies, **agg))
            created.append((run, agg))
            print(f"create {name}")
        await session.commit()

    if index:
        from app.services.indexer import index_run

        for run, agg in created:
            await index_run(
                run_id=run.id,
                target_url=run.target_url,
                method=run.method,
                num_requests=run.num_requests,
                p50=agg["p50"],
                p95=agg["p95"],
                p99=agg["p99"],
                throughput=agg["throughput"],
                error_rate=agg["error_rate"],
                created_at=run.created_at,
                access_code_id="demo",
            )
            print(f"index  {run.id}")
    print(f"Done. {len(created)} created.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed QueryScope demo runs")
    parser.add_argument("--target-url", default="https://httpbin.org/get")
    parser.add_argument("--index", action="store_true", help="also index into Azure AI Search")
    args = parser.parse_args()
    asyncio.run(seed(args.target_url, args.index))


if __name__ == "__main__":
    main()
