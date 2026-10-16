from datetime import UTC, datetime

import pytest

from decision_gateway.constraints import (
    Asking,
    Constraint,
    OpenRouterResponseProvider,
    RequestDateRange,
    SystemOneResponseModelId,
    first_rejection,
    from_config,
)
from decision_gateway.store import Observation

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def observed(model: str = "m", provider: str | None = None, at: datetime = NOW) -> Observation:
    response: dict[str, object] = {"model": model, "answers": {}, "usage": {}}
    if provider is not None:
        response["provider"] = provider
    return Observation("o1", "k", "http://x/v1/systemone", {}, response, at)


def max_cost(observation: Observation, at_most: float) -> str | None:
    """A requirement as a plain function, loaded by "module:name"."""
    cost = observation.cost or 0.0
    return None if cost <= at_most else f"cost {cost} is above {at_most}"


def no_cost_known(observation: Observation) -> str | None:
    return None if observation.cost is None else "a cost is known"


class MaxCost(Constraint):
    """A requirement as a class, loaded by "module:Name"."""

    def __init__(self, at_most: float) -> None:
        self.at_most = at_most

    def rejection(self, observation: Observation) -> str | None:
        cost = observation.cost or 0.0
        return None if cost <= self.at_most else f"cost {cost} is above {self.at_most}"


def test_systemone_response_model_id() -> None:
    r = SystemOneResponseModelId("typesafe/jev-1.13-20260917")
    assert r.rejection(observed("typesafe/jev-1.13-20260917")) is None
    assert r.rejection(observed("typesafe/jev-1.14-20261101")) == (
        "served by 'typesafe/jev-1.14-20261101', not 'typesafe/jev-1.13-20260917'"
    )
    assert r.allows_sending(Asking("jev", {}, NOW)) is None


def test_openrouter_response_provider() -> None:
    r = OpenRouterResponseProvider("TypeSafe")
    assert r.rejection(observed(provider="TypeSafe")) is None
    assert r.rejection(observed(provider="Other")) == "served by provider 'Other', not 'TypeSafe'"
    assert r.rejection(observed()) == "served by provider None, not 'TypeSafe'"


@pytest.mark.parametrize(
    "range_",
    [
        ["2026-10-16T00:00:00Z", "2026-10-17T00:00:00Z"],
        ["2026-10-16T00:00:00", "2026-10-17T00:00:00"],  # no offset: UTC
        ["2026-10-16T02:00:00+02:00", "2026-10-17T02:00:00+02:00"],
        [datetime(2026, 10, 16, tzinfo=UTC), datetime(2026, 10, 17, tzinfo=UTC)],  # TOML datetimes
        [datetime(2026, 10, 16), datetime(2026, 10, 17)],  # noqa: DTZ001 (TOML local datetimes)
    ],
)
def test_request_date_range(range_: list[datetime | str]) -> None:
    r = RequestDateRange(range_)
    later = datetime(2026, 10, 17, 0, 0, 1, tzinfo=UTC)
    assert r.rejection(observed(at=NOW)) is None
    assert r.rejection(observed(at=later)) == (
        "asked at 2026-10-17T00:00:01Z, outside 2026-10-16T00:00:00Z to 2026-10-17T00:00:00Z"
    )
    assert r.allows_sending(Asking("m", {}, NOW)) is None
    assert r.allows_sending(Asking("m", {}, later)) == (
        "now is 2026-10-17T00:00:01Z, outside 2026-10-16T00:00:00Z to 2026-10-17T00:00:00Z"
    )


def test_from_config_builtins_and_custom() -> None:
    rs = from_config(
        {
            "systemone_response_model_id": "m",
            "request_date_range": ["2026-10-16T00:00:00Z", "2026-10-17T00:00:00Z"],
            "decision_gateway.constraints_test:MaxCost": {"at_most": 0.01},
        }
    )
    assert [r.name for r in rs] == ["SystemOneResponseModelId", "RequestDateRange", "MaxCost"]
    assert first_rejection(rs, observed()) is None
    expensive = Observation("o2", "k", "http://x", {}, {"model": "m"}, NOW, cost=0.5)
    assert first_rejection(rs, expensive) == "cost 0.5 is above 0.01 (MaxCost)"


def test_plain_functions_as_requirements() -> None:
    rs = from_config(
        {
            "decision_gateway.constraints_test:max_cost": {"at_most": 0.01},
            "decision_gateway.constraints_test:no_cost_known": True,
        }
    )
    assert [r.name for r in rs] == ["max_cost", "no_cost_known"]
    assert first_rejection(rs, observed()) is None
    expensive = Observation("o2", "k", "http://x", {}, {"model": "m"}, NOW, cost=0.5)
    assert first_rejection(rs, expensive) == "cost 0.5 is above 0.01 (max_cost)"
    assert rs[1].allows_sending(Asking("m", {}, NOW)) is None


def test_from_config_errors() -> None:
    with pytest.raises(ValueError, match="unknown requirement 'served'"):
        from_config({"served": "x"})
    with pytest.raises(TypeError, match="neither a Constraint nor a function"):
        from_config({"decision_gateway.constraints_test:NOW": "x"})
    with pytest.raises(TypeError, match="a class but not a Constraint"):
        from_config({"decision_gateway.constraints_test:Observation": "x"})
