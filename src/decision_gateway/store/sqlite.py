"""SQLiteStore: the store in one SQLite file."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from platformdirs import user_data_dir

from decision_gateway.store.base import Observation, RequestEvent
from decision_gateway.store.key import canonical

# $DECISION_GATEWAY_STORE, or store.sqlite in the user's data directory for the platform
# (~/.local/share/decision-gateway on Linux, ~/Library/Application Support/decision-gateway on macOS).
DEFAULT_PATH = Path(
    os.environ.get("DECISION_GATEWAY_STORE") or Path(user_data_dir("decision-gateway")) / "store.sqlite"
).expanduser()

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id        TEXT PRIMARY KEY,
    key       TEXT NOT NULL,     -- key.py: endpoint, body and assets as sent
    endpoint  TEXT NOT NULL,
    request   TEXT NOT NULL,     -- JSON: the System One request body as sent
    response  TEXT NOT NULL,     -- JSON: the System One response body as received
    model     TEXT,              -- the model the response says answered
    provider  TEXT,              -- the provider the response names, if any
    asked_at  TEXT NOT NULL,     -- UTC, ISO 8601
    cost      REAL               -- usage.cost, if the server reports it
);
CREATE INDEX IF NOT EXISTS observations_key ON observations (key, asked_at);

CREATE TABLE IF NOT EXISTS requests (
    id           TEXT PRIMARY KEY,
    at           TEXT NOT NULL,  -- UTC, ISO 8601
    model        TEXT NOT NULL,  -- the name in models.toml
    key          TEXT NOT NULL,
    labels       TEXT NOT NULL,  -- JSON object
    observation  TEXT,           -- observations.id that answered, if any
    hit          INTEGER NOT NULL,
    accepted     INTEGER NOT NULL,
    reason       TEXT            -- why the observation was not accepted
);
"""


class SQLiteStore:
    """One SQLite file in WAL mode, shared by every process on a machine. Each thread uses its
    own connection; close() closes them all."""

    def __init__(self, path: str | Path = DEFAULT_PATH, timeout: float = 60) -> None:
        self.path = Path(path).expanduser()
        self.timeout = timeout
        self._local = threading.local()
        self._open: list[sqlite3.Connection] = []
        self._open_lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con.executescript(SCHEMA)

    @property
    def con(self) -> sqlite3.Connection:
        con: sqlite3.Connection | None = getattr(self._local, "con", None)
        if con is None:
            # each connection is used by one thread; check_same_thread=False lets close() close them all
            con = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None, check_same_thread=False)
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            self._local.con = con
            with self._open_lock:
                self._open.append(con)
        return con

    def append_observation(self, o: Observation) -> None:
        self.con.execute(
            "INSERT INTO observations (id, key, endpoint, request, response, model, provider, asked_at, cost) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (o.id, o.key, o.endpoint, canonical(o.request), canonical(o.response), o.served_model, o.provider,
             _iso(o.asked_at), o.cost),
        )  # fmt: skip

    def append_request(self, e: RequestEvent) -> None:
        self.con.execute(
            "INSERT INTO requests (id, at, model, key, labels, observation, hit, accepted, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (e.id, _iso(e.at), e.model, e.key, canonical(e.labels), e.observation, int(e.hit), int(e.accepted),
             e.reason),
        )  # fmt: skip

    def observations(self, key: str) -> list[Observation]:
        rows = self.con.execute(
            "SELECT id, key, endpoint, request, response, asked_at, cost FROM observations "
            "WHERE key = ? ORDER BY asked_at, id",
            (key,),
        ).fetchall()
        return [
            Observation(i, k, endpoint, json.loads(req), json.loads(resp), datetime.fromisoformat(at), cost)
            for i, k, endpoint, req, resp, at, cost in rows
        ]

    def close(self) -> None:
        with self._open_lock:
            for con in self._open:
                con.close()
            self._open.clear()
        self._local = threading.local()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat()
