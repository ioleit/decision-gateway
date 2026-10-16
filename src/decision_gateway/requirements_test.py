from datetime import UTC, datetime

import pytest

from decision_gateway import RoutedResponse
from decision_gateway.requirements import (
    Asking,
    OpenRouterResponseProvider,
    RequestDateRange,
    RequestRequirement,
    ResponseRequirement,
    SystemOneResponseModelId,
    from_config,
    spec,
)

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
ASKING = Asking(model="jev", wire={}, now=NOW)


class MaxProbability(ResponseRequirement):
    """A custom requirement, as a user would write one: loaded by "module:Class"."""

    def __init__(self, at_most: float) -> None:
        self.at_most = at_most

    def check(self, asking: Asking, response: RoutedResponse) -> str | None:  # noqa: ARG002
        top = max(p for c in response.choices.values() for p in c.probabilities.values())
        return None if top <= self.at_most else f"a probability of {top} is above {self.at_most}"


class OnlyModel(RequestRequirement):
    def __init__(self, model: str) -> None:
        self.model = model

    def check(self, asking: Asking) -> str | None:
        return None if asking.model == self.model else f"only for {self.model}"


def answered(model: str, provider: str | None = None) -> RoutedResponse:
    """A response as OpenRouter would give it."""
    response: dict[str, object] = {"model": model, "answers": {"q": {"type": "noul", "noul": 0.5}}, "usage": {}}
    if provider is not None:
        response["provider"] = provider
    return RoutedResponse.model_validate(response)


def test_systemone_response_model_id() -> None:
    r = SystemOneResponseModelId("typesafe/jev-1.13-20260917")
    assert r.check(ASKING, answered("typesafe/jev-1.13-20260917")) is None
    assert r.check(ASKING, answered("typesafe/jev-1.14-20261101")) == (
        "served by 'typesafe/jev-1.14-20261101', not 'typesafe/jev-1.13-20260917'"
    )


def test_openrouter_response_provider() -> None:
    r = OpenRouterResponseProvider("TypeSafe")
    assert r.check(ASKING, answered("m", provider="TypeSafe")) is None
    assert r.check(ASKING, answered("m", provider="Other")) == "served by provider 'Other', not 'TypeSafe'"
    assert r.check(ASKING, answered("m")) == "served by provider None, not 'TypeSafe'"


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
    assert r.check(ASKING) is None
    later = Asking(model="jev", wire={}, now=datetime(2026, 10, 17, 0, 0, 1, tzinfo=UTC))
    assert r.check(later) == "new questions may be sent only between 2026-10-16T00:00:00Z and 2026-10-17T00:00:00Z"


def test_from_config_builtins_and_custom() -> None:
    rs = from_config(
        {
            "systemone_response_model_id": "typesafe/jev-1.13-20260917",
            "request_date_range": ["2026-10-16T00:00:00Z", "2026-10-17T00:00:00Z"],
            "decision_gateway.requirements_test:MaxProbability": {"at_most": 0.9},
            "decision_gateway.requirements_test:OnlyModel": "jev",
        }
    )
    assert [type(r).__name__ for r in rs] == [
        "SystemOneResponseModelId",
        "RequestDateRange",
        "MaxProbability",
        "OnlyModel",
    ]
    custom = rs[2]
    assert isinstance(custom, MaxProbability)
    probable = {"type": "choice", "choice": "A", "confidence": 0.95, "probabilities": {"A": 0.95, "B": 0.05}}
    response = RoutedResponse.model_validate({"model": "m", "answers": {"q": probable}, "usage": {}})
    assert custom.check(ASKING, response) == ("a probability of 0.95 is above 0.9")


def test_from_config_errors() -> None:
    with pytest.raises(ValueError, match="unknown requirement 'served'"):
        from_config({"served": "x"})
    with pytest.raises(TypeError, match="is not a RequestRequirement or ResponseRequirement"):
        from_config({"decision_gateway.requirements_test:ASKING": "x"})


def test_spec_is_json_with_datetimes_as_text() -> None:
    table = {"request_date_range": [datetime(2026, 10, 16, tzinfo=UTC), "2026-10-17T00:00:00Z"], "x:Y": {"a": 1}}
    assert spec(table) == {"request_date_range": ["2026-10-16T00:00:00Z", "2026-10-17T00:00:00Z"], "x:Y": {"a": 1}}
