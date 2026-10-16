"""What the router needs from a backend: how a model is reached.

Requests and responses are TypeSafe's System One API: https://docs.typesafe.ai/api, with the
OpenAPI spec at https://api.typesafe.ai/openapi.json. In short:

    request   {"model": ..., "state": <any JSON>, "questions": {name: {"type": ..., ...}}}
    response  {"model": ..., "answers": {name: {"type": ..., ...}}, "usage": {...}}

An answer the model could not give ({"type": ..., "failed": reason}: a refusal, an unreadable
reply) is a result and is cached like any other. A transport error (timeout, HTTP 5xx) raises
and is not cached.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from decision_router.requirements import from_config, spec

if TYPE_CHECKING:
    from decision_router.requirements import Requirement

JSONObject = dict[str, Any]  # a request, a response, a models.toml entry, ...


@dataclass
class Reply:
    response: JSONObject
    raw: JSONObject | None = None  # the reply as received, if it is not the response
    cost: float | None = None
    provenance: JSONObject | None = None  # generation id, provider, ...


class Backend(ABC):
    """One model as reached through one backend. `entry` is its models.toml table."""

    cache: bool = True  # False: always asked, never stored (also settable per model: cache = false)

    def __init__(self, name: str, entry: JSONObject | None = None) -> None:
        self.name = name  # the name in models.toml: what answers are stored under
        self.entry: JSONObject = entry or {}
        self.display_name: str = self.entry.get("display_name", name)
        self.cache = bool(self.entry.get("cache", type(self).cache))
        table = self.entry.get("requirements", {})
        self.requirements: list[Requirement] = from_config(table)
        self.requirements_spec: JSONObject = spec(table)  # as written, for the cache key

    def wire(self, request: JSONObject) -> JSONObject:
        """What goes over the network for request (its translation for this API, if any)."""
        return request

    @abstractmethod
    def call(self, wire: JSONObject, request: JSONObject) -> Reply:
        """Send wire and return the reply as a response for request."""

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"
