"""Export cached answers chosen by a query to parquet, and optionally to a Hugging Face dataset.

    export(cache_path, "exports/run-1", keys="SELECT key FROM answers WHERE model = 'uniform'")
    push("exports/run-1", "you/decision-answers", private=True)

The export holds answers.parquet and labels.parquet with the cache's columns, so preheat.py
can load it back into a cache with every key unchanged. Needs DuckDB; push needs huggingface_hub.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from decision_router import query
from decision_router.cache.sqlite import COLUMNS, DEFAULT_PATH

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection


def export(source: str | Path = DEFAULT_PATH, out: str | Path = "export", keys: str | None = None) -> tuple[int, int]:
    """Write the answers whose key the `keys` query returns (all if None), and their labels,
    to out/answers.parquet and out/labels.parquet. `keys` runs against query.connect(source).
    Returns (answers, label rows) written."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    con = query.connect(source)
    chosen = f"key IN ({keys})" if keys else "TRUE"
    # JSON columns go out as text, exactly as the cache stores them.
    cols = ", ".join(
        f"CAST({c} AS VARCHAR) AS {c}" if c in {"request", "wire", "response", "raw", "provenance"} else c
        for c in COLUMNS
    )
    con.execute(f"CREATE TEMP TABLE chosen AS SELECT {cols} FROM answers WHERE {chosen} ORDER BY key")
    con.execute(
        "CREATE TEMP TABLE chosen_labels AS SELECT key, CAST(labels AS VARCHAR) AS labels FROM labels "
        "WHERE key IN (SELECT key FROM chosen) ORDER BY key, labels"
    )
    for table, name in (("chosen", "answers"), ("chosen_labels", "labels")):
        con.execute(
            f"COPY {table} TO {query.sql_literal(str(out / f'{name}.parquet'))} (FORMAT parquet, COMPRESSION zstd)"
        )
    n = (_count(con, "chosen"), _count(con, "chosen_labels"))
    con.close()
    return n


def _count(con: DuckDBPyConnection, table: str) -> int:
    row = con.execute(f"SELECT count(*) FROM {table}").fetchone()
    return int(row[0]) if row else 0


class PublicDatasetError(Exception):
    """A private push was asked for, but the dataset already exists and is public."""


def push(out: str | Path, repo_id: str, *, private: bool = True, revision: str | None = None) -> str:
    """Upload an export directory to a Hugging Face dataset repo. Returns the commit URL.

    private=True (the default): a missing dataset is created private, and an existing public
    dataset is refused (PublicDatasetError) rather than published to. private=False: a missing
    dataset is created public. An existing dataset's visibility is never changed."""
    try:
        from huggingface_hub import HfApi
        from huggingface_hub.errors import RepositoryNotFoundError
    except ImportError:
        raise ImportError("push needs huggingface_hub: pip install 'decision-router[hub]'") from None
    api = HfApi()
    try:
        existing = api.repo_info(repo_id, repo_type="dataset")
    except RepositoryNotFoundError:
        api.create_repo(repo_id, repo_type="dataset", private=private)
    else:
        if private and not existing.private:
            raise PublicDatasetError(
                f"{repo_id} is a public dataset; pushing there would publish the export. "
                "Use another dataset, or pass public (--public) if publishing is intended."
            )
    info = api.upload_folder(
        folder_path=str(out),
        repo_id=repo_id,
        repo_type="dataset",
        revision=revision,
        allow_patterns=["answers.parquet", "labels.parquet", "README.md"],
    )
    return str(info)
