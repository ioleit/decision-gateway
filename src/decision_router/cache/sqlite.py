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
    request: dict
    response: dict
    wire: dict | None = None
    raw: dict | None = None
    asked_at: str | None = None
    cost: float | None = None
    provenance: dict | None = None

    def row(self) -> tuple:
        return tuple(_dump(c, getattr(self, c)) for c in COLUMNS)


def _dump(column: str, value):
    if column in JSON_COLUMNS:
        return None if value is None else canonical(value)
    return value


class Cache:
    def __init__(self, path: str | Path = DEFAULT_PATH, timeout: float = 60):
        self.path = Path(path).expanduser()
        self.timeout = timeout
        self._local = threading.local()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(schema())

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        return con

    @property
    def con(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            con = self._local.con = self._connect()
        return con

    def get(self, key: str) -> dict | None:
        """The stored response for key, or None."""
        row = self.con.execute("SELECT response FROM answers WHERE key = ?", (key,)).fetchone()
        return None if row is None else json.loads(row[0])

    def put(self, record: Record) -> bool:
        """Store an answer; False if the key already had one (which is kept)."""
        cur = self.con.execute(f"INSERT OR IGNORE INTO answers ({', '.join(COLUMNS)}) "
                               f"VALUES ({', '.join('?' * len(COLUMNS))})", record.row())
        return cur.rowcount == 1

    def label(self, key: str, labels: dict | None) -> bool:
        """Record what the question behind key is about; False if empty or already recorded."""
        if not labels:
            return False
        cur = self.con.execute("INSERT OR IGNORE INTO labels (key, labels) VALUES (?, ?)", (key, canonical(labels)))
        return cur.rowcount == 1

    def put_rows(self, answers: list[tuple], labels: list[tuple]) -> tuple[int, int]:
        """Bulk insert of rows in COLUMNS order and (key, labels-JSON) pairs, in one transaction.
        Existing keys and labels are kept. Returns (answers, labels) added."""
        con = self.con
        con.execute("BEGIN IMMEDIATE")  # holds the write lock, so the counts are ours alone
        try:
            before = self.counts()
            con.executemany(f"INSERT OR IGNORE INTO answers ({', '.join(COLUMNS)}) "
                            f"VALUES ({', '.join('?' * len(COLUMNS))})", answers)
            con.executemany("INSERT OR IGNORE INTO labels (key, labels) VALUES (?, ?)", labels)
            after = self.counts()
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        return after[0] - before[0], after[1] - before[1]

    def counts(self) -> tuple[int, int]:
        """(answers, label rows) in the cache."""
        return (self.con.execute("SELECT count(*) FROM answers").fetchone()[0],
                self.con.execute("SELECT count(*) FROM labels").fetchone()[0])

    def close(self) -> None:
        con = getattr(self._local, "con", None)
        if con is not None:
            con.close()
            self._local.con = None
