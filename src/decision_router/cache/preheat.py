"""Load an export into a cache, so the answers in it are served without asking any model.

    preheat("exports/run-1", Cache())          # a local export directory
    preheat("hf://you/decision-answers", Cache())   # a Hugging Face dataset (downloaded first)

Keys are taken as they are in the export; answers and labels the cache already has are kept.
Needs DuckDB; hf:// sources need huggingface_hub.
"""

from __future__ import annotations

from pathlib import Path

from decision_router import query
from decision_router.cache.sqlite import COLUMNS, Cache

BATCH = 10_000


def download(source: str, revision: str | None = None) -> Path:
    """hf://owner/name -> a local directory with the export's files."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        raise ImportError("hf:// sources need huggingface_hub: pip install 'decision-router[hub]'") from None
    repo_id = source.removeprefix("hf://")
    return Path(
        snapshot_download(
            repo_id, repo_type="dataset", revision=revision, allow_patterns=["answers.parquet", "labels.parquet"]
        )
    )


def preheat(source: str | Path, cache: Cache, revision: str | None = None) -> tuple[int, int]:
    """Add the export's answers and labels to cache. Returns (answers, label rows) added."""
    if str(source).startswith("hf://"):
        source = download(str(source), revision)
    source = Path(source)
    con = query.duckdb_connect()
    cols = ", ".join(COLUMNS)
    answers = con.execute(f"SELECT {cols} FROM {query.read_parquet(source / 'answers.parquet')}")
    labels_file = source / "labels.parquet"
    added = [0, 0]
    while rows := answers.fetchmany(BATCH):
        a, _ = cache.put_rows(rows, [])
        added[0] += a
    if labels_file.exists():
        labels = con.execute(f"SELECT key, labels FROM {query.read_parquet(labels_file)}")
        while rows := labels.fetchmany(BATCH):
            _, n = cache.put_rows([], rows)
            added[1] += n
    con.close()
    return added[0], added[1]
