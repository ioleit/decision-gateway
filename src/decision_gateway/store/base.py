"""Where the gateway records what happened: observations and requests, append-only.

    observations  every response received: what was sent, where, the response as received,
                  who answered (the model and provider it reports), when, and the cost.
                  Responses that a model's requirements did not accept are kept too.
    requests      every request made through the gateway: when, with which labels, to which
                  model name; which observation answered it,
                  whether it came from the store (a hit), and whether it was accepted.

Nothing is updated or deleted. Stored answers are found by key (key.py) and then filtered by
the requirements of the model name asking (constraints.py).

Store is the interface; sqlite.py has the implementation for now.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True)
class Observation:
    """A response received for a request."""

    id: str
    key: str
    endpoint: str
    request: dict[str, Any]  # the body as sent
    response: dict[str, Any]  # the body as received
    asked_at: datetime  # UTC
    cost: float | None = None

    @property
    def served_model(self) -> str | None:
        """The model the response says answered (System One's `model`)."""
        model = self.response.get("model")
        return model if isinstance(model, str) else None

    @property
    def provider(self) -> str | None:
        """The provider the response names (OpenRouter's `provider`), if any."""
        provider = self.response.get("provider")
        return provider if isinstance(provider, str) else None


@dataclass(frozen=True)
class RequestEvent:
    """A request made through the gateway, and how it was answered."""

    id: str
    at: datetime  # UTC
    model: str  # the name in models.toml
    key: str
    labels: dict[str, Any] = field(default_factory=dict)
    observation: str | None = None  # the observation that answered, if any
    hit: bool = False  # answered from the store, without a call
    accepted: bool = False  # the observation met the model's requirements
    reason: str | None = None  # why not, if not accepted


class Store(Protocol):
    def append_observation(self, observation: Observation) -> None: ...

    def append_request(self, event: RequestEvent) -> None: ...

    def observations(self, key: str) -> list[Observation]:
        """The observations for a key, oldest first."""
        ...
