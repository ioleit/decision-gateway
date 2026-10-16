"""Helpers for testing code that uses the router, without a network or a real model.

    from decision_gateway import Cache, Router
    from decision_gateway.testing import FakeServer, choice

    server = FakeServer()
    router = Router({"fake": server.model("fake")}, Cache(tmp_path / "cache.sqlite"))
    router.system_one(**choice("A", "B"), model="fake")
    assert server.calls == 1

FakeServer is an HTTP transport for the TypeSafe SDK: requests go through the real SDK client,
and it answers like the uniform model, as OpenRouter would report it (model id, provider, cost).
"""

from __future__ import annotations

import json
import threading
import time
from typing import TYPE_CHECKING, Any

import httpx2

from . import uniform
from .models import Model

if TYPE_CHECKING:
    from .systemone import JSONObject


def choice(*options: str, state: JSONObject | None = None) -> JSONObject:
    """system_one arguments for one choice question, "pick", between the given options."""
    return {
        "state": state or {"case": 1},
        "questions": {"pick": {"type": "choice", "criteria": {o: o for o in options}}},
    }


class FakeServer:
    """A System One server in memory. It counts its calls, keeps the requests, and can be made
    slow, failing (an HTTP status), or answering as another model or provider."""

    def __init__(self, served: str | None = None, provider: str = "Fake", delay: float = 0.0) -> None:
        self.served = served  # the model id it reports; None: the id it was asked for
        self.provider = provider
        self.delay = delay
        self.statuses: list[int] = []  # answered in order with these HTTP errors, then normally
        self.wrong = False  # answer another question than the one asked
        self.calls = 0
        self.requests: list[JSONObject] = []
        self._lock = threading.Lock()
        self.transport = httpx2.MockTransport(self._handle)

    def model(self, name: str, **fields: Any) -> Model:  # noqa: ANN401 (models.toml fields)
        """A models.toml entry for a model served by this server."""
        return Model(name=name, backend="uniform", transport=self.transport, **fields)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        with self._lock:
            self.calls += 1
            self.requests.append(body)
            status = self.statuses.pop(0) if self.statuses else 200
        if self.delay:
            time.sleep(self.delay)
        if status != 200:  # noqa: PLR2004
            return httpx2.Response(status, json={"error": {"code": status, "message": "fake error"}})
        reply = uniform.respond(body, model=self.served or body["model"])
        if self.wrong:
            reply["answers"] = {"other": {"type": "noul", "noul": 0.5}}
        reply.update(id=f"gen-{self.calls}", provider=self.provider)
        reply["usage"]["cost"] = 0.001
        return httpx2.Response(200, json=reply)
