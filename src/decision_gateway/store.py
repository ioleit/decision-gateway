"""Where the gateway records what happened: observations and requests, append-only.

    observations  every response received: what was sent, where, the response as received,
                  who answered (the model and provider it reports), when, and the cost.
                  Responses that a model's requirements did not accept are kept too.
    requests      every request made through the gateway: when, with which labels, to which
                  model name; which observation answered it,
                  whether it came from the store (a hit), and whether it was accepted.

Nothing is updated or deleted. Stored answers are found by key (key.py) and then filtered by
the requirements of the model name asking (requirements.py).

Store is the interface; SQLiteStore is the implementation for now.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, Self

from platformdirs import user_data_dir

from .key import canonical

# $DECISION_GATEWAY_STORE, or store.sqlite in the user's data directory for the platform
# (~/.local/share/decision-gateway on Linux, ~/Library/Application Support/decision-gateway on macOS).
DEFAULT_PATH = Path(
    os.environ.get("DECISION_GATEWAY_STORE") or Path(user_data_dir("decision-gateway")) / "store.sqlite"
).expanduser()


@dataclass(frozen=True)
class Observation:
    """A response received for a request."""

    id: str
    key: str
    endpoint: str
    request: dict[str, Any]  # the body as sent
    response: dict[str, Any]  # the body as received
    asked_at: datetime  # UTC
    cost: float | None = None

    @property
    def served_model(self) -> str | None:
        """The model the response says answered (System One's `model`)."""
        model = self.response.get("model")
        return model if isinstance(model, str) else None

    @property
    def provider(self) -> str | None:
        """The provider the response names (OpenRouter's `provider`), if any."""
        provider = self.response.get("provider")
        return provider if isinstance(provider, str) else None


@dataclass(frozen=True)
class RequestEvent:
    """A request made through the gateway, and how it was answered."""

    id: str
    at: datetime  # UTC
    model: str  # the name in models.toml
    key: str
    labels: dict[str, Any] = field(default_factory=dict)
    observation: str | None = None  # the observation that answered, if any
    hit: bool = False  # answered from the store, without a call
    accepted: bool = False  # the observation met the model's requirements
    reason: str | None = None  # why not, if not accepted


class Store(Protocol):
    def append_observation(self, observation: Observation) -> None: ...

    def append_request(self, event: RequestEvent) -> None: ...

    def observations(self, key: str) -> list[Observation]:
        """The observations for a key, oldest first."""
        ...


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
