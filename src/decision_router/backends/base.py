"""What the router needs from a backend: how a model is reached, and what version answers.

Request and response follow the Jev / SystemOne shape:

    request   {"model": ..., "state": <any JSON>, "questions": {name: {"type": ..., "criteria": ...}}}
    response  {"model": ..., "answers": {name: {"type": ..., "choice"|"noul"|"score": ...,
                                                "probabilities": {...}}}, "usage": ...}

An answer the model could not give ({"type": ..., "failed": reason}: a refusal, an unreadable
reply) is a result and is cached like any other. A transport error (timeout, HTTP 5xx) raises
and is not cached.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Reply:
    response: dict
    raw: dict | None = None         # the reply as received, if it is not the response
    cost: float | None = None
    provenance: dict | None = None  # generation id, provider, ...


class Backend(ABC):
    """One model as reached through one backend. `entry` is its models.toml table."""

    cache = True  # False: always asked, never stored (also settable per model: cache = false)

    def __init__(self, name: str, entry: dict | None = None):
        self.name = name
        self.entry = entry or {}
        self.cache = self.entry.get("cache", type(self).cache)

    def version(self) -> str | None:
        """What answers, as it goes into the cache key. None: unknown, so nothing is cached."""
        return self.entry.get("version")

    def wire(self, request: dict) -> dict:
        """What goes over the network for request (its translation for this API, if any)."""
        return request

    @abstractmethod
    def call(self, wire: dict, request: dict) -> Reply:
        """Send wire and return the reply as a response for request."""

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"
