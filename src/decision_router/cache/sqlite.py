"""The live cache: one SQLite file in WAL mode, shared by every process on the machine.

Writes are INSERT OR IGNORE on the key, so two processes that ask the same question at the
same time both succeed and the first answer stays. Each thread gets its own connection.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Self

from .key import canonical

DEFAULT_PATH = Path(os.environ.get("DECISION_ROUTER_CACHE", "~/.local/share/decision-router/cache.sqlite")).expanduser()

COLUMNS = ("key", "model", "version", "request", "wire", "response", "raw", "asked_at", "cost", "provenance")
JSON_COLUMNS = {"request", "wire", "response", "raw", "provenance"}


def schema() -> str:
    return resources.files(__package__).joinpath("schema.sql").read_text()


@dataclass
class Record:
    key: str
    model: str
    version: str
    request: dict[str, Any]
    response: dict[str, Any]
    wire: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None
    asked_at: str | None = None
    cost: float | None = None
    provenance: dict[str, Any] | None = None

    def row(self) -> Row:
        return tuple(_dump(c, getattr(self, c)) for c in COLUMNS)


Row = tuple[str | float | None, ...]  # one answers row, in COLUMNS order


def _dump(column: str, value: Any) -> str | float | None:  # noqa: ANN401 (a field of Record)
    if column in JSON_COLUMNS:
        return None if value is None else canonical(value)
    plain: str | float | None = value
    return plain


class Cache:
    def __init__(self, path: str | Path = DEFAULT_PATH, timeout: float = 60) -> None:
        self.path = Path(path).expanduser()
        self.timeout = timeout
        self._local = threading.local()
        self._open: list[sqlite3.Connection] = []  # every thread's connection, for close()
        self._open_lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con.executescript(schema())

    def _connect(self) -> sqlite3.Connection:
        # Each connection is used by one thread only; check_same_thread=False lets close()
        # close them all from whichever thread calls it.
        con = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None, check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        return con

    @property
    def con(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            con = self._local.con = self._connect()
            with self._open_lock:
                self._open.append(con)
        return con

    def get(self, key: str) -> dict[str, Any] | None:
        """The stored response for key, or None."""
        row = self.con.execute("SELECT response FROM answers WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        response: dict[str, Any] = json.loads(row[0])
        return response

    def put(self, record: Record) -> bool:
        """Store an answer; False if the key already had one (which is kept)."""
        cur = self.con.execute(
            f"INSERT OR IGNORE INTO answers ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
            record.row(),
        )
        return cur.rowcount == 1

    def label(self, key: str, labels: dict[str, Any] | None) -> bool:
        """Record what the question behind key is about; False if empty or already recorded."""
        if not labels:
            return False
        cur = self.con.execute("INSERT OR IGNORE INTO labels (key, labels) VALUES (?, ?)", (key, canonical(labels)))
        return cur.rowcount == 1

    def put_rows(self, answers: list[Row], labels: list[tuple[str, str]]) -> tuple[int, int]:
        """Bulk insert of rows in COLUMNS order and (key, labels-JSON) pairs, in one transaction.
        Existing keys and labels are kept. Returns (answers, labels) added."""
        con = self.con
        con.execute("BEGIN IMMEDIATE")  # holds the write lock, so the counts are ours alone
        try:
            before = self.counts()
            con.executemany(
                f"INSERT OR IGNORE INTO answers ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                answers,
            )
            con.executemany("INSERT OR IGNORE INTO labels (key, labels) VALUES (?, ?)", labels)
            after = self.counts()
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        return after[0] - before[0], after[1] - before[1]

    def counts(self) -> tuple[int, int]:
        """(answers, label rows) in the cache."""
        return (
            self.con.execute("SELECT count(*) FROM answers").fetchone()[0],
            self.con.execute("SELECT count(*) FROM labels").fetchone()[0],
        )

    def close(self) -> None:
        """Close the connections of every thread that used this cache."""
        with self._open_lock:
            for con in self._open:
                con.close()
            self._open.clear()
        self._local = threading.local()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
