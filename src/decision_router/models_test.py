import re
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from decision_router import models
from decision_router.backends import JSONObject, Uniform
from decision_router.requirements import Asking, ResponseRequirement


def test_example_config_loads() -> None:
    ms = models.load(Path(__file__).parents[2] / "models.example.toml")
    assert isinstance(ms["uniform"], Uniform)
    assert ms["uniform"].cache


def test_unknown_backend() -> None:
    with pytest.raises(ValueError, match="unknown backend"):
        models.from_config({"models": {"x": {"backend": "carrier-pigeon"}}})


def test_cache_off_per_model() -> None:
    ms = models.from_config({"models": {"u": {"backend": "uniform", "cache": False}}})
    assert ms["u"].cache is False


class ServesWeights(ResponseRequirement):
    """Stands in for the template's "my_checks:ServesWeights"."""

    def __init__(self, weights: str) -> None:
        self.weights = weights

    def check(self, asking: Asking, response: JSONObject) -> str | None:  # noqa: ARG002
        return None


def test_every_template_in_the_example_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    """The commented-out templates in models.example.toml, uncommented, are valid models."""
    monkeypatch.setitem(sys.modules, "my_checks", SimpleNamespace(ServesWeights=ServesWeights))
    lines, in_template = [], False
    for line in (Path(__file__).parents[2] / "models.example.toml").read_text().splitlines():
        # a template: "# [models.<name>]", then "# <field> = <value>" lines
        starts = re.fullmatch(r"# \[models\.[\w-]+\]", line) is not None
        in_template = starts or (in_template and re.match(r"# \w+ = ", line) is not None)
        lines.append(line.removeprefix("# ") if in_template else line)
    ms = models.from_config(tomllib.loads("\n".join(lines)))
    assert set(ms) == {
        "uniform", "jev", "jev-typesafe", "decider-2026-10-16", "decider-any-provider", "decider-4b-3f2a9c1",
        "team-decider", "wrapped", "uniform-uncached",
    }  # fmt: skip
    assert ms["jev"].display_name == "Jev 1.13 (2026-09-17)"
    assert [type(r).__name__ for r in ms["jev"].requirements] == [
        "SystemOneResponseModelId",
        "OpenRouterResponseProvider",
    ]
    assert [type(r).__name__ for r in ms["decider-2026-10-16"].requirements] == ["RequestDateRange"]
    assert [type(r).__name__ for r in ms["decider-4b-3f2a9c1"].requirements] == ["ServesWeights"]
    assert not ms["decider-any-provider"].cache
    assert not ms["uniform-uncached"].cache
