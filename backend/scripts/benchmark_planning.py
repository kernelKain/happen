"""Measure the planning path against fixtures. It spends no SerpApi credits.

Every provider call here is a local fake with a scripted delay, so the numbers
describe the planner's own overhead and its deadline behaviour. They are not a
live measurement and must never be reported as one: real network latency,
SerpApi response time, and cold-start model loading are all absent here. The
only honest claims from this script are the relative ones, such as that a
cached swap costs no provider call and stays inside its target.

Run it with:

    cd backend && uv run python scripts/benchmark_planning.py
    cd backend && uv run python scripts/benchmark_planning.py --json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from happen_api.planning.deadline import CACHED_SECONDS, PLANNING_DEADLINE_SECONDS
from happen_api.planning.discovery import _place_from_record
from happen_api.planning.itinerary import assemble_itinerary
from happen_api.planning.limits import (
    PLAN_BILLED_REQUEST_LIMIT,
    AllowanceStore,
    MeteredProvider,
    PlanCache,
)
from happen_api.providers.serpapi.client import SerpApiFailure

WARMUP = 3
RUNS = 40
_DATE = date(2026, 10, 5)
from datetime import time as clock_time

_START = clock_time(19, 0)
_WHEN = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)


@dataclass
class FakeProvider:
    """A scripted provider. It opens no socket and spends no credit."""

    credit_limit: int = PLAN_BILLED_REQUEST_LIMIT
    calls: list[str] = field(default_factory=list)
    credits_charged: int = 0
    delay: float = 0.0

    def set_attempt_gate(self, gate: object) -> None:
        self._gate = gate

    def _charge(self, name: str) -> None:
        if self.delay:
            time.sleep(self.delay)
        self.calls.append(name)
        self.credits_charged += 1
        gate = getattr(self, "_gate", None)
        if callable(gate):
            gate()

    def search_places(self, *_args: object, **_kwargs: object) -> object:
        self._charge("search_places")
        return _snapshot()

    def place_details(self, **_kwargs: object) -> object:
        self._charge("place_details")
        return _snapshot()

    def place_reviews(self, **_kwargs: object) -> object:
        self._charge("place_reviews")
        return _snapshot()

    def web_search(self, *_args: object, **_kwargs: object) -> object:
        self._charge("web_search")
        return _snapshot()

    def lookup_maps_coordinates(self, _query: str) -> object:
        self._charge("lookup_maps_coordinates")
        return []

    def supported_locations(self, _query: str, limit: int = 5) -> object:
        # Free call. It must never be charged.
        self.calls.append("supported_locations")
        return []


def _snapshot() -> object:
    class _Snapshot:
        payload: ClassVar[dict[str, object]] = {"local_results": []}

    return _Snapshot()


def _percentiles(samples: list[float]) -> dict[str, float]:
    """Return p50 and p95 in milliseconds without assuming a distribution."""

    ordered = sorted(samples)
    return {
        "p50_ms": round(statistics.median(ordered) * 1000, 3),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] * 1000, 3),
        "min_ms": round(ordered[0] * 1000, 3),
        "max_ms": round(ordered[-1] * 1000, 3),
    }


def benchmark_cached_plan(delay: float = 0.0) -> dict[str, object]:
    """Measure a plan served from the normalized evidence cache.

    This is the cached-swap latency path: it builds a candidate pool once, then
    assembles the itinerary from stored evidence with no provider call at all.
    """

    store = AllowanceStore()
    token = store.issue()
    provider = FakeProvider(delay=delay)
    metered = MeteredProvider(provider, store, token)
    cache = PlanCache()
    key = "a" * 64
    metered.search_places("dinner in Tokyo")
    cache.put(key, _pool())

    def once() -> float:
        started = time.perf_counter()
        cached = cache.get(key)
        assert cached is not None
        assemble_itinerary(
            cached.places,
            _intents(),
            local_date=_DATE,
            local_start=_START,
            retrieved_at=_WHEN,
        )
        return time.perf_counter() - started

    for _ in range(WARMUP):
        once()
    samples = [once() for _ in range(RUNS)]
    result = _percentiles(samples)
    result["provider_calls"] = 0
    result["target_ms"] = CACHED_SECONDS * 1000
    result["within_target"] = result["p95_ms"] <= CACHED_SECONDS * 1000
    return result


def benchmark_metered_call(delay: float) -> dict[str, object]:
    """Measure one metered billed call, including the per-attempt accounting."""

    def once() -> float:
        store = AllowanceStore()
        token = store.issue()
        provider = FakeProvider(delay=delay)
        metered = MeteredProvider(provider, store, token)
        started = time.perf_counter()
        try:
            metered.search_places("dinner in Tokyo")
        except SerpApiFailure as failure:
            # The scripted fake refuses every search. The refusal is the point
            # of this measurement, so it is expected rather than an error.
            if failure.code != "CREDIT_BUDGET_EXCEEDED":
                raise
        return time.perf_counter() - started

    for _ in range(WARMUP):
        once()
    samples = [once() for _ in range(RUNS)]
    result = _percentiles(samples)
    result["provider_calls"] = 1
    return result


def _pool() -> object:
    from happen_api.planning.discovery import CandidatePool

    return CandidatePool(places=[_place("Kura", "kura", 4.8), _place("Nami", "nami", 4.6)])


def _place(name: str, place_id: str, rating: float) -> object:
    record = {
        "title": name,
        "place_id": place_id,
        "data_id": f"data-{place_id}",
        "address": "Tokyo",
        "gps_coordinates": {"latitude": 35.6764, "longitude": 139.65},
        "website": "https://venue.example",
        "link": "https://maps.example/venue",
        "rating": rating,
        "reviews": 40,
        "operating_hours": {"monday": "6:00 PM–11:00 PM"},
    }
    found = _place_from_record(record, _dinner())
    assert found is not None
    return found


def _dinner() -> object:
    from happen_api.planning.contracts import IntentKind

    return IntentKind.dinner


def _intents() -> list[object]:
    from happen_api.planning.contracts import PlaceIntent

    return [PlaceIntent(kind=_dinner(), label="dinner", position=1)]


def main() -> int:
    """Report fixture-derived latencies and label them accurately."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print JSON only")
    parser.add_argument(
        "--delay-ms",
        type=float,
        default=25.0,
        help="scripted per-call delay standing in for network latency",
    )
    args = parser.parse_args()

    results = {
        "source": "fixture",
        "measures_live_serpapi": False,
        "warning": (
            "Fixture-derived. These numbers exclude real network latency, SerpApi "
            "response time, and cold-start model loading. They are not a live "
            "performance measurement."
        ),
        "runs_per_case": RUNS,
        "warmup": WARMUP,
        "planning_deadline_seconds": PLANNING_DEADLINE_SECONDS,
        "plan_allowance": PLAN_BILLED_REQUEST_LIMIT,
        "cases": {
            "cached_plan_no_provider_call": benchmark_cached_plan(),
            "metered_billed_call": benchmark_metered_call(args.delay_ms / 1000),
        },
    }

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
        return 0

    print("Fixture benchmark. No SerpApi credits were consumed.")
    print(results["warning"])
    print()
    for name, case in results["cases"].items():
        print(
            f"{name}: p50={case['p50_ms']}ms p95={case['p95_ms']}ms "
            f"provider_calls={case['provider_calls']}"
        )
        if "within_target" in case:
            verdict = "within" if case["within_target"] else "over"
            print(f"  cached target {case['target_ms']}ms: {verdict}")
    print()
    print("Live validation still required: see docs/HANDOFF2.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
