from pathlib import Path

import pytest

from decision_router import Cache, Router, query
from decision_router.testing import choice


@pytest.fixture
def filled(router: Router, cache: Cache) -> Cache:
    for n in (2, 3, 4):
        opts = "ABCD"[:n]
        router.system_one(**choice(*opts), model="uniform", labels={"task": "demo", "n": n})
        router.system_one(**choice(*opts), model="fake", labels={"task": "demo", "n": n})
    router.system_one(**choice("A", "B"), model="uniform", labels={"study": "other"})
    return cache


def test_views_over_the_live_cache(filled: Cache) -> None:
    con = query.connect(filled.path)
    assert con.sql("SELECT model, count(*) FROM answers GROUP BY model ORDER BY model").fetchall() == [
        ("fake", 3),
        ("uniform", 3),
    ]
    assert con.sql("SELECT count(*) FROM labels").fetchall() == [(7,)]


def test_json_columns_are_queryable(filled: Cache) -> None:
    con = query.connect(filled.path)
    rows = con.sql("""SELECT CAST(l.labels->>'n' AS INT) AS n,
                             CAST(a.response->'answers'->'pick'->'probabilities'->>'A' AS DOUBLE) AS p
                      FROM answers a JOIN labels l USING (key)
                      WHERE a.model = 'uniform' AND (l.labels->>'task') = 'demo' ORDER BY n""").fetchall()
    assert rows == [(2, 0.5), (3, pytest.approx(1 / 3)), (4, 0.25)]


def test_reads_while_a_writer_works(filled: Cache, router: Router) -> None:
    con = query.connect(filled.path)
    router.system_one(**choice("X", "Y"), model="uniform")
    assert con.sql("SELECT count(*) FROM answers").fetchall() == [(7,)]


def test_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        query.connect(tmp_path / "nope.sqlite")
    with pytest.raises(FileNotFoundError, match="not an export"):
        query.connect(tmp_path)
