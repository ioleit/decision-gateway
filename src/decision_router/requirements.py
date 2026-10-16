"""Requirements: reject responses from a model if these conditions are not met.

Used to prevent different models served by the same backend configuration from sharing a
cache, for example minor updates without a version jump.

In models.toml, a model's requirements are a table of name = value:

    [models.jev.requirements]
    systemone_response_model_id = "typesafe/jev-1.13-20260917"
    openrouter_response_provider = "TypeSafe"
    "my_checks:SameQuantization" = { quantization = "bf16" }

A name is one of the built-ins below, or "module:Class" for your own: a subclass of
RequestRequirement (checked before a question is sent) or ResponseRequirement (checked on the
result, an answer or a refusal, before it is stored). It is built from the value: a table
becomes keyword arguments, anything else one argument. check() returns None if the requirement
is met, or the reason it is not.

A requirement that is not met stops the call: nothing is sent, or nothing is stored, and
RequirementNotMetError says why. Answers already in the cache are served as they are.

The requirements are part of the cache key: changing them starts a new set of answers.

Open issue: a refusal carries no model id and no provider (OpenRouter's refusal is an HTTP
error with a message only), so the built-in response requirements cannot check it and let it
pass. A change of model is still caught by the answers around it, unless the new model refuses
every question.
"""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from .backends.base import JSONObject
    from .result import DecisionResult


class RequirementNotMetError(Exception):
    """A requirement of a model was not met; the response, if any, was not stored."""


@dataclass(frozen=True)
class Asking:
    """A question about to be asked, as requirements see it."""

    model: str  # the name in models.toml
    wire: JSONObject  # the request as it goes over the network
    now: datetime  # UTC


class RequestRequirement(ABC):
    """Checked before a question is sent."""

    @abstractmethod
    def check(self, asking: Asking) -> str | None:
        """None if the question may be sent, else why not."""


class ResponseRequirement(ABC):
    """Checked on a result (an answer or a refusal) before it is stored."""

    @abstractmethod
    def check(self, asking: Asking, result: DecisionResult) -> str | None:
        """None if the result may be stored, else why not. result.router.response_json is the
        response exactly as received, with fields the SDK's types leave out."""


Requirement = RequestRequirement | ResponseRequirement


class SystemOneResponseModelId(ResponseRequirement):
    """The response's `model` is this id.

    In the System One API, a response's `model` names the model that served the request.
    OpenRouter puts its full model id there, with the release date ("typesafe/jev-1.13-20260917"),
    also when the request asked for "typesafe/jev-1.13" or an alias such as "jev-latest".
    """

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def check(self, asking: Asking, result: DecisionResult) -> str | None:  # noqa: ARG002 (only the result matters)
        response = result.router.response_json
        if response is None:
            return None  # a refusal names no model; see "Open issue" above
        served = response.get("model")
        return None if served == self.model_id else f"served by {served!r}, not {self.model_id!r}"


class OpenRouterResponseProvider(ResponseRequirement):
    """The response's `provider` is this name ("TypeSafe"): OpenRouter adds it to every response."""

    def __init__(self, provider: str) -> None:
        self.provider = provider

    def check(self, asking: Asking, result: DecisionResult) -> str | None:  # noqa: ARG002 (only the result matters)
        response = result.router.response_json
        if response is None:
            return None  # a refusal names no provider; see "Open issue" above
        provider = response.get("provider")
        return None if provider == self.provider else f"served by provider {provider!r}, not {self.provider!r}"


class RequestDateRange(RequestRequirement):
    """New questions only between two times: [start, end], ISO strings or TOML datetimes (no
    offset means UTC).

    A stopgap for models whose responses say nothing about which model answered: it keeps one
    run's answers to a short window, in which the model is assumed not to change.
    """

    def __init__(self, range_: Sequence[datetime | str]) -> None:
        self.start, self.end = (_utc(t) for t in range_)

    def check(self, asking: Asking) -> str | None:
        if self.start <= asking.now <= self.end:
            return None
        return f"new questions may be sent only between {_iso(self.start)} and {_iso(self.end)}"


BUILTIN: dict[str, Callable[..., Requirement]] = {
    "systemone_response_model_id": SystemOneResponseModelId,
    "openrouter_response_provider": OpenRouterResponseProvider,
    "request_date_range": RequestDateRange,
}


def from_config(table: JSONObject) -> list[Requirement]:
    """The requirements of a models.toml `requirements` table."""
    out: list[Requirement] = []
    for name, value in table.items():
        cls = BUILTIN.get(name) or _import(name)
        out.append(cls(**value) if isinstance(value, dict) else cls(value))
    return out


def spec(table: JSONObject) -> JSONObject:
    """The table as JSON (datetimes as ISO text), for the cache key and the stored record."""
    return {k: _jsonable(v) for k, v in table.items()}


def check_request(model: str, requirements: Sequence[Requirement], asking: Asking) -> None:
    for r in requirements:
        if isinstance(r, RequestRequirement) and (reason := r.check(asking)) is not None:
            raise RequirementNotMetError(f"{model}: not sent, {reason} ({type(r).__name__})")


def check_response(model: str, requirements: Sequence[Requirement], asking: Asking, result: DecisionResult) -> None:
    for r in requirements:
        if isinstance(r, ResponseRequirement) and (reason := r.check(asking, result)) is not None:
            raise RequirementNotMetError(f"{model}: result not stored, {reason} ({type(r).__name__})")


def _import(target: str) -> Callable[..., Requirement]:
    module, _, name = target.partition(":")
    if not name:
        raise ValueError(f"unknown requirement {target!r}: not a built-in ({', '.join(BUILTIN)}) nor 'module:Class'")
    cls = getattr(importlib.import_module(module), name)
    if not (isinstance(cls, type) and issubclass(cls, (RequestRequirement, ResponseRequirement))):
        raise TypeError(f"{target} is not a RequestRequirement or ResponseRequirement")
    built: Callable[..., Requirement] = cls
    return built


def _jsonable(value: Any) -> Any:  # noqa: ANN401 (any TOML value)
    if isinstance(value, datetime):
        return _iso(_utc(value))
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def _utc(value: datetime | str) -> datetime:
    """A TOML datetime or an ISO string as an aware UTC datetime; no offset means UTC."""
    when = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return when.astimezone(UTC) if when.tzinfo else when.replace(tzinfo=UTC)


def _iso(when: datetime) -> str:
    return when.isoformat().replace("+00:00", "Z")
