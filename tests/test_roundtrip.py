"""export -> preheat -> the same hits, with zero backend calls: the deployment case."""

from conftest import choice
from decision_router import Cache, Router, query
from decision_router.cache.export import export
from decision_router.cache.preheat import preheat
from fake_backend import Fake

QUESTIONS = [choice(*"ABCD"[:n], state={"case": c}) for n in (2, 3, 4) for c in range(5)]


def test_roundtrip(tmp_path, router, cache, fake):
    for i, q in enumerate(QUESTIONS):
        router.ask("fake", q, labels={"i": i})
        router.ask("uniform", q, labels={"i": i, "copy": "uniform"})
    calls = fake.calls

    n = export(cache.path, tmp_path / "exp")
    assert n == (30, 30)

    fresh = Cache(tmp_path / "fresh.sqlite")
    assert preheat(tmp_path / "exp", fresh) == (30, 30)

    cold = Fake("fake", {"version": "fake/1"})
    deployed = Router({"fake": cold, "uniform": router.models["uniform"]}, fresh)
    for q in QUESTIONS:
        assert deployed.ask("fake", q) == router.ask("fake", q)
    assert cold.calls == 0 and fake.calls == calls

    # every row identical, byte for byte
    sql = "SELECT * FROM answers ORDER BY key"
    assert fresh.con.execute(sql).fetchall() == cache.con.execute(sql).fetchall()
    sql = "SELECT * FROM labels ORDER BY key, labels"
    assert fresh.con.execute(sql).fetchall() == cache.con.execute(sql).fetchall()

    # preheating again adds nothing
    assert preheat(tmp_path / "exp", fresh) == (0, 0)


def test_export_a_query_result(tmp_path, router, cache):
    for q in QUESTIONS:
        router.ask("fake", q)
        router.ask("uniform", q, labels={"keep": True})
    n = export(cache.path, tmp_path / "exp", keys="SELECT key FROM answers WHERE model = 'uniform'")
    assert n == (15, 15)
    con = query.connect(tmp_path / "exp")
    assert con.sql("SELECT DISTINCT model FROM answers").fetchall() == [("uniform",)]
    assert con.sql("SELECT count(*) FROM labels WHERE labels->>'keep' = 'true'").fetchone()[0] == 15
