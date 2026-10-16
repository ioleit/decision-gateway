from datetime import UTC, datetime

import pytest

from decision_gateway.requirements import (
    Asking,
    OpenRouterResponseProvider,
    RequestDateRange,
    Requirement,
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


class MaxCost(Requirement):
    """A custom requirement, as a user would write one: loaded by "module:Class"."""

    def __init__(self, at_most: float) -> None:
        self.at_most = at_most

    def accepts(self, observation: Observation) -> str | None:
        cost = observation.cost or 0.0
        return None if cost <= self.at_most else f"cost {cost} is above {self.at_most}"


def test_systemone_response_model_id() -> None:
    r = SystemOneResponseModelId("typesafe/jev-1.13-20260917")
    assert r.accepts(observed("typesafe/jev-1.13-20260917")) is None
    assert r.accepts(observed("typesafe/jev-1.14-20261101")) == (
        "served by 'typesafe/jev-1.14-20261101', not 'typesafe/jev-1.13-20260917'"
    )
    assert r.allows_sending(Asking("jev", {}, NOW)) is None


def test_openrouter_response_provider() -> None:
    r = OpenRouterResponseProvider("TypeSafe")
    assert r.accepts(observed(provider="TypeSafe")) is None
    assert r.accepts(observed(provider="Other")) == "served by provider 'Other', not 'TypeSafe'"
    assert r.accepts(observed()) == "served by provider None, not 'TypeSafe'"


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
    assert r.accepts(observed(at=NOW)) is None
    assert r.accepts(observed(at=later)) == (
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
            "decision_gateway.requirements_test:MaxCost": {"at_most": 0.01},
        }
    )
    assert [type(r).__name__ for r in rs] == ["SystemOneResponseModelId", "RequestDateRange", "MaxCost"]
    assert first_rejection(rs, observed()) is None
    expensive = Observation("o2", "k", "http://x", {}, {"model": "m"}, NOW, cost=0.5)
    assert first_rejection(rs, expensive) == "cost 0.5 is above 0.01 (MaxCost)"


def test_from_config_errors() -> None:
    with pytest.raises(ValueError, match="unknown requirement 'served'"):
        from_config({"served": "x"})
    with pytest.raises(TypeError, match="is not a Requirement"):
        from_config({"decision_gateway.requirements_test:NOW": "x"})
