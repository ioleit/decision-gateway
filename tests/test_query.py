import pytest

from conftest import choice
from decision_router import query


@pytest.fixture
def filled(router, cache):
    for n in (2, 3, 4):
        opts = "ABCD"[:n]
        router.ask("uniform", choice(*opts), labels={"task": "demo", "n": n})
        router.ask("fake", choice(*opts), labels={"task": "demo", "n": n})
    router.ask("uniform", choice("A", "B"), labels={"study": "other"})
    return cache


def test_views_over_the_live_cache(filled):
    con = query.connect(filled.path)
    assert con.sql("SELECT model, count(*) FROM answers GROUP BY model ORDER BY model").fetchall() == \
        [("fake", 3), ("uniform", 3)]
    assert con.sql("SELECT count(*) FROM labels").fetchone()[0] == 7


def test_json_columns_are_queryable(filled):
    con = query.connect(filled.path)
    rows = con.sql("""SELECT CAST(l.labels->>'n' AS INT) AS n,
                             CAST(a.response->'answers'->'pick'->'probabilities'->>'A' AS DOUBLE) AS p
                      FROM answers a JOIN labels l USING (key)
                      WHERE a.model = 'uniform' AND (l.labels->>'task') = 'demo' ORDER BY n""").fetchall()
    assert rows == [(2, 0.5), (3, pytest.approx(1 / 3)), (4, 0.25)]


def test_reads_while_a_writer_works(filled, router):
    con = query.connect(filled.path)
    router.ask("uniform", choice("X", "Y"))
    assert con.sql("SELECT count(*) FROM answers").fetchone()[0] >= 6


def test_missing_source(tmp_path):
    with pytest.raises(FileNotFoundError):
        query.connect(tmp_path / "nope.sqlite")
    with pytest.raises(FileNotFoundError, match="not an export"):
        query.connect(tmp_path)
