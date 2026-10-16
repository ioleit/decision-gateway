import threading

import pytest

from decision_router import Cache, Router
from decision_router.testing import Fake, choice


def test_miss_calls_once_then_hits(router: Router, fake: Fake, cache: Cache) -> None:
    r1 = router.ask("fake", choice("A", "B"))
    r2 = router.ask("fake", choice("A", "B"))
    assert fake.calls == 1
    assert r1 == r2
    assert cache.counts() == (1, 0)


def test_cached_and_key_make_no_call(router: Router, fake: Fake) -> None:
    req = choice("A", "B")
    assert router.cached("fake", req) is None
    assert router.key("fake", req) is not None
    assert fake.calls == 0
    router.ask("fake", req)
    assert router.cached("fake", req) == router.ask("fake", req)
    assert fake.calls == 1


def test_different_questions_are_different_answers(router: Router, fake: Fake) -> None:
    router.ask("fake", choice("A", "B"))
    router.ask("fake", choice("A", "B", "C"))
    router.ask("fake", choice("A", "B", state={"case": 2}))
    assert fake.calls == 3


def test_labels_are_not_in_the_key(router: Router, fake: Fake, cache: Cache) -> None:
    router.ask("fake", choice("A", "B"), labels={"task": "demo"})
    router.ask("fake", choice("A", "B"), labels={"task": "demo"})
    router.ask("fake", choice("A", "B"), labels={"study": "other"})
    router.ask("fake", choice("A", "B"))
    assert fake.calls == 1
    assert cache.counts() == (1, 2)


def test_a_new_version_is_a_new_key(cache: Cache) -> None:
    v1, v2 = Fake("m", {"version": "m/1"}), Fake("m", {"version": "m/2"})
    Router({"m": v1}, cache).ask("m", choice("A", "B"))
    Router({"m": v2}, cache).ask("m", choice("A", "B"))
    assert (v1.calls, v2.calls) == (1, 1)


def test_unknown_version_or_cache_off_is_never_stored(cache: Cache) -> None:
    unversioned, off = Fake("u"), Fake("o", {"version": "o/1", "cache": False})
    router = Router({"u": unversioned, "o": off}, cache)
    for _ in range(2):
        router.ask("u", choice("A", "B"))
        router.ask("o", choice("A", "B"))
    assert (unversioned.calls, off.calls) == (2, 2)
    assert router.key("u", choice("A")) is None
    assert router.key("o", choice("A")) is None
    assert cache.counts() == (0, 0)


def test_no_cache_at_all(fake: Fake) -> None:
    router = Router({"fake": fake})
    router.ask("fake", choice("A", "B"))
    router.ask("fake", choice("A", "B"))
    assert fake.calls == 2


def test_errors_are_raised_and_not_stored(router: Router, fake: Fake, cache: Cache) -> None:
    fake.fail = TimeoutError("slow")
    with pytest.raises(TimeoutError):
        router.ask("fake", choice("A", "B"))
    fake.fail = None
    router.ask("fake", choice("A", "B"))
    assert fake.calls == 2
    assert cache.counts()[0] == 1


def test_a_response_that_misses_questions_is_an_error(router: Router, fake: Fake, cache: Cache) -> None:
    fake.bad = True
    with pytest.raises(ValueError, match="does not answer"):
        router.ask("fake", choice("A", "B"))
    assert cache.counts() == (0, 0)


def test_provenance_is_stored(router: Router, cache: Cache) -> None:
    router.ask("fake", choice("A", "B"))
    row = cache.con.execute("SELECT model, version, wire, raw, cost, provenance, asked_at FROM answers").fetchone()
    model, version, wire, raw, cost, provenance, asked_at = row
    assert (model, version, wire, cost, provenance) == ("fake", "fake/1", None, 0.001, '{"generation":"gen-1"}')
    assert raw.startswith('{"wrapped":')
    assert asked_at.endswith("Z")


def test_one_call_for_concurrent_asks_in_one_process(cache: Cache) -> None:
    slow = Fake("slow", {"version": "s/1"}, delay=0.2)
    router = Router({"slow": slow}, cache)
    out = []
    threads = [threading.Thread(target=lambda: out.append(router.ask("slow", choice("A", "B")))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert slow.calls == 1
    assert len(out) == 8
    assert all(o == out[0] for o in out)


def test_uniform_through_the_router(router: Router, cache: Cache) -> None:
    r = router.ask("uniform", choice("A", "B", "C"), labels={"task": "demo"})
    assert r["model"] == "uniform"
    assert r["answers"]["pick"]["probabilities"]["B"] == pytest.approx(1 / 3)
    assert router.cached("uniform", choice("A", "B", "C")) == r


def test_unknown_model(router: Router) -> None:
    with pytest.raises(KeyError, match="unknown model"):
        router.ask("nope", choice("A"))
