import asyncio
import threading
from pathlib import Path

import pytest
from pydantic import BaseModel
from typesafe_sdk import Noul, SystemOneResponse, TypeSafeBadRequestError

from decision_router import AsyncRouter, Cache, Model, Record, RoutedResponse, Router
from decision_router.models import MissingKeyError
from decision_router.requirements import RequirementNotMetError
from decision_router.systemone import InvalidResponseError
from decision_router.testing import FakeServer, choice

PAST = ["2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z"]


def test_a_miss_calls_once_then_hits(router: Router, server: FakeServer, cache: Cache) -> None:
    first = router.system_one(**choice("A", "B"), model="fake")
    second = router.system_one(**choice("A", "B"), model="fake")
    assert server.calls == 1
    assert first == second
    assert isinstance(first, SystemOneResponse)
    assert cache.counts() == (1, 0)


def test_it_takes_system_one_arguments_like_the_sdk(router: Router, server: FakeServer) -> None:
    response = router.system_one("I was charged twice.", {"refund": Noul(instructions="Money back?")}, "fake")
    assert response.nouls["refund"].noul == 0.5
    assert server.requests[0] == {
        "state": "I was charged twice.",
        "model": "fake",
        "questions": {"refund": {"type": "noul", "instructions": "Money back?"}},
    }


def test_cached_and_key_make_no_call(router: Router, server: FakeServer) -> None:
    req = choice("A", "B")
    assert router.cached(**req, model="fake") is None
    assert router.key(**req, model="fake") is not None
    assert server.calls == 0
    asked = router.system_one(**req, model="fake")
    assert router.cached(**req, model="fake") == asked
    assert server.calls == 1


def test_different_requests_are_different_answers(router: Router, server: FakeServer) -> None:
    router.system_one(**choice("A", "B"), model="fake")
    router.system_one(**choice("A", "B", "C"), model="fake")
    router.system_one(**choice("A", "B", state={"case": 2}), model="fake")
    router.system_one(**choice("A", "B"), model="fake", extra_body={"provider": {"only": ["x"]}})
    assert server.calls == 4


def test_labels_are_not_in_the_key(router: Router, server: FakeServer, cache: Cache) -> None:
    router.system_one(**choice("A", "B"), model="fake", labels={"task": "demo"})
    router.system_one(**choice("A", "B"), model="fake", labels={"task": "demo"})
    router.system_one(**choice("A", "B"), model="fake", labels={"study": "other"})
    router.system_one(**choice("A", "B"), model="fake")
    assert server.calls == 1
    assert cache.counts() == (1, 2)


def test_the_models_extra_body_is_sent_and_keyed(cache: Cache, server: FakeServer) -> None:
    pinned = server.model("m", extra_body={"provider": {"only": ["typesafe"], "allow_fallbacks": False}})
    with Router({"m": pinned}, cache) as router:
        router.system_one(**choice("A", "B"), model="m")
    assert server.requests[0]["provider"] == {"only": ["typesafe"], "allow_fallbacks": False}
    stored = cache.con.execute("SELECT request FROM answers").fetchone()[0]
    assert '"provider":{"allow_fallbacks":false,"only":["typesafe"]}' in stored


def test_the_model_id_sent_is_the_configured_one(cache: Cache, server: FakeServer) -> None:
    with Router({"jev": server.model("jev", model="typesafe/jev-1.13")}, cache) as router:
        router.system_one(**choice("A", "B"), model="jev")
    assert server.requests[0]["model"] == "typesafe/jev-1.13"


def test_changed_requirements_are_a_new_key(cache: Cache, server: FakeServer) -> None:
    plain = server.model("m")
    required = server.model("m", requirements_table={"systemone_response_model_id": "m"})
    with Router({"m": plain}, cache) as r:
        r.system_one(**choice("A", "B"), model="m")
    with Router({"m": required}, cache) as r:
        r.system_one(**choice("A", "B"), model="m")
    assert server.calls == 2


def test_cache_off_and_no_cache_are_never_stored(cache: Cache, server: FakeServer) -> None:
    with Router({"o": server.model("o", cache=False)}, cache) as router:
        router.system_one(**choice("A", "B"), model="o")
        router.system_one(**choice("A", "B"), model="o")
        assert router.key(**choice("A"), model="o") is None
    with Router({"n": server.model("n")}) as uncached:
        uncached.system_one(**choice("A", "B"), model="n")
    assert server.calls == 3
    assert cache.counts() == (0, 0)


def test_errors_are_raised_and_not_stored(router: Router, server: FakeServer, cache: Cache) -> None:
    server.statuses = [400]
    with pytest.raises(TypeSafeBadRequestError):
        router.system_one(**choice("A", "B"), model="fake")
    router.system_one(**choice("A", "B"), model="fake")
    assert server.calls == 2
    assert cache.counts()[0] == 1


def test_a_response_that_misses_questions_is_an_error(router: Router, server: FakeServer, cache: Cache) -> None:
    server.wrong = True
    with pytest.raises(InvalidResponseError, match="do not match the questions asked"):
        router.system_one(**choice("A", "B"), model="fake")
    assert cache.counts() == (0, 0)


def test_the_response_is_stored_as_received(router: Router, cache: Cache) -> None:
    router.system_one(**choice("A", "B"), model="fake")
    response, cost, provenance, asked_at = cache.con.execute(
        "SELECT response, cost, provenance, asked_at FROM answers"
    ).fetchone()
    assert '"provider":"Fake"' in response  # beyond the System One API, kept
    assert '"cost":0.001' in response
    assert cost == 0.001
    assert provenance == '{"id":"gen-1","provider":"Fake"}'
    assert asked_at.endswith("Z")


def test_extra_fields_reach_the_caller_too(router: Router) -> None:
    response = router.system_one(**choice("A", "B"), model="fake")
    assert isinstance(response, RoutedResponse)
    assert response.model_extra == {"id": "gen-1", "provider": "Fake"}
    again = router.system_one(**choice("A", "B"), model="fake")
    assert again.model_extra == {"id": "gen-1", "provider": "Fake"}


def test_a_response_model_of_your_own(router: Router) -> None:
    class Mine(BaseModel):
        model: str
        provider: str

    response = router.system_one(**choice("A", "B"), model="fake", response_model=Mine)
    assert response == Mine(model="fake", provider="Fake")


def test_one_call_for_concurrent_asks_in_one_process(cache: Cache) -> None:
    slow = FakeServer(delay=0.2)
    out = []
    with Router({"slow": slow.model("slow")}, cache) as router:
        threads = [
            threading.Thread(target=lambda: out.append(router.system_one(**choice("A", "B"), model="slow")))
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert slow.calls == 1
    assert len(out) == 8
    assert all(o == out[0] for o in out)


def test_async_router(cache: Cache, server: FakeServer) -> None:
    async def run() -> list[RoutedResponse]:
        async with AsyncRouter({"fake": server.model("fake")}, cache) as router:
            many = await asyncio.gather(*[router.system_one(**choice("A", "B"), model="fake") for _ in range(5)])
            again = await router.system_one(**choice("A", "B"), model="fake")
            return [*many, again]

    out = asyncio.run(run())
    assert server.calls == 1
    assert all(o == out[0] for o in out)


def test_uniform(router: Router) -> None:
    r = router.system_one(**choice("A", "B", "C"), model="uniform")
    assert r.model == "uniform"
    assert r.choices["pick"].probabilities["B"] == pytest.approx(1 / 3)


def test_unknown_and_default_model(cache: Cache, server: FakeServer) -> None:
    with Router({"fake": server.model("fake")}, cache) as router:
        with pytest.raises(KeyError, match="unknown model"):
            router.system_one(**choice("A"), model="nope")
        with pytest.raises(ValueError, match="no default_model"):
            router.system_one(**choice("A"))
    with Router({"fake": server.model("fake")}, cache, default_model="fake") as router:
        assert router.system_one(**choice("A", "B")).model == "fake"


def test_the_key_is_read_only_on_a_miss(tmp_path: Path, server: FakeServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JEV_KEY", "k")
    jev = Model(name="jev", backend="openrouter", key_env="JEV_KEY", transport=server.transport)
    with Cache(tmp_path / "c.sqlite") as cache:
        with Router({"jev": jev}, cache) as router:
            router.system_one(**choice("A", "B"), model="jev")
        monkeypatch.delenv("JEV_KEY")
        with Router({"jev": jev}, cache) as router:
            assert router.system_one(**choice("A", "B"), model="jev").model == "jev"  # cached: no key needed
            with pytest.raises(MissingKeyError, match="JEV_KEY"):
                router.system_one(**choice("A", "B", "C"), model="jev")
    assert server.calls == 1


def test_a_request_requirement_not_met_sends_nothing(cache: Cache, server: FakeServer) -> None:
    late = server.model("m", requirements_table={"request_date_range": PAST})
    with Router({"m": late}, cache) as router, pytest.raises(RequirementNotMetError, match="not sent"):
        router.system_one(**choice("A", "B"), model="m")
    assert server.calls == 0
    assert cache.counts() == (0, 0)


def test_a_response_requirement_not_met_stores_nothing(cache: Cache) -> None:
    moved = FakeServer(served="m-20261101")
    other = moved.model("m", requirements_table={"systemone_response_model_id": "m-20260917"})
    with (
        Router({"m": other}, cache) as router,
        pytest.raises(RequirementNotMetError, match="response not stored, served by 'm-20261101', not 'm-20260917'"),
    ):
        router.system_one(**choice("A", "B"), model="m", labels={"t": 1})
    assert moved.calls == 1
    assert cache.counts() == (0, 0)


def test_requirements_apply_without_a_cache_too() -> None:
    moved = FakeServer(served="m-20261101")
    other = moved.model("m", requirements_table={"systemone_response_model_id": "m-20260917"})
    with Router({"m": other}) as router, pytest.raises(RequirementNotMetError):
        router.system_one(**choice("A", "B"), model="m")


def test_cached_answers_are_served_when_a_request_requirement_no_longer_holds(cache: Cache, server: FakeServer) -> None:
    # the same requirements (so the same key), now outside the date range: cached answers still come back
    late = server.model("m", requirements_table={"request_date_range": PAST})
    with Router({"m": late}, cache) as router:
        k = router.key(**choice("A", "B"), model="m")
        assert k is not None
        stored = {"model": "m", "answers": {"pick": {"type": "noul", "noul": 0.9}}, "usage": {}}
        cache.put(Record(key=k, model="m", requirements=late.requirements_spec, request={}, response=stored))
        assert router.system_one(**choice("A", "B"), model="m").nouls["pick"].noul == 0.9
    assert server.calls == 0
