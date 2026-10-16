"""export -> preheat -> the same hits, with zero backend calls: the deployment case."""

from pathlib import Path

import pytest

from decision_router import Cache, Router, query
from decision_router.cache.export import export
from decision_router.cache.preheat import preheat
from decision_router.testing import Fake, choice

QUESTIONS = [choice(*"ABCD"[:n], state={"case": c}) for n in (2, 3, 4) for c in range(5)]


def test_roundtrip(tmp_path: Path, router: Router, cache: Cache, fake: Fake, request: pytest.FixtureRequest) -> None:
    for i, q in enumerate(QUESTIONS):
        router.ask("fake", **q, labels={"i": i})
        router.ask("uniform", **q, labels={"i": i, "copy": "uniform"})
    calls = fake.calls

    n = export(cache.path, tmp_path / "exp")
    assert n == (30, 30)

    fresh = Cache(tmp_path / "fresh.sqlite")
    request.addfinalizer(fresh.close)
    assert preheat(tmp_path / "exp", fresh) == (30, 30)

    cold = Fake("fake")
    deployed = Router({"fake": cold, "uniform": router.models["uniform"]}, fresh)
    for q in QUESTIONS:
        assert deployed.ask("fake", **q) == router.ask("fake", **q)
    assert cold.calls == 0
    assert fake.calls == calls

    # every row identical, byte for byte
    sql = "SELECT * FROM answers ORDER BY key"
    assert fresh.con.execute(sql).fetchall() == cache.con.execute(sql).fetchall()
    sql = "SELECT * FROM labels ORDER BY key, labels"
    assert fresh.con.execute(sql).fetchall() == cache.con.execute(sql).fetchall()

    # preheating again adds nothing
    assert preheat(tmp_path / "exp", fresh) == (0, 0)


def test_refusals_roundtrip(tmp_path: Path, cache: Cache) -> None:
    refusing = Fake("fake")
    refusing.refuse = True
    first = Router({"fake": refusing}, cache).ask("fake", **choice("A", "B"), labels={"study": "demo"})
    assert first.router.refusal is not None
    assert export(cache.path, tmp_path / "exp") == (1, 1)

    with Cache(tmp_path / "fresh.sqlite") as fresh:
        assert preheat(tmp_path / "exp", fresh) == (1, 1)
        cold = Fake("fake")
        served = Router({"fake": cold}, fresh).ask("fake", **choice("A", "B"))
        assert served == first
        assert cold.calls == 0
        assert query.connect(fresh.path).sql("SELECT outcome, count(*) FROM answers GROUP BY ALL").fetchall() == [
            ("refused", 1)
        ]
