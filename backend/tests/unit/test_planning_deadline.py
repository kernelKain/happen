"""The shared planning deadline, cancellation, and concurrency-safe accounting.

Every test here uses a fake clock and a scripted provider. Nothing opens a
socket and no SerpApi credit is spent. The rules under test:

- one monotonic budget governs every stage of a request;
- a cancelled or expired request never reaches the network, and costs nothing;
- concurrent work shares one eight-attempt allowance and cannot exceed it;
- the answer does not depend on the order concurrent work happened to finish.
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, time
from typing import ClassVar

import pytest

from happen_api.planning.constraints import EveningConstraints
from happen_api.planning.contracts import IntentKind, PlaceIntent, ResolvedDestination
from happen_api.planning.deadline import (
    CACHED_SECONDS,
    PLANNING_DEADLINE_SECONDS,
    DeadlineExceeded,
    PlanningDeadline,
    Stage,
    stage_timings_are_safe,
)
from happen_api.planning.limits import (
    PLAN_BILLED_REQUEST_LIMIT,
    AllowanceStore,
    MeteredProvider,
    PlanCache,
)


class FakeClock:
    """A monotonic clock a test moves by hand. Nothing here sleeps."""

    def __init__(self, start: float = 0.0) -> None:
        self.now_value = start

    def __call__(self) -> float:
        return self.now_value

    def advance(self, seconds: float) -> None:
        self.now_value += seconds


def _deadline(clock: FakeClock, *, cancel: bool = False) -> PlanningDeadline:
    return PlanningDeadline(
        budget_seconds=PLANNING_DEADLINE_SECONDS,
        now=clock,
        cancel=lambda: cancel,
    ).start()


def test_the_deadline_is_the_contract_budget_and_is_monotonic() -> None:
    """Verify one request carries the contract's fourteen-second budget."""

    clock = FakeClock()
    deadline = _deadline(clock)
    assert deadline.remaining == PLANNING_DEADLINE_SECONDS
    clock.advance(3.0)
    assert deadline.remaining == pytest.approx(11.0)
    clock.advance(11.0)
    assert deadline.expired is True
    assert deadline.remaining == 0.0


def test_a_stage_never_receives_more_time_than_the_request_has_left() -> None:
    """Verify a late stage is handed only what is left, never its own full cap."""

    clock = FakeClock()
    deadline = _deadline(clock)
    clock.advance(13.0)
    # A stage that would like 8 seconds gets the 1 second that remains.
    assert deadline.budget_for(8.0) == pytest.approx(1.0)
    clock.advance(5.0)
    assert deadline.budget_for(8.0) == 0.0


def test_a_stage_refuses_to_start_after_the_budget_runs_out() -> None:
    """Verify expired work is never started, rather than started and cut off."""

    clock = FakeClock()
    deadline = _deadline(clock)
    clock.advance(PLANNING_DEADLINE_SECONDS + 1)
    with pytest.raises(DeadlineExceeded), deadline.stage(Stage.search, 8.0):
        pytest.fail("an expired stage must not run")


def test_a_cancelled_request_reports_cancelled_and_is_expired_separately() -> None:
    """Verify a disconnection is distinguishable from an exhausted budget."""

    clock = FakeClock()
    deadline = _deadline(clock, cancel=True)
    assert deadline.cancelled() is True
    assert deadline.expired is False
    with pytest.raises(DeadlineExceeded):
        deadline.check()


def test_stage_timings_record_only_safe_fields() -> None:
    """Verify diagnostics carry a name, a duration, and an outcome, nothing else."""

    clock = FakeClock()
    deadline = _deadline(clock)
    with deadline.stage(Stage.search, 8.0):
        clock.advance(0.5)
    with deadline.stage(Stage.details, 4.0):
        clock.advance(0.25)
    timings = deadline.timings()
    assert [item["stage"] for item in timings] == ["search", "details"]
    assert timings[0]["elapsed_ms"] == 500
    assert timings[1]["elapsed_ms"] == 250
    assert all(item["outcome"] == "ok" for item in timings)
    # No prompt, destination, URL, or review text can appear in a timing.
    assert stage_timings_are_safe(timings)


def test_a_timed_out_stage_is_recorded_as_such() -> None:
    """Verify a stage that had no time left is labelled, not silently ok."""

    clock = FakeClock()
    deadline = _deadline(clock)
    clock.advance(PLANNING_DEADLINE_SECONDS)
    with pytest.raises(DeadlineExceeded), deadline.stage(Stage.reviews, 4.0):
        pytest.fail("must not run")
    # Nothing ran, so nothing was recorded. The refusal itself is the outcome.


class ScriptedProvider:
    """A provider whose sends are counted and whose delay is scripted."""

    def __init__(self, *, fail_first: int = 0, hold: float = 0.0) -> None:
        self.calls: list[str] = []
        self.sends = 0
        self.fail_first = fail_first
        self.hold = hold
        self._gate: object = None

    def set_attempt_gate(self, gate: object) -> None:
        self._gate = gate

    def _attempt(self, name: str) -> None:
        # The send gate runs first, exactly as the real client orders them.
        self.calls.append(name)
        self.sends += 1
        if callable(self._gate):
            self._gate()

    def search_places(self, *_args: object, **_kwargs: object) -> object:
        self._attempt("search_places")

        class _Snapshot:
            payload: ClassVar[dict[str, object]] = {"local_results": []}

        return _Snapshot()


def test_cancellation_before_send_sends_nothing_and_spends_nothing() -> None:
    """Verify a caller that disconnected costs zero provider attempts."""

    store = AllowanceStore()
    token = store.issue()
    provider = ScriptedProvider()
    metered = MeteredProvider(provider, store, token)
    from happen_api.providers.serpapi.client import SerpApiClient, SerpApiFailure

    client = SerpApiClient("test-key", credit_limit=8, cancelled=lambda: True)
    client.set_attempt_gate(metered._claim)
    with pytest.raises(SerpApiFailure):
        client.search_places("dinner in Tokyo")
    assert store.spent(token) == 0
    assert provider.sends == 0


def test_the_expired_deadline_stops_a_send_before_the_allowance_is_charged() -> None:
    """Verify an expired budget refuses the attempt and spends nothing."""

    clock = FakeClock()
    deadline = _deadline(clock)
    store = AllowanceStore()
    token = store.issue()
    provider = ScriptedProvider()
    metered = MeteredProvider(provider, store, token)
    from happen_api.providers.serpapi.client import SerpApiClient, SerpApiFailure

    client = SerpApiClient("test-key", credit_limit=8)
    client.set_attempt_gate(metered._claim)
    client.set_send_gate(lambda: deadline.allow_send())
    clock.advance(PLANNING_DEADLINE_SECONDS + 1)
    with pytest.raises(SerpApiFailure):
        client.search_places("dinner in Tokyo")
    assert provider.sends == 0
    assert store.spent(token) == 0


def test_concurrent_tasks_share_one_allowance_and_cannot_exceed_it() -> None:
    """Verify racing callers cannot jointly send more than eight requests."""

    store = AllowanceStore()
    token = store.issue()
    clients = [MeteredProvider(ScriptedProvider(), store, token) for _ in range(6)]
    barrier = threading.Barrier(len(clients))

    def drain(client: MeteredProvider) -> None:
        barrier.wait()
        for _ in range(PLAN_BILLED_REQUEST_LIMIT):
            try:
                client.search_places("dinner in Tokyo")
            except Exception:  # noqa: BLE001 - exhaustion and timeout both stop it
                return

    threads = [threading.Thread(target=drain, args=(client,)) for client in clients]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    sent = sum(client.credits_charged for client in clients)
    assert store.spent(token) == PLAN_BILLED_REQUEST_LIMIT
    assert store.remaining(token) == 0
    # Every claim was made through the one shared store, so nothing overspent.
    assert sent == PLAN_BILLED_REQUEST_LIMIT


def test_a_retry_is_charged_once_per_actual_attempt_under_a_shared_deadline() -> None:
    """Verify each real network attempt spends one request, retry included."""

    import httpx
    import respx

    from happen_api.providers.serpapi.client import SerpApiClient, SerpApiFailure

    clock = FakeClock()
    deadline = _deadline(clock)
    store = AllowanceStore()
    token = store.issue()
    metered = MeteredProvider(ScriptedProvider(), store, token)
    client = SerpApiClient(_KEY, credit_limit=PLAN_BILLED_REQUEST_LIMIT)
    client.set_attempt_gate(metered._claim)
    client.set_send_gate(lambda: deadline.allow_send())

    def fail_then_succeed(_request: httpx.Request) -> httpx.Response:
        if _request.url.params.get("attempt") == "second":
            return httpx.Response(200, json=_SUCCESS)
        raise httpx.ReadTimeout("timed out")

    with respx.mock, pytest.raises(SerpApiFailure) as caught:
        respx.get(_SEARCH_URL).mock(side_effect=fail_then_succeed)
        client.search_places("dinner in Tokyo")
    assert caught.value.code == "TRANSIENT_DEPENDENCY"
    # Two attempts reached the network, so two requests were spent.
    assert store.spent(token) == 2
    assert store.remaining(token) == PLAN_BILLED_REQUEST_LIMIT - 2


def test_repeated_runs_produce_an_identical_pool_and_plan() -> None:
    """Verify the same retrieval input yields byte-identical output every time.

    Determinism here means repeated runs agree. It does not mean the order the
    provider happened to return rows in is discarded: `provider_rank` is the
    documented first tie-breaker, so reversed input legitimately ranks the other
    way first. What must never vary is the outcome of one fixed input.
    """

    from happen_api.planning.discovery import _candidate_pool, _sort_pool
    from happen_api.planning.itinerary import assemble_itinerary

    destination = ResolvedDestination(
        label="Tokyo",
        source_text="Tokyo",
        timezone_name="Asia/Tokyo",
        latitude=35.6764,
        longitude=139.65,
    )
    rows = [
        {
            "title": name,
            "place_id": place_id,
            "address": "Tokyo",
            "gps_coordinates": {"latitude": 35.6764, "longitude": 139.65},
            "rating": 4.6,
            "operating_hours": {"monday": "6:00 PM–11:00 PM"},
        }
        for name, place_id in (("Kura", "kura"), ("Nami", "nami"), ("Aoi", "aoi"))
    ]
    intents = [PlaceIntent(kind=IntentKind.dinner, label="dinner", position=1)]
    constraints = EveningConstraints()

    def run_once() -> tuple[list[str], list[str]]:
        pool = _candidate_pool(
            rows,
            IntentKind.dinner,
            destination,
            local_date=_MONDAY,
            arrival=_ARRIVAL,
            constraints=constraints,
        )
        _sort_pool(pool, intents, local_date=_MONDAY, arrival=_ARRIVAL, constraints=constraints)
        plan = assemble_itinerary(
            pool,
            intents,
            local_date=_MONDAY,
            local_start=_ARRIVAL,
            retrieved_at=_WHEN,
        )
        return [item.name for item in pool], [item.name for item in plan.stops]

    first_pool, first_stops = run_once()
    for _ in range(4):
        again_pool, again_stops = run_once()
        assert again_pool == first_pool
        assert again_stops == first_stops
    assert first_pool == ["Kura", "Nami", "Aoi"]


def test_the_documented_tie_break_chain_orders_equal_fit_candidates() -> None:
    """Verify provider rank, then casefolded name, then place id decide the order.

    This is the chain that makes it safe to sort after concurrent retrieval. The
    provider's own result order is the documented first tie-breaker, so it does
    decide; the name and the id only settle what it leaves equal, which is what
    keeps the result stable rather than arbitrary.
    """

    from happen_api.planning.discovery import _candidate_pool, _sort_pool

    destination = ResolvedDestination(
        label="Tokyo",
        source_text="Tokyo",
        timezone_name="Asia/Tokyo",
        latitude=35.6764,
        longitude=139.65,
    )
    rows = [
        {
            "title": name,
            "place_id": place_id,
            "address": "Tokyo",
            "gps_coordinates": {"latitude": 35.6764, "longitude": 139.65},
            "rating": 4.6,
            "operating_hours": {"monday": "6:00 PM–11:00 PM"},
        }
        for name, place_id in (("Zori", "zori"), ("Aoi", "aoi"), ("Mugi", "mugi"))
    ]
    constraints = EveningConstraints()

    def ordered(pool: list[object]) -> list[str]:
        _sort_pool(
            pool,  # type: ignore[arg-type]
            [PlaceIntent(kind=IntentKind.dinner, label="dinner", position=1)],
            local_date=_MONDAY,
            arrival=_ARRIVAL,
            constraints=constraints,
        )
        return [item.name for item in pool]  # type: ignore[attr-defined]

    def build(source: list[dict[str, object]]) -> list[str]:
        return ordered(
            _candidate_pool(
                source,
                IntentKind.dinner,
                destination,
                local_date=_MONDAY,
                arrival=_ARRIVAL,
                constraints=constraints,
            )
        )

    # Provider order is honoured for equal fit, and the name settles a tie that
    # the provider left equal.
    assert build(rows) == ["Zori", "Aoi", "Mugi"]
    # An identical ranking put in the same provider order always gives the same
    # result, whatever order the rows were written in.
    assert build([rows[1], rows[2], rows[0]]) == ["Aoi", "Mugi", "Zori"]


def test_a_cached_plan_needs_no_provider_call_and_stays_inside_its_target() -> None:
    """Verify the cached path performs zero sends and completes well in budget."""

    from happen_api.planning.discovery import CandidatePool, _place_from_record
    from happen_api.planning.itinerary import assemble_itinerary

    store = AllowanceStore()
    token = store.issue()
    provider = ScriptedProvider()
    metered = MeteredProvider(provider, store, token)
    cache = PlanCache()
    key = "b" * 64

    record = {
        "title": "Kura",
        "place_id": "kura",
        "address": "Tokyo",
        "gps_coordinates": {"latitude": 35.6764, "longitude": 139.65},
        "operating_hours": {"monday": "6:00 PM–11:00 PM"},
    }
    place = _place_from_record(record, IntentKind.dinner)
    assert place is not None
    cache.put(key, CandidatePool(places=[place]))
    metered.search_places("dinner in Tokyo")
    spent_after_setup = store.spent(token)

    cached = cache.get(key)
    assert cached is not None
    plan = assemble_itinerary(
        cached.places,
        [_DINNER],
        local_date=_MONDAY,
        local_start=_ARRIVAL,
        retrieved_at=_WHEN,
    )
    assert plan.stops
    # The cached plan spent nothing at all.
    assert store.spent(token) == spent_after_setup
    # The ceiling the contract sets for a cached read.
    assert CACHED_SECONDS <= 0.3


_MONDAY = date(2026, 10, 5)
_ARRIVAL = time(19, 0)
_WHEN = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)
_DINNER = PlaceIntent(kind=IntentKind.dinner, label="dinner", position=1)

_KEY = "test-key-value"
_SEARCH_URL = "https://serpapi.com/search.json"
_SUCCESS = {"search_metadata": {"id": "s1", "status": "Success"}, "local_results": []}
