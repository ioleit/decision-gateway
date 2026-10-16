"""Ask a decision model, from the cache if the question was asked before.

    from typesafe_sdk import Noul

    router = Router(models.load("models.toml"), Cache())
    result = router.ask(
        "jev",
        state="I was charged twice for my subscription.",
        questions={"refund": Noul(instructions="Is the customer asking for money back?")},
        labels={"study": "demo", "item": 7},
    )
    result.response.nouls["refund"].noul        # or result.router.refusal, see result.py

Questions and responses are TypeSafe's System One types (see systemone.py). A question
already answered (same model, requirements and request) is never asked again. Within one
process, a question being asked is waited for, not asked a second time; across processes, the
cache keeps whichever answer arrives first.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .cache import Cache, Record, key
from .requirements import Asking, check_request, check_response
from .result import DecisionResult, Refusal, RouterInfo
from .systemone import parse_response, wire_questions

if TYPE_CHECKING:
    from collections.abc import Mapping

    from typesafe_sdk import JSONValue, Question

    from .backends import Backend, JSONObject, Reply


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

    def ask(
        self,
        model: str,
        *,
        state: JSONValue,
        questions: Mapping[str, Question],
        labels: JSONObject | None = None,
    ) -> DecisionResult:
        """The answers of model to questions about state, or its refusal: cached, or asked and
        then cached with labels (what the question is about, in your terms; not in the key)."""
        backend = self.model(model)
        request = _request(model, state, questions)
        wire = backend.wire(request)
        found = self._cached(model, request)
        if found is None:
            return self._call(model, backend, wire, request)[0]
        cache, k = found
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
            return _result(hit.response, hit.refusal, request["questions"])
        try:
            result, reply = self._call(model, backend, wire, request)
            response = reply.response
            cache.put(
                Record(
                    key=k,
                    model=model,
                    requirements=backend.requirements_spec,
                    request=request,
                    response=response,
                    refusal=None if reply.refusal is None else _refusal_json(reply.refusal),
                    wire=None if wire == request else wire,
                    raw=None if reply.raw in (None, response) else reply.raw,
                    asked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    cost=reply.cost,
                    provenance=reply.provenance,
                )
            )
            cache.label(k, labels)
            return result
        finally:
            with self._lock:
                self._inflight.pop(k).set()

    def cached(self, model: str, *, state: JSONValue, questions: Mapping[str, Question]) -> DecisionResult | None:
        """The cached result, without asking; None if there is none."""
        request = _request(model, state, questions)
        found = self._cached(model, request)
        hit = None if found is None else found[0].get(found[1])
        return None if hit is None else _result(hit.response, hit.refusal, request["questions"])

    def key(self, model: str, *, state: JSONValue, questions: Mapping[str, Question]) -> str | None:
        """The cache key of these questions to model, or None if its answers are not cached.
        Makes no call."""
        found = self._cached(model, _request(model, state, questions))
        return None if found is None else found[1]

    def _cached(self, model: str, request: JSONObject) -> tuple[Cache, str] | None:
        """(cache, key) if answers of model to request are cached, else None."""
        backend = self.model(model)
        if self.cache is None or not backend.cache:
            return None
        return self.cache, key(model, backend.requirements_spec, backend.wire(request))

    def _call(
        self, model: str, backend: Backend, wire: JSONObject, request: JSONObject
    ) -> tuple[DecisionResult, Reply]:
        """Ask the backend: the model's requirements checked before and after, a response
        checked against the System One API. Nothing that fails a check is returned."""
        asking = Asking(model=model, wire=wire, now=datetime.now(UTC))
        check_request(model, backend.requirements, asking)
        reply = backend.call(wire, request)
        refusal = None if reply.refusal is None else _refusal_json(reply.refusal)
        result = _result(reply.response, refusal, request["questions"])
        check_response(model, backend.requirements, asking, result)
        return result, reply


def _result(response: JSONObject | None, refusal: JSONObject | None, questions: JSONObject) -> DecisionResult:
    """A stored or received outcome as a DecisionResult; a response must be valid System One."""
    if response is None:
        if refusal is None:
            raise ValueError("neither a response nor a refusal")
        return DecisionResult(None, RouterInfo(refusal=Refusal(**refusal)))
    return DecisionResult(parse_response(response, questions), RouterInfo(response_json=response))


def _refusal_json(refusal: Refusal) -> JSONObject:
    return {"message": refusal.message, "status": refusal.status}


def _request(model: str, state: JSONValue, questions: Mapping[str, Question]) -> JSONObject:
    """The System One request body, before a backend's changes (its model id, provider, ...)."""
    return {"model": model, "state": state, "questions": wire_questions(questions)}
