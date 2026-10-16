"""Constraints: conditions on observations, and the helpers to build and check them.

A model's requirements (ModelConfig.requirements, from its `requirements` table in models.toml)
are a list of constraints. They decide which observations (store/) count as that model's
answers: when a request is looked up, and when a new response arrives. Used to prevent
different models served by the same backend configuration from sharing answers, for example
minor updates without a version jump.

A response that violates a constraint stays recorded, and the call raises
ConstraintViolatedError. A constraint can also stop a request before it is sent.

In models.toml, a model's requirements are an inline table of name = value:

    [models.jev]
    requirements = { openrouter_response_provider = "TypeSafe", "my_checks:max_cost" = { at_most = 0.001 } }

A name is one of the built-ins below, or "module:name" for your own:

- a function rejection(observation, ...) -> str | None: None if the observation counts,
  otherwise why not. A table value is passed as keyword arguments, true as nothing, anything
  else as one argument:

      def max_cost(observation, at_most):
          cost = observation.cost or 0.0
          return None if cost <= at_most else f"cost {cost} is above {at_most}"

- or a subclass of Constraint, built from the value the same way, which can also stop a
  request before it is sent (allows_sending).
"""

from __future__ import annotations

import functools
import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from decision_gateway.store import Observation


class ConstraintViolatedError(Exception):
    """A request was not sent, or its response was not accepted, because of a constraint."""


@dataclass(frozen=True)
class Asking:
    """A request about to be sent, as requirements see it."""

    model: str  # the name in models.toml
    body: dict[str, Any]  # the System One request body as it will be sent
    now: datetime  # UTC


class Constraint(ABC):
    @abstractmethod
    def rejection(self, observation: Observation) -> str | None:
        """Why the observation does not count as an answer of this model, or None if it does."""

    def allows_sending(self, asking: Asking) -> str | None:  # noqa: ARG002 (most requirements need not look)
        """Why the request may not be sent, or None if it may. By default every request may."""
        return None

    @property
    def name(self) -> str:
        return type(self).__name__


class FunctionConstraint(Constraint):
    """A plain function as a requirement."""

    def __init__(self, function: Callable[[Observation], str | None], name: str) -> None:
        self.function = function
        self._name = name

    def rejection(self, observation: Observation) -> str | None:
        return self.function(observation)

    @property
    def name(self) -> str:
        return self._name


class SystemOneResponseModelId(Constraint):
    """The response's `model` is this id.

    In the System One API, a response's `model` names the model that served the request.
    OpenRouter puts its full model id there, with the release date ("typesafe/jev-1.13-20260917"),
    also when the request asked for "typesafe/jev-1.13" or an alias such as "jev-latest".
    """

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def rejection(self, observation: Observation) -> str | None:
        served = observation.served_model
        return None if served == self.model_id else f"served by {served!r}, not {self.model_id!r}"


class OpenRouterResponseProvider(Constraint):
    """The response's `provider` is this name ("TypeSafe"): OpenRouter adds it to every response."""

    def __init__(self, provider: str) -> None:
        self.provider = provider

    def rejection(self, observation: Observation) -> str | None:
        provider = observation.provider
        return None if provider == self.provider else f"served by provider {provider!r}, not {self.provider!r}"


class RequestDateRange(Constraint):
    """Only answers asked between two times count: [start, end], ISO strings or TOML datetimes
    (no offset means UTC). Requests outside the range are not sent.

    A stopgap for models whose responses say nothing about which model answered: it keeps one
    run's answers to a short window, in which the model is assumed not to change.
    """

    def __init__(self, range_: Sequence[datetime | str]) -> None:
        self.start, self.end = (_utc(t) for t in range_)

    def rejection(self, observation: Observation) -> str | None:
        if self.start <= observation.asked_at <= self.end:
            return None
        return f"asked at {_iso(observation.asked_at)}, {self._outside()}"

    def allows_sending(self, asking: Asking) -> str | None:
        return None if self.start <= asking.now <= self.end else f"now is {_iso(asking.now)}, {self._outside()}"

    def _outside(self) -> str:
        return f"outside {_iso(self.start)} to {_iso(self.end)}"


BUILTIN: dict[str, type[Constraint]] = {
    "systemone_response_model_id": SystemOneResponseModelId,
    "openrouter_response_provider": OpenRouterResponseProvider,
    "request_date_range": RequestDateRange,
}


def from_config(table: dict[str, Any]) -> list[Constraint]:
    """The requirements of a models.toml `requirements` table."""
    out: list[Constraint] = []
    for name, value in table.items():
        target = BUILTIN.get(name) or _import(name)
        if isinstance(target, type):
            requirement: Constraint = target(**value) if isinstance(value, dict) else target(value)
        else:
            out_name = name.partition(":")[2] or name
            requirement = FunctionConstraint(_bind(target, value), out_name)
        out.append(requirement)
    return out


def first_rejection(requirements: Sequence[Constraint], observation: Observation) -> str | None:
    """None if every requirement accepts the observation, else the first reason it does not."""
    for r in requirements:
        if (reason := r.rejection(observation)) is not None:
            return f"{reason} ({r.name})"
    return None


def check_sending(model: str, requirements: Sequence[Constraint], asking: Asking) -> None:
    for r in requirements:
        if (reason := r.allows_sending(asking)) is not None:
            raise ConstraintViolatedError(f"{model}: not sent, {reason} ({r.name})")


def _bind(function: Callable[..., str | None], value: Any) -> Callable[[Observation], str | None]:  # noqa: ANN401
    """The function with its configured arguments: a table as keywords, true as none, else one."""
    if isinstance(value, dict):
        return functools.partial(function, **value)
    if value is True:
        return function
    return functools.partial(function, value)


def _import(target: str) -> Callable[..., Any]:
    """A Constraint subclass or a function, by "module:name"."""
    module, _, name = target.partition(":")
    if not name:
        raise ValueError(f"unknown requirement {target!r}: not a built-in ({', '.join(BUILTIN)}) nor 'module:name'")
    found = getattr(importlib.import_module(module), name)
    if isinstance(found, type) and not issubclass(found, Constraint):
        raise TypeError(f"{target} is a class but not a Constraint")
    if not callable(found):
        raise TypeError(f"{target} is neither a Constraint nor a function")
    imported: Callable[..., Any] = found
    return imported


def _utc(value: datetime | str) -> datetime:
    """A TOML datetime or an ISO string as an aware UTC datetime; no offset means UTC."""
    when = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return when.astimezone(UTC) if when.tzinfo else when.replace(tzinfo=UTC)


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat().replace("+00:00", "Z")
