"""Helpers for testing code that uses the router, without a network or a real model.

    from decision_router import Cache, Router
    from decision_router.testing import Fake, choice

    fake = Fake("fake")
    router = Router({"fake": fake}, Cache(tmp_path / "cache.sqlite"))
    router.ask("fake", **choice("A", "B"))
    assert fake.calls == 1

Fake answers like the uniform backend, so tests need no network.
"""

from __future__ import annotations

import threading
import time

from .backends import Backend, JSONObject, Reply, Uniform


def choice(*options: str, state: JSONObject | None = None) -> JSONObject:
    """A request with one choice question, "pick", between the given options."""
    return {
        "state": state or {"case": 1},
        "questions": {"pick": {"type": "choice", "criteria": {o: o for o in options}}},
    }


class Fake(Backend):
    """Answers like uniform and counts its calls; can be made slow, failing or wrong."""

    def __init__(self, name: str, entry: JSONObject | None = None, delay: float = 0.0) -> None:
        super().__init__(name, entry)
        self.calls = 0
        self.delay = delay
        self.fail: Exception | None = None  # raised instead of answering
        self.bad = False  # answer another question than the one asked
        self._lock = threading.Lock()

    def call(self, wire: JSONObject, request: JSONObject) -> Reply:
        with self._lock:
            self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise self.fail
        if self.bad:
            return Reply({"model": self.name, "answers": {"other": {"type": "noul", "noul": 0.5}}, "usage": {}})
        reply = Uniform(self.name).call(wire, request)
        return Reply(reply.response, raw={"wrapped": reply.response}, cost=0.001, provenance={"generation": "gen-1"})
