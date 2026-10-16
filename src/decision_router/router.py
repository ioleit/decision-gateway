"""Ask a decision model, from the cache if the question was asked before.

    router = Router(models.load("models.toml"), Cache())
    response = router.ask("uniform", request, labels={"study": "demo", "item": 7})

A question already answered (same model, version and wire) is never asked again. Within one
process, a question being asked is waited for, not asked a second time; across processes, the
cache keeps whichever answer arrives first.
"""

from __future__ import annotations

import threading
import time

from .backends import Backend
from .cache import Cache, Record, key


class Router:
    def __init__(self, models: dict[str, Backend], cache: Cache | None = None):
        self.models = models
        self.cache = cache
        self._lock = threading.Lock()
        self._inflight: dict[str, threading.Event] = {}

    def model(self, name: str) -> Backend:
        try:
            return self.models[name]
        except KeyError:
            raise KeyError(f"unknown model {name!r}; known: {', '.join(self.models)}") from None

    def key(self, name: str, request: dict) -> str | None:
        """The cache key for request to model name, or None if its answers are not cached.
        Makes no call."""
        backend = self.model(name)
        version = backend.version()
        if self.cache is None or not backend.cache or version is None:
            return None
        return key(name, version, backend.wire(_with_model(request, name)))

    def cached(self, name: str, request: dict) -> dict | None:
        """The cached response, without asking; None if there is none."""
        k = self.key(name, request)
        return None if k is None else self.cache.get(k)

    def ask(self, name: str, request: dict, labels: dict | None = None) -> dict:
        """The response to request from model name: cached, or asked and then cached with labels."""
        backend = self.model(name)
        request = _with_model(request, name)
        wire = backend.wire(request)
        k = self.key(name, request)
        if k is None:
            return _checked(backend.call(wire, request).response, request)
        while True:
            with self._lock:
                hit = self.cache.get(k)
                if hit is not None:
                    break
                wait = self._inflight.get(k)
                if wait is None:
                    self._inflight[k] = threading.Event()
                    break
            wait.wait()
        if hit is not None:
            self.cache.label(k, labels)
            return hit
        try:
            reply = backend.call(wire, request)
            response = _checked(reply.response, request)
            self.cache.put(Record(
                key=k, model=name, version=backend.version(), request=request, response=response,
                wire=None if wire == request else wire,
                raw=None if reply.raw in (None, response) else reply.raw,
                asked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                cost=reply.cost, provenance=reply.provenance))
            self.cache.label(k, labels)
            return response
        finally:
            with self._lock:
                self._inflight.pop(k).set()


def _with_model(request: dict, name: str) -> dict:
    return request if request.get("model") == name else {**request, "model": name}


def _checked(response: dict, request: dict) -> dict:
    """A response must answer exactly the questions asked; anything else is an error, not an answer."""
    answers = response.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(request["questions"]):
        raise ValueError(f"response does not answer the questions asked: {str(response)[:300]}")
    return response
