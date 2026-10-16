"""Read-only SQL over cached answers, without asking any model. Needs the [query] extra (DuckDB).

    from decision_router import query
    con = query.connect()                      # the live cache (SQLite file)
    con = query.connect("exports/run-1")       # an export: answers.parquet + labels.parquet
    con.sql("SELECT model, count(*) FROM answers GROUP BY model").show()

Two views, the same for both sources:

    answers  key, model, version, request, wire, response, raw, asked_at, cost, provenance
             (the JSON columns as DuckDB JSON: response->>'$.answers.q.choice')
    labels   key, labels (JSON)

In DuckDB, -> and ->> bind more loosely than AND and =, so parenthesize them in conditions:
WHERE model = 'x' AND (labels->>'task') = 'demo'.

Reading the SQLite file uses DuckDB's sqlite extension, which DuckDB downloads on first use.
"""

from __future__ import annotations

from pathlib import Path

from .cache.sqlite import COLUMNS, DEFAULT_PATH, JSON_COLUMNS


def _duckdb():
    try:
        import duckdb
    except ImportError:
        raise ImportError("decision_router.query needs DuckDB: pip install 'decision-router[query]'") from None
    return duckdb


def _select(table: str, columns: tuple[str, ...]) -> str:
    cols = ", ".join(f"CAST({c} AS JSON) AS {c}" if c in JSON_COLUMNS | {"labels"} else c for c in columns)
    return f"SELECT {cols} FROM {table}"


def connect(source: str | Path = DEFAULT_PATH):
    """A DuckDB connection with the views answers and labels over a cache file or an export
    directory. The source is never written to."""
    duckdb = _duckdb()
    source = Path(source).expanduser()
    con = duckdb.connect()
    if source.is_dir():
        a, l = source / "answers.parquet", source / "labels.parquet"
        if not a.exists():
            raise FileNotFoundError(f"{source} is not an export: no answers.parquet")
        con.execute(f"CREATE VIEW answers AS {_select(_parquet(a), COLUMNS)}")
        con.execute(f"CREATE VIEW labels AS {_select(_parquet(l), ('key', 'labels'))}")
    elif source.exists():
        con.execute("INSTALL sqlite; LOAD sqlite")
        con.execute(f"ATTACH {_literal(str(source))} AS cache (TYPE sqlite, READ_ONLY)")
        con.execute(f"CREATE VIEW answers AS {_select('cache.answers', COLUMNS)}")
        con.execute(f"CREATE VIEW labels AS {_select('cache.labels', ('key', 'labels'))}")
    else:
        raise FileNotFoundError(f"no cache or export at {source}")
    return con


def _parquet(path: Path) -> str:
    return f"read_parquet({_literal(str(path))})"


def _literal(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"
