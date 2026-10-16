"""The gateway: an HTTP transport that the TypeSafe SDK client sends its requests through.

    client = TypeSafeClient(..., transport=GatewayTransport(model, store, labels={"project": "evals"}))

The client stays the SDK's own. For each System One request (POST .../v1/systemone with a
JSON body), the gateway

0. adds the model's extra_body fields (from models.toml, e.g. a provider pin) to the body,
   where the request doesn't set them itself;
1. looks up the observations stored for the request's key (key.py) and returns the oldest
   one the model's requirements accept, without a call (a hit);
2. otherwise checks that the requirements allow sending, sends the request, and records the
   response as an observation; if the requirements don't accept it, the call raises
   RequirementNotMetError, and the observation stays recorded;
3. records every request, hit or not, with its labels (labels.py): the transport's own,
   those set by labels() around the call, and those sent with label_headers().

Everything else passes through unchanged and unrecorded: other endpoints, failed responses
(the SDK raises and retries as usual), and requests with assets or a compressed body, which
are not stored yet.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx2
from pydantic import ValidationError

from .key import key
from .labels import HEADER as LABELS_HEADER
from .labels import current as current_labels
from .requirements import Asking, RequirementNotMetError, check_sending, first_rejection
from .store import Observation, RequestEvent
from .systemone import RoutedResponse

if TYPE_CHECKING:
    from .config import ModelConfig
    from .store import Store

SYSTEM_ONE_PATH = "/v1/systemone"


@dataclass(frozen=True)
class _Request:
    """A System One request the gateway handles."""

    endpoint: str
    body: dict[str, Any]
    key: str


class _Gateway:
    def __init__(self, model: ModelConfig, store: Store, labels: dict[str, Any] | None) -> None:
        self.model = model
        self.store = store
        self.labels = dict(labels or {})

    def _labels(self, request: httpx2.Request) -> dict[str, Any]:
        sent = request.headers.get(LABELS_HEADER)
        return {**self.labels, **current_labels(), **(json.loads(sent) if sent else {})}

    def _parse(self, request: httpx2.Request) -> _Request | None:
        """The System One request to handle, or None to pass it through."""
        if request.method != "POST" or not request.url.path.endswith(SYSTEM_ONE_PATH):
            return None
        if not request.headers.get("content-type", "").startswith("application/json"):
            return None  # multipart: a request with assets
        if request.headers.get("content-encoding"):
            return None  # compressed
        body = {**self.model.extra_body, **json.loads(request.content)}
        endpoint = str(request.url.copy_with(query=None))
        return _Request(endpoint, body, key(endpoint, body))

    def _outgoing(self, request: httpx2.Request, req: _Request | None) -> httpx2.Request:
        """The request as sent: without the labels header, with the model's extra_body fields."""
        if LABELS_HEADER not in request.headers and (req is None or not self.model.extra_body):
            return request
        drop = {LABELS_HEADER, "content-length"}
        headers = {k: v for k, v in request.headers.items() if k.lower() not in drop}
        content = json.dumps(req.body).encode() if req is not None else request.content
        return httpx2.Request(
            request.method, request.url, headers=headers, content=content, extensions=request.extensions
        )

    def _lookup(self, req: _Request, tags: dict[str, Any]) -> httpx2.Response | None:
        """A stored answer the model accepts, as a response; recorded as a hit."""
        if not self.model.cache:
            return None
        for observation in self.store.observations(req.key):
            if first_rejection(self.model.requirements, observation) is None:
                self._record(req, observation, tags, hit=True, reason=None)
                return httpx2.Response(200, json=observation.response)
        return None

    def _check_sending(self, req: _Request) -> None:
        check_sending(self.model.name, self.model.requirements, Asking(self.model.name, req.body, _now()))

    def _received(
        self, req: _Request, tags: dict[str, Any], response: httpx2.Response, asked_at: datetime
    ) -> httpx2.Response:
        """Record a response; raise if the model's requirements don't accept it."""
        if response.status_code != httpx2.codes.OK:
            return response
        try:
            received = response.json()
            parsed = RoutedResponse.model_validate(received)
        except (ValueError, ValidationError):
            return response  # not a System One response: the SDK reports it
        if set(parsed.answers) != set(req.body.get("questions", {})):
            return response
        usage = received.get("usage") or {}
        cost = usage.get("cost") if isinstance(usage.get("cost"), int | float) else None
        observation = Observation(str(uuid.uuid4()), req.key, req.endpoint, req.body, received, asked_at, cost)
        self.store.append_observation(observation)
        reason = first_rejection(self.model.requirements, observation)
        self._record(req, observation, tags, hit=False, reason=reason)
        if reason is not None:
            raise RequirementNotMetError(f"{self.model.name}: response not accepted, {reason}")
        return response

    def _record(
        self, req: _Request, observation: Observation, tags: dict[str, Any], *, hit: bool, reason: str | None
    ) -> None:
        self.store.append_request(
            RequestEvent(
                id=str(uuid.uuid4()),
                at=_now(),
                model=self.model.name,
                key=req.key,
                labels=tags,
                observation=observation.id,
                hit=hit,
                accepted=reason is None,
                reason=reason,
            )
        )


class GatewayTransport(_Gateway, httpx2.BaseTransport):
    """The gateway for TypeSafeClient."""

    def __init__(
        self,
        model: ModelConfig,
        store: Store,
        labels: dict[str, Any] | None = None,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        super().__init__(model, store, labels)
        self.transport = transport or httpx2.HTTPTransport()

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        req = self._parse(request)
        if req is None:
            return self.transport.handle_request(self._outgoing(request, None))
        tags = self._labels(request)
        hit = self._lookup(req, tags)
        if hit is not None:
            return hit
        self._check_sending(req)
        asked_at = _now()
        response = self.transport.handle_request(self._outgoing(request, req))
        response.read()
        return self._received(req, tags, response, asked_at)

    def close(self) -> None:
        self.transport.close()


class AsyncGatewayTransport(_Gateway, httpx2.AsyncBaseTransport):
    """The gateway for AsyncTypeSafeClient."""

    def __init__(
        self,
        model: ModelConfig,
        store: Store,
        labels: dict[str, Any] | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(model, store, labels)
        self.transport = transport or httpx2.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        req = self._parse(request)
        if req is None:
            return await self.transport.handle_async_request(self._outgoing(request, None))
        tags = self._labels(request)
        hit = self._lookup(req, tags)
        if hit is not None:
            return hit
        self._check_sending(req)
        asked_at = _now()
        response = await self.transport.handle_async_request(self._outgoing(request, req))
        await response.aread()
        return self._received(req, tags, response, asked_at)

    async def aclose(self) -> None:
        await self.transport.aclose()


def _now() -> datetime:
    return datetime.now(UTC)
