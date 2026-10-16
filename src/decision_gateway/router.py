"""A drop-in replacement for TypeSafe's SDK client that routes by model name and caches.

    from typesafe_sdk import Noul
    from decision_gateway import Cache, Router, models

    client = Router(models.load("models.toml"), Cache())       # instead of TypeSafeClient(...)
    response = client.system_one(
        state="I was charged twice for my subscription.",
        questions={"refund": Noul(instructions="Is the customer asking for money back?")},
        model="jev",                                             # a name in models.toml
        labels={"study": "demo"},                                # optional, kept with the answer
    )
    response.nouls["refund"].noul

`system_one` takes the same arguments as TypeSafeClient.system_one and returns the same
response type. `model` names an entry in models.toml, which says how the SDK client for it is
configured (base URL, key, model id, provider pin, requirements). AsyncRouter is the same for
AsyncTypeSafeClient.

A question already answered (same model name, requirements and request body) is never asked
again. Within one process, a question being asked is waited for, not asked a second time;
across processes, the cache keeps whichever answer arrives first. Requests with assets
(images) are sent but not cached yet.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Self, TypeVar

from pydantic import BaseModel

from .cache import Cache, Record, key
from .requirements import Asking, check_request, check_response
from .systemone import NotCacheableError, RoutedResponse, check_answers, request_body, wire_questions

if TYPE_CHECKING:
    from collections.abc import Mapping

    import httpx2
    from typesafe_sdk import Asset, AsyncTypeSafeClient, Content, JSONValue, Question, RetryPolicy, TypeSafeClient

    from .models import Model
    from .systemone import JSONObject

ResponseT = TypeVar("ResponseT", bound=BaseModel)


@dataclass
class _Plan:
    """A request, prepared: where it goes, what is sent, and its cache key if it is cached."""

    name: str
    model: Model
    send: dict[str, Any]  # keyword arguments for the SDK's system_one
    wire: JSONObject  # the body as sent (without state if it holds assets)
    questions: Mapping[str, object]
    key: str | None


class _Routing:
    def __init__(
        self, models: Mapping[str, Model], cache: Cache | None = None, default_model: str | None = None
    ) -> None:
        self.models = dict(models)
        self.cache = cache
        self.default_model = default_model

    def model(self, name: str | None) -> Model:
        name = name or self.default_model
        if name is None:
            raise ValueError("no model given, and the router has no default_model")
        try:
            return self.models[name]
        except KeyError:
            raise KeyError(f"unknown model {name!r}; known: {', '.join(self.models)}") from None

    def key(
        self,
        state: Content,
        questions: Mapping[str, Question],
        model: str | None = None,
        extra_body: Mapping[str, JSONValue | None] | None = None,
    ) -> str | None:
        """The cache key of a request, or None if it is not cached. Makes no call."""
        return self._plan(state, questions, model, None, None, None, None, extra_body).key

    def cached(
        self,
        state: Content,
        questions: Mapping[str, Question],
        model: str | None = None,
        extra_body: Mapping[str, JSONValue | None] | None = None,
    ) -> RoutedResponse | None:
        """The cached response to a request, without asking; None if there is none."""
        return self._cached(self._plan(state, questions, model, None, None, None, None, extra_body))

    def _plan(  # noqa: PLR0913, PLR0917 (system_one's arguments)
        self,
        state: Content,
        questions: Mapping[str, Question],
        model: str | None,
        assets: Mapping[str, Asset] | None,
        retry: RetryPolicy | None,
        timeout: float | httpx2.Timeout | None,
        extra_headers: Mapping[str, str] | None,
        extra_body: Mapping[str, JSONValue | None] | None,
    ) -> _Plan:
        m = self.model(model)
        body_extra = {**m.extra_body, **(extra_body or {})}
        send: dict[str, Any] = {"state": state, "questions": questions, "extra_body": body_extra or None}
        send.update({k: v for k, v in (("assets", assets), ("retry", retry), ("timeout", timeout)) if v is not None})
        if extra_headers is not None:
            send["extra_headers"] = extra_headers
        try:
            wire = request_body(state, questions, m.model, body_extra)
            cacheable = self.cache is not None and m.cache and not assets
        except NotCacheableError:
            wire = {"model": m.model, "questions": wire_questions(questions), **body_extra}
            cacheable = False
        k = key(m.name, m.requirements_spec, wire) if cacheable else None
        return _Plan(m.name, m, send, wire, wire["questions"], k)

    def _asking(self, plan: _Plan) -> Asking:
        asking = Asking(model=plan.name, wire=plan.wire, now=datetime.now(UTC))
        check_request(plan.name, plan.model.requirements, asking)
        return asking

    def _checked(self, plan: _Plan, asking: Asking, response: RoutedResponse) -> JSONObject:
        """The response as received, after the API's and the model's checks."""
        check_answers(response, plan.questions)
        check_response(plan.name, plan.model.requirements, asking, response)
        received: JSONObject = response.raw_http_response.json()
        return received

    def _cached(self, plan: _Plan) -> RoutedResponse | None:
        if plan.key is None or self.cache is None:
            return None
        stored = self.cache.get(plan.key)
        if stored is None:
            return None
        response = RoutedResponse.model_validate_json(json.dumps(stored))
        check_answers(response, plan.questions)
        return response

    def _store(self, plan: _Plan, received: JSONObject, labels: JSONObject | None) -> None:
        if self.cache is None or plan.key is None:
            return
        usage = received.get("usage") or {}
        provenance = {k: received[k] for k in ("id", "provider") if received.get(k) is not None}
        self.cache.put(
            Record(
                key=plan.key,
                model=plan.name,
                requirements=plan.model.requirements_spec,
                request=plan.wire,
                response=received,
                asked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                cost=usage.get("cost"),
                provenance=provenance or None,
            )
        )
        self.cache.label(plan.key, labels)

    def _label(self, plan: _Plan, labels: JSONObject | None) -> None:
        if self.cache is not None and plan.key is not None:
            self.cache.label(plan.key, labels)


def _as(response: RoutedResponse, response_model: type[ResponseT] | None) -> Any:  # noqa: ANN401 (the caller's type)
    if response_model is None:
        return response
    return response_model.model_validate_json(json.dumps(response.model_dump(mode="json")))


class Router(_Routing):
    """TypeSafeClient's system_one, routed by model name and cached."""

    def __init__(
        self, models: Mapping[str, Model], cache: Cache | None = None, default_model: str | None = None
    ) -> None:
        super().__init__(models, cache, default_model)
        self._clients: dict[str, TypeSafeClient] = {}
        self._lock = threading.Lock()
        self._inflight: dict[str, threading.Event] = {}

    def system_one(  # noqa: PLR0913, PLR0917 (the same arguments as TypeSafeClient.system_one)
        self,
        state: Content,
        questions: Mapping[str, Question],
        model: str | None = None,
        assets: Mapping[str, Asset] | None = None,
        retry: RetryPolicy | None = None,
        timeout: float | httpx2.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        extra_body: Mapping[str, JSONValue | None] | None = None,
        response_model: type[ResponseT] | None = None,
        *,
        labels: JSONObject | None = None,
    ) -> Any:  # noqa: ANN401 (RoutedResponse, or response_model)
        """TypeSafeClient.system_one, from the cache if this request was answered before.
        labels: what the question is about, in your terms; kept with the answer, not in the key."""
        plan = self._plan(state, questions, model, assets, retry, timeout, extra_headers, extra_body)
        if plan.key is None:
            return _as(self._send(plan)[0], response_model)
        while True:
            with self._lock:
                hit = self._cached(plan)
                if hit is not None:
                    break
                wait = self._inflight.get(plan.key)
                if wait is None:
                    self._inflight[plan.key] = threading.Event()
                    break
            wait.wait()
        if hit is not None:
            self._label(plan, labels)
            return _as(hit, response_model)
        try:
            response, received = self._send(plan)
            self._store(plan, received, labels)
            return _as(response, response_model)
        finally:
            with self._lock:
                self._inflight.pop(plan.key).set()

    def _send(self, plan: _Plan) -> tuple[RoutedResponse, JSONObject]:
        asking = self._asking(plan)
        with self._lock:
            client = self._clients.get(plan.name)
            if client is None:
                client = self._clients[plan.name] = plan.model.client()
        response = client.system_one(**plan.send, response_model=RoutedResponse)
        return response, self._checked(plan, asking, response)

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
        self._clients.clear()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class AsyncRouter(_Routing):
    """AsyncTypeSafeClient's system_one, routed by model name and cached."""

    def __init__(
        self, models: Mapping[str, Model], cache: Cache | None = None, default_model: str | None = None
    ) -> None:
        super().__init__(models, cache, default_model)
        self._clients: dict[str, AsyncTypeSafeClient] = {}
        self._inflight: dict[str, asyncio.Event] = {}

    async def system_one(  # noqa: PLR0913, PLR0917 (the same arguments as AsyncTypeSafeClient.system_one)
        self,
        state: Content,
        questions: Mapping[str, Question],
        model: str | None = None,
        assets: Mapping[str, Asset] | None = None,
        retry: RetryPolicy | None = None,
        timeout: float | httpx2.Timeout | None = None,  # noqa: ASYNC109 (the SDK's argument)
        extra_headers: Mapping[str, str] | None = None,
        extra_body: Mapping[str, JSONValue | None] | None = None,
        response_model: type[ResponseT] | None = None,
        *,
        labels: JSONObject | None = None,
    ) -> Any:  # noqa: ANN401 (RoutedResponse, or response_model)
        """AsyncTypeSafeClient.system_one, from the cache if this request was answered before."""
        plan = self._plan(state, questions, model, assets, retry, timeout, extra_headers, extra_body)
        if plan.key is None:
            return _as((await self._send(plan))[0], response_model)
        while (hit := self._cached(plan)) is None and (wait := self._inflight.get(plan.key)) is not None:
            await wait.wait()
        if hit is not None:
            self._label(plan, labels)
            return _as(hit, response_model)
        self._inflight[plan.key] = asyncio.Event()
        try:
            response, received = await self._send(plan)
            self._store(plan, received, labels)
            return _as(response, response_model)
        finally:
            self._inflight.pop(plan.key).set()

    async def _send(self, plan: _Plan) -> tuple[RoutedResponse, JSONObject]:
        asking = self._asking(plan)
        client = self._clients.get(plan.name)
        if client is None:
            client = self._clients[plan.name] = plan.model.async_client()
        response = await client.system_one(**plan.send, response_model=RoutedResponse)
        return response, self._checked(plan, asking, response)

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
