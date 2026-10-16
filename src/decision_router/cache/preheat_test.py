"""export -> preheat -> the same hits, with zero backend calls: the deployment case."""

from pathlib import Path

import pytest

from decision_router import Cache, Router
from decision_router.cache.export import export
from decision_router.cache.preheat import preheat
from decision_router.testing import FakeServer, choice

QUESTIONS = [choice(*"ABCD"[:n], state={"case": c}) for n in (2, 3, 4) for c in range(5)]


def test_roundtrip(
    tmp_path: Path, router: Router, cache: Cache, server: FakeServer, request: pytest.FixtureRequest
) -> None:
    for i, q in enumerate(QUESTIONS):
        router.system_one(**q, model="fake", labels={"i": i})
        router.system_one(**q, model="uniform", labels={"i": i, "copy": "uniform"})
    calls = server.calls

    n = export(cache.path, tmp_path / "exp")
    assert n == (30, 30)

    fresh = Cache(tmp_path / "fresh.sqlite")
    request.addfinalizer(fresh.close)
    assert preheat(tmp_path / "exp", fresh) == (30, 30)

    cold = FakeServer()
    deployed = Router({"fake": cold.model("fake"), "uniform": router.models["uniform"]}, fresh)
    request.addfinalizer(deployed.close)
    for q in QUESTIONS:
        assert deployed.system_one(**q, model="fake") == router.system_one(**q, model="fake")
    assert cold.calls == 0
    assert server.calls == calls

    # every row identical, byte for byte
    sql = "SELECT * FROM answers ORDER BY key"
    assert fresh.con.execute(sql).fetchall() == cache.con.execute(sql).fetchall()
    sql = "SELECT * FROM labels ORDER BY key, labels"
    assert fresh.con.execute(sql).fetchall() == cache.con.execute(sql).fetchall()

    # preheating again adds nothing
    assert preheat(tmp_path / "exp", fresh) == (0, 0)
