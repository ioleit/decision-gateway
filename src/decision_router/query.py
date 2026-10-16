"""Read-only SQL over cached answers, without asking any model. Needs the [query] extra (DuckDB).

    from decision_router import query
    con = query.connect()                      # the live cache (SQLite file)
    con = query.connect("exports/run-1")       # an export: answers.parquet + labels.parquet
    con.sql("SELECT model, count(*) FROM answers GROUP BY model").show()

Two views, the same for both sources:

    answers  key, model, requirements, request, wire, response, raw, asked_at, cost, provenance
             (the JSON columns as DuckDB JSON: response->>'$.answers.q.choice')
    labels   key, labels (JSON)

In DuckDB, -> and ->> bind more loosely than AND and =, so parenthesize them in conditions:
WHERE model = 'x' AND (labels->>'task') = 'demo'.

Reading the SQLite file uses DuckDB's sqlite extension, which DuckDB downloads on first use.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from decision_router.cache.sqlite import COLUMNS, DEFAULT_PATH, JSON_COLUMNS

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection


def duckdb_connect() -> DuckDBPyConnection:
    """A new in-memory DuckDB connection; DuckDB is an optional dependency."""
    try:
        import duckdb
    except ImportError:
        raise ImportError("decision_router.query needs DuckDB: pip install 'decision-router[query]'") from None
    return duckdb.connect()


def _select(table: str, columns: tuple[str, ...]) -> str:
    cols = ", ".join(f"CAST({c} AS JSON) AS {c}" if c in JSON_COLUMNS | {"labels"} else c for c in columns)
    return f"SELECT {cols} FROM {table}"


def connect(source: str | Path = DEFAULT_PATH) -> DuckDBPyConnection:
    """A DuckDB connection with the views answers and labels over a cache file or an export
    directory. The source is never written to."""
    source = Path(source).expanduser()
    if not source.exists():
        raise FileNotFoundError(f"no cache or export at {source}")
    if source.is_dir() and not (source / "answers.parquet").exists():
        raise FileNotFoundError(f"{source} is not an export: no answers.parquet")
    con = duckdb_connect()
    if source.is_dir():
        answers, labels = source / "answers.parquet", source / "labels.parquet"
        con.execute(f"CREATE VIEW answers AS {_select(read_parquet(answers), COLUMNS)}")
        con.execute(f"CREATE VIEW labels AS {_select(read_parquet(labels), ('key', 'labels'))}")
    else:
        con.execute("INSTALL sqlite; LOAD sqlite")
        con.execute(f"ATTACH {sql_literal(str(source))} AS cache (TYPE sqlite, READ_ONLY)")
        con.execute(f"CREATE VIEW answers AS {_select('cache.answers', COLUMNS)}")
        con.execute(f"CREATE VIEW labels AS {_select('cache.labels', ('key', 'labels'))}")
    return con


def read_parquet(path: Path) -> str:
    """SQL for reading a parquet file."""
    return f"read_parquet({sql_literal(str(path))})"


def sql_literal(s: str) -> str:
    """s as a quoted SQL string literal."""
    return "'" + s.replace("'", "''") + "'"
