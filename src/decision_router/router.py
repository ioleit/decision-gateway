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
from typing import TYPE_CHECKING

from .cache import Cache, Record, key

if TYPE_CHECKING:
    from .backends import Backend, JSONObject


class Router:
    def __init__(self, models: dict[str, Backend], cache: Cache | None = None) -> None:
        self.models = models
        self.cache = cache
        self._lock = threading.Lock()
        self._inflight: dict[str, threading.Event] = {}

    def model(self, name: str) -> Backend:
        try:
            return self.models[name]
        except KeyError:
            raise KeyError(f"unknown model {name!r}; known: {', '.join(self.models)}") from None

    def _cached(self, name: str, request: JSONObject) -> tuple[Cache, str, str] | None:
        """(cache, version, key) if answers of model name to request are cached, else None."""
        backend = self.model(name)
        version = backend.version()
        if self.cache is None or not backend.cache or version is None:
            return None
        return self.cache, version, key(name, version, backend.wire(request))

    def key(self, name: str, request: JSONObject) -> str | None:
        """The cache key for request to model name, or None if its answers are not cached.
        Makes no call."""
        found = self._cached(name, _with_model(request, name))
        return None if found is None else found[2]

    def cached(self, name: str, request: JSONObject) -> JSONObject | None:
        """The cached response, without asking; None if there is none."""
        found = self._cached(name, _with_model(request, name))
        return None if found is None else found[0].get(found[2])

    def ask(self, name: str, request: JSONObject, labels: JSONObject | None = None) -> JSONObject:
        """The response to request from model name: cached, or asked and then cached with labels."""
        backend = self.model(name)
        request = _with_model(request, name)
        wire = backend.wire(request)
        found = self._cached(name, request)
        if found is None:
            return _checked(backend.call(wire, request).response, request)
        cache, version, k = found
        while True:
            with self._lock:
                hit = cache.get(k)
                if hit is not None:
                    break
                wait = self._inflight.get(k)
                if wait is None:
                    self._inflight[k] = threading.Event()
                    break
            wait.wait()
        if hit is not None:
            cache.label(k, labels)
            return hit
        try:
            reply = backend.call(wire, request)
            response = _checked(reply.response, request)
            cache.put(
                Record(
                    key=k,
                    model=name,
                    version=version,
                    request=request,
                    response=response,
                    wire=None if wire == request else wire,
                    raw=None if reply.raw in (None, response) else reply.raw,
                    asked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    cost=reply.cost,
                    provenance=reply.provenance,
                )
            )
            cache.label(k, labels)
            return response
        finally:
            with self._lock:
                self._inflight.pop(k).set()


def _with_model(request: JSONObject, name: str) -> JSONObject:
    return request if request.get("model") == name else {**request, "model": name}


def _checked(response: JSONObject, request: JSONObject) -> JSONObject:
    """A response must answer exactly the questions asked; anything else is an error, not an answer."""
    answers = response.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(request["questions"]):
        raise ValueError(f"response does not answer the questions asked: {str(response)[:300]}")
    return response
