"""FakeTransport: a System One server in memory, for tests of code that uses the gateway.

    from decision_gateway import Gateway, SQLiteStore
    from decision_gateway.testing import FakeTransport, choice

    fake = FakeTransport()
    gateway = Gateway({"fake": fake.model("fake")}, SQLiteStore(tmp_path / "store.sqlite"))
    gateway.client("fake").system_one(**choice("A", "B"))
    assert fake.calls == 1

Requests go through the real SDK client. It answers like the uniform baseline, as OpenRouter
would report it (model id, provider, cost).
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx2

from decision_gateway.config import ModelConfig
from decision_gateway.transports.uniform_transport import respond


class FakeTransport(httpx2.BaseTransport, httpx2.AsyncBaseTransport):
    """Counts its calls, keeps the requests, and can be made slow, failing (an HTTP status), or
    answering as another model or provider."""

    def __init__(self, served: str | None = None, provider: str = "Fake", delay: float = 0.0) -> None:
        self.served = served  # the model id it reports; None: the id it was asked for
        self.provider = provider
        self.delay = delay
        self.statuses: list[int] = []  # answered in order with these HTTP errors, then normally
        self.wrong = False  # answer another question than the one asked
        self.calls = 0
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def model(self, name: str, **fields: Any) -> ModelConfig:  # noqa: ANN401 (models.toml fields)
        """A models.toml entry for a model served by this transport."""
        fields.setdefault("base_url", f"http://{name}.fake.invalid")
        return ModelConfig(name=name, backend="uniform", transport=self, **fields)

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        with self._lock:
            self.calls += 1
            self.requests.append(body)
            status = self.statuses.pop(0) if self.statuses else 200
        if self.delay:
            time.sleep(self.delay)
        if status != httpx2.codes.OK:
            return httpx2.Response(status, json={"error": {"code": status, "message": "fake error"}})
        reply = respond(body, model=self.served or body["model"])
        if self.wrong:
            reply["answers"] = {"other": {"type": "noul", "noul": 0.5}}
        reply.update(id=f"gen-{self.calls}", provider=self.provider)
        reply["usage"]["cost"] = 0.001
        return httpx2.Response(200, json=reply)

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        return self.handle_request(request)
