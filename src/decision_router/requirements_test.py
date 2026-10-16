from datetime import UTC, datetime

import pytest

from decision_router import DecisionResult, Refusal, RouterInfo
from decision_router.requirements import (
    Asking,
    OpenRouterResponseProvider,
    RequestDateRange,
    RequestRequirement,
    ResponseRequirement,
    SystemOneResponseModelId,
    from_config,
    spec,
)
from decision_router.systemone import parse_response

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
ASKING = Asking(model="jev", wire={}, now=NOW)


class MaxProbability(ResponseRequirement):
    """A custom requirement, as a user would write one: loaded by "module:Class"."""

    def __init__(self, at_most: float) -> None:
        self.at_most = at_most

    def check(self, asking: Asking, result: DecisionResult) -> str | None:  # noqa: ARG002
        response = result.router.response_json or {"answers": {}}
        top = max(p for a in response["answers"].values() for p in a.get("probabilities", {}).values())
        return None if top <= self.at_most else f"a probability of {top} is above {self.at_most}"


class OnlyModel(RequestRequirement):
    def __init__(self, model: str) -> None:
        self.model = model

    def check(self, asking: Asking) -> str | None:
        return None if asking.model == self.model else f"only for {self.model}"


def answered(model: str, provider: str | None = None) -> DecisionResult:
    """A result with a valid System One response, as an OpenRouter response would give it."""
    response = {"model": model, "answers": {"q": {"type": "noul", "noul": 0.5}}, "usage": {}}
    if provider is not None:
        response["provider"] = provider
    return DecisionResult(parse_response(response, {"q": None}), RouterInfo(response_json=response))


REFUSED = DecisionResult(None, RouterInfo(refusal=Refusal(message="refused to answer", status=502)))


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


def test_built_in_response_requirements_let_refusals_pass() -> None:
    # open issue: a refusal names no model or provider, so these cannot check it
    assert SystemOneResponseModelId("m").check(ASKING, REFUSED) is None
    assert OpenRouterResponseProvider("TypeSafe").check(ASKING, REFUSED) is None


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
            "decision_router.requirements_test:MaxProbability": {"at_most": 0.9},
            "decision_router.requirements_test:OnlyModel": "jev",
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
    probable = {"answers": {"q": {"probabilities": {"A": 0.95, "B": 0.05}}}}
    assert custom.check(ASKING, DecisionResult(None, RouterInfo(response_json=probable))) == (
        "a probability of 0.95 is above 0.9"
    )


def test_from_config_errors() -> None:
    with pytest.raises(ValueError, match="unknown requirement 'served'"):
        from_config({"served": "x"})
    with pytest.raises(TypeError, match="is not a RequestRequirement or ResponseRequirement"):
        from_config({"decision_router.requirements_test:ASKING": "x"})


def test_spec_is_json_with_datetimes_as_text() -> None:
    table = {"request_date_range": [datetime(2026, 10, 16, tzinfo=UTC), "2026-10-17T00:00:00Z"], "x:Y": {"a": 1}}
    assert spec(table) == {"request_date_range": ["2026-10-16T00:00:00Z", "2026-10-17T00:00:00Z"], "x:Y": {"a": 1}}
