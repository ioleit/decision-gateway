import threading

import pytest

from decision_router import Cache, Record, Router
from decision_router.requirements import RequirementNotMetError
from decision_router.systemone import InvalidResponseError
from decision_router.testing import Fake, choice


def test_miss_calls_once_then_hits(router: Router, fake: Fake, cache: Cache) -> None:
    r1 = router.ask("fake", **choice("A", "B"))
    r2 = router.ask("fake", **choice("A", "B"))
    assert fake.calls == 1
    assert r1 == r2
    assert cache.counts() == (1, 0)


def test_cached_and_key_make_no_call(router: Router, fake: Fake) -> None:
    req = choice("A", "B")
    assert router.cached("fake", **req) is None
    assert router.key("fake", **req) is not None
    assert fake.calls == 0
    router.ask("fake", **req)
    assert router.cached("fake", **req) == router.ask("fake", **req)
    assert fake.calls == 1


def test_different_questions_are_different_answers(router: Router, fake: Fake) -> None:
    router.ask("fake", **choice("A", "B"))
    router.ask("fake", **choice("A", "B", "C"))
    router.ask("fake", **choice("A", "B", state={"case": 2}))
    assert fake.calls == 3


def test_labels_are_not_in_the_key(router: Router, fake: Fake, cache: Cache) -> None:
    router.ask("fake", **choice("A", "B"), labels={"task": "demo"})
    router.ask("fake", **choice("A", "B"), labels={"task": "demo"})
    router.ask("fake", **choice("A", "B"), labels={"study": "other"})
    router.ask("fake", **choice("A", "B"))
    assert fake.calls == 1
    assert cache.counts() == (1, 2)


def test_changed_requirements_are_a_new_key(cache: Cache) -> None:
    v1, v2 = Fake("m"), Fake("m", {"requirements": {"systemone_response_model_id": "m"}})
    Router({"m": v1}, cache).ask("m", **choice("A", "B"))
    Router({"m": v2}, cache).ask("m", **choice("A", "B"))
    assert (v1.calls, v2.calls) == (1, 1)


def test_cache_off_is_never_stored(cache: Cache) -> None:
    off = Fake("o", {"cache": False})
    router = Router({"o": off}, cache)
    for _ in range(2):
        router.ask("o", **choice("A", "B"))
    assert off.calls == 2
    assert router.key("o", **choice("A")) is None
    assert cache.counts() == (0, 0)


def test_no_cache_at_all(fake: Fake) -> None:
    router = Router({"fake": fake})
    router.ask("fake", **choice("A", "B"))
    router.ask("fake", **choice("A", "B"))
    assert fake.calls == 2


def test_errors_are_raised_and_not_stored(router: Router, fake: Fake, cache: Cache) -> None:
    fake.fail = TimeoutError("slow")
    with pytest.raises(TimeoutError):
        router.ask("fake", **choice("A", "B"))
    fake.fail = None
    router.ask("fake", **choice("A", "B"))
    assert fake.calls == 2
    assert cache.counts()[0] == 1


def test_a_response_that_misses_questions_is_an_error(router: Router, fake: Fake, cache: Cache) -> None:
    fake.bad = True
    with pytest.raises(InvalidResponseError, match="do not match the questions asked"):
        router.ask("fake", **choice("A", "B"))
    assert cache.counts() == (0, 0)


def test_provenance_is_stored(router: Router, cache: Cache) -> None:
    router.ask("fake", **choice("A", "B"))
    row = cache.con.execute("SELECT model, requirements, wire, raw, cost, provenance, asked_at FROM answers").fetchone()
    model, requirements, wire, raw, cost, provenance, asked_at = row
    assert (model, requirements, wire, cost, provenance) == ("fake", "{}", None, 0.001, '{"generation":"gen-1"}')
    assert raw.startswith('{"wrapped":')
    assert asked_at.endswith("Z")


def test_one_call_for_concurrent_asks_in_one_process(cache: Cache) -> None:
    slow = Fake("slow", delay=0.2)
    router = Router({"slow": slow}, cache)
    out = []
    threads = [threading.Thread(target=lambda: out.append(router.ask("slow", **choice("A", "B")))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert slow.calls == 1
    assert len(out) == 8
    assert all(o == out[0] for o in out)


def test_uniform_through_the_router(router: Router, cache: Cache) -> None:
    r = router.ask("uniform", **choice("A", "B", "C"), labels={"task": "demo"})
    assert r.model == "uniform"
    assert r.choices["pick"].probabilities["B"] == pytest.approx(1 / 3)
    assert router.cached("uniform", **choice("A", "B", "C")) == r


def test_unknown_model(router: Router) -> None:
    with pytest.raises(KeyError, match="unknown model"):
        router.ask("nope", **choice("A"))


PAST = ["2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z"]


def test_a_request_requirement_not_met_sends_nothing(cache: Cache) -> None:
    late = Fake("m", {"requirements": {"request_date_range": PAST}})
    with pytest.raises(RequirementNotMetError, match="not sent, new questions may be sent only between"):
        Router({"m": late}, cache).ask("m", **choice("A", "B"))
    assert late.calls == 0
    assert cache.counts() == (0, 0)


def test_a_response_requirement_not_met_stores_nothing(cache: Cache) -> None:
    other = Fake("m", {"requirements": {"systemone_response_model_id": "m-20261101"}})
    with pytest.raises(RequirementNotMetError, match="response not stored, served by 'm', not 'm-20261101'"):
        Router({"m": other}, cache).ask("m", **choice("A", "B"), labels={"t": 1})
    assert other.calls == 1
    assert cache.counts() == (0, 0)


def test_requirements_apply_without_a_cache_too() -> None:
    other = Fake("m", {"requirements": {"systemone_response_model_id": "m-20261101"}})
    with pytest.raises(RequirementNotMetError):
        Router({"m": other}).ask("m", **choice("A", "B"))


def test_cached_answers_are_served_when_a_request_requirement_no_longer_holds(cache: Cache) -> None:
    # the same requirements (so the same key), now outside the date range: cached answers still come back
    late = Fake("m", {"requirements": {"request_date_range": PAST}})
    router = Router({"m": late}, cache)
    k = router.key("m", **choice("A", "B"))
    assert k is not None
    stored = {"model": "m", "answers": {"pick": {"type": "noul", "noul": 0.9}}, "usage": {}}
    cache.put(Record(key=k, model="m", requirements=late.requirements_spec, request={}, response=stored))
    assert router.ask("m", **choice("A", "B")).nouls["pick"].noul == 0.9
    assert late.calls == 0
