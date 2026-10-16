from conftest import choice
from decision_router import Cache
from decision_router.cli import main


def test_query_export_preheat(tmp_path, router, cache, capsys):
    for n in (2, 3):
        router.ask("uniform", choice(*"ABC"[:n]))
    db = str(cache.path)

    assert main(["--cache", db, "query", "--csv", "SELECT model, count(*) AS n FROM answers GROUP BY model"]) == 0
    assert capsys.readouterr().out.splitlines() == ["model,n", "uniform,2"]

    assert main(["--cache", db, "export", str(tmp_path / "exp")]) == 0
    assert "exported 2 answers" in capsys.readouterr().out

    fresh = tmp_path / "fresh.sqlite"
    assert main(["--cache", str(fresh), "preheat", str(tmp_path / "exp")]) == 0
    assert "added 2 answers" in capsys.readouterr().out
    assert Cache(fresh).counts() == (2, 0)

    assert main(["query", "--source", str(tmp_path / "exp"), "--csv", "SELECT count(*) AS n FROM answers"]) == 0
    assert capsys.readouterr().out.splitlines() == ["n", "2"]
