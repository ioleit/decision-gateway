"""Requirements: which answers a model name accepts.

Used to prevent different models served by the same backend configuration from sharing
answers, for example minor updates without a version jump.

Every response is recorded as an observation (store.py). A model's requirements decide which
observations count as that model's answers: when a request is looked up, and when a new
response arrives. A response that is not accepted stays recorded, and the call raises
RequirementNotMetError. A requirement can also stop a request before it is sent.

In models.toml, a model's requirements are a table of name = value:

    [models.jev.requirements]
    systemone_response_model_id = "typesafe/jev-1.13-20260917"
    openrouter_response_provider = "TypeSafe"
    "my_checks:SameQuantization" = { quantization = "bf16" }

A name is one of the built-ins below, or "module:Class" for your own subclass of Requirement,
built from the value: a table becomes keyword arguments, anything else one argument.
"""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from .store import Observation


class RequirementNotMetError(Exception):
    """A request was not sent, or its response was not accepted, because of a requirement."""


@dataclass(frozen=True)
class Asking:
    """A request about to be sent, as requirements see it."""

    model: str  # the name in models.toml
    body: dict[str, Any]  # the System One request body as it will be sent
    now: datetime  # UTC


class Requirement(ABC):
    @abstractmethod
    def accepts(self, observation: Observation) -> str | None:
        """None if the observation counts as an answer of this model, else why not."""

    def allows_sending(self, asking: Asking) -> str | None:  # noqa: ARG002 (most requirements need not look)
        """None if the request may be sent, else why not. By default every request may."""
        return None


class SystemOneResponseModelId(Requirement):
    """The response's `model` is this id.

    In the System One API, a response's `model` names the model that served the request.
    OpenRouter puts its full model id there, with the release date ("typesafe/jev-1.13-20260917"),
    also when the request asked for "typesafe/jev-1.13" or an alias such as "jev-latest".
    """

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def accepts(self, observation: Observation) -> str | None:
        served = observation.served_model
        return None if served == self.model_id else f"served by {served!r}, not {self.model_id!r}"


class OpenRouterResponseProvider(Requirement):
    """The response's `provider` is this name ("TypeSafe"): OpenRouter adds it to every response."""

    def __init__(self, provider: str) -> None:
        self.provider = provider

    def accepts(self, observation: Observation) -> str | None:
        provider = observation.provider
        return None if provider == self.provider else f"served by provider {provider!r}, not {self.provider!r}"


class RequestDateRange(Requirement):
    """Only answers asked between two times count: [start, end], ISO strings or TOML datetimes
    (no offset means UTC). Requests outside the range are not sent.

    A stopgap for models whose responses say nothing about which model answered: it keeps one
    run's answers to a short window, in which the model is assumed not to change.
    """

    def __init__(self, range_: Sequence[datetime | str]) -> None:
        self.start, self.end = (_utc(t) for t in range_)

    def accepts(self, observation: Observation) -> str | None:
        return (
            None
            if self.start <= observation.asked_at <= self.end
            else f"asked at {_iso(observation.asked_at)}, {self._range()}"
        )

    def allows_sending(self, asking: Asking) -> str | None:
        return None if self.start <= asking.now <= self.end else f"now is {_iso(asking.now)}, {self._range()}"

    def _range(self) -> str:
        return f"outside {_iso(self.start)} to {_iso(self.end)}"


BUILTIN: dict[str, Callable[..., Requirement]] = {
    "systemone_response_model_id": SystemOneResponseModelId,
    "openrouter_response_provider": OpenRouterResponseProvider,
    "request_date_range": RequestDateRange,
}


def from_config(table: dict[str, Any]) -> list[Requirement]:
    """The requirements of a models.toml `requirements` table."""
    out: list[Requirement] = []
    for name, value in table.items():
        cls = BUILTIN.get(name) or _import(name)
        out.append(cls(**value) if isinstance(value, dict) else cls(value))
    return out


def first_rejection(requirements: Sequence[Requirement], observation: Observation) -> str | None:
    """None if every requirement accepts the observation, else the first reason it is not."""
    for r in requirements:
        if (reason := r.accepts(observation)) is not None:
            return f"{reason} ({type(r).__name__})"
    return None


def check_sending(model: str, requirements: Sequence[Requirement], asking: Asking) -> None:
    for r in requirements:
        if (reason := r.allows_sending(asking)) is not None:
            raise RequirementNotMetError(f"{model}: not sent, {reason} ({type(r).__name__})")


def _import(target: str) -> Callable[..., Requirement]:
    module, _, name = target.partition(":")
    if not name:
        raise ValueError(f"unknown requirement {target!r}: not a built-in ({', '.join(BUILTIN)}) nor 'module:Class'")
    cls = getattr(importlib.import_module(module), name)
    if not (isinstance(cls, type) and issubclass(cls, Requirement)):
        raise TypeError(f"{target} is not a Requirement")
    built: Callable[..., Requirement] = cls
    return built


def _utc(value: datetime | str) -> datetime:
    """A TOML datetime or an ISO string as an aware UTC datetime; no offset means UTC."""
    when = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return when.astimezone(UTC) if when.tzinfo else when.replace(tzinfo=UTC)


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat().replace("+00:00", "Z")
