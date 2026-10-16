"""Export the answers a query selects."""

from pathlib import Path

from decision_router import Cache, Router, query
from decision_router.cache.export import export
from decision_router.testing import choice

QUESTIONS = [choice(*"ABCD"[:n], state={"case": c}) for n in (2, 3, 4) for c in range(5)]


def test_export_a_query_result(tmp_path: Path, router: Router, cache: Cache) -> None:
    for q in QUESTIONS:
        router.ask("fake", q)
        router.ask("uniform", q, labels={"keep": True})
    n = export(cache.path, tmp_path / "exp", keys="SELECT key FROM answers WHERE model = 'uniform'")
    assert n == (15, 15)
    con = query.connect(tmp_path / "exp")
    assert con.sql("SELECT DISTINCT model FROM answers").fetchall() == [("uniform",)]
    assert con.sql("SELECT count(*) FROM labels WHERE (labels->>'keep') = 'true'").fetchall() == [(15,)]
