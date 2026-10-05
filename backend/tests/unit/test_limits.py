"""Admission control and the bounded plan cache. No provider is called."""

from __future__ import annotations

from happen_api.ai.extractor import release_model
from happen_api.planning.contracts import IntentKind
from happen_api.planning.discovery import CandidatePool, DiscoveredPlace
from happen_api.planning.limits import PlanCache, PlanningThrottle


def test_three_billed_plans_block_another_until_one_finishes() -> None:
    """One process keeps at most three billed plans running."""

    gate = PlanningThrottle()
    for caller in ("a", "b", "c"):
        assert gate.start(caller, limit=30, window_seconds=60, billed=True) is None
    waiting = gate.start("d", limit=30, window_seconds=60, billed=True)
    assert waiting == 1
    gate.finish(True)
    assert gate.start("d", limit=30, window_seconds=60, billed=True) is None


def test_plan_cache_keeps_a_bound_and_rejects_a_raw_key() -> None:
    """The cache stores the candidate pool, evicts past its maximum, and ignores a raw key."""

    cache = PlanCache(maxsize=2, ttl=60)
    cache.put("a" * 64, CandidatePool(places=[_place("First")]))
    cache.put("b" * 64, CandidatePool(places=[_place("Second"), _place("Alternate")]))
    cache.put("c" * 64, CandidatePool(places=[_place("Third"), _place("Other")]))
    cache.put("Dinner in Kyoto", CandidatePool(places=[_place("Rejected")]))
    cache.put("d" * 64, CandidatePool(places=[]))
    assert len(cache) == 2
    assert cache.get("a" * 64) is None
    kept = cache.get("c" * 64)
    assert kept is not None
    assert [place.name for place in kept.places] == ["Third", "Other"]
    kept.places[0].name = "Mutated"
    again = cache.get("c" * 64)
    assert again is not None
    assert again.places[0].name == "Third"
    assert cache.get("Dinner in Kyoto") is None


def test_release_model_is_safe_when_none_is_loaded() -> None:
    """Stopping the process does not require a model to have been loaded."""

    release_model()


def _place(name: str) -> DiscoveredPlace:
    return DiscoveredPlace(intent=IntentKind.dinner, name=name, place_id=name.casefold())
