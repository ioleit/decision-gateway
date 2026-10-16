import re
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from decision_gateway import Observation, Requirement, models
from decision_gateway.models import MissingKeyError, Model

EXAMPLE = Path(__file__).parents[2] / "models.example.toml"


def test_backend_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key")
    jev = Model(name="jev", backend="openrouter", model="typesafe/jev-1.13")
    assert jev.client_options() == {
        "api_key": "or-key",
        "model": "typesafe/jev-1.13",
        "base_url": "https://openrouter.ai/api",
        "compression": False,
    }
    direct = Model(name="jev-1.13", timeout=30, max_retries=5)
    options = direct.client_options()
    assert (options["api_key"], options["model"], options["base_url"], options["timeout"]) == (
        "ts-key",
        "jev-1.13",
        None,
        30,
    )
    assert options["retry"].max_retries == 5
    assert "compression" not in options  # the SDK's default
    assert direct.display_name == "jev-1.13"


def test_a_missing_key() -> None:
    with pytest.raises(MissingKeyError, match="NO_SUCH_KEY"):
        Model(name="m", key_env="NO_SUCH_KEY").client_options()


def test_config_errors() -> None:
    with pytest.raises(ValueError, match="unknown backend"):
        models.from_config({"models": {"x": {"backend": "carrier-pigeon"}}})
    with pytest.raises(ValueError, match=r"unknown fields \['served'\]"):
        models.from_config({"models": {"x": {"served": "y"}}})


def test_cache_off_per_model() -> None:
    assert models.from_config({"models": {"u": {"backend": "uniform", "cache": False}}})["u"].cache is False


class MaxCost(Requirement):
    """Stands in for the template's "my_checks:MaxCost"."""

    def __init__(self, at_most: float) -> None:
        self.at_most = at_most

    def accepts(self, observation: Observation) -> str | None:  # noqa: ARG002
        return None


def test_every_template_in_the_example_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    """The commented-out templates in models.example.toml, uncommented, are valid models."""
    monkeypatch.setitem(sys.modules, "my_checks", SimpleNamespace(MaxCost=MaxCost))
    lines, in_template = [], False
    for line in EXAMPLE.read_text().splitlines():
        # a template: "# [models.<name>]", then "# <field> = <value>" lines
        starts = re.fullmatch(r"# \[models\.[\w-]+\]", line) is not None
        in_template = starts or (in_template and re.match(r"# \w+ = ", line) is not None)
        lines.append(line.removeprefix("# ") if in_template else line)
    ms = models.from_config(tomllib.loads("\n".join(lines)))
    assert set(ms) == {
        "uniform", "jev", "jev-typesafe", "decider-2026-10-16", "decider-any-provider", "decider-4b", "jev-cheap",
        "uniform-uncached",
    }  # fmt: skip
    jev = ms["jev"]
    assert (jev.display_name, jev.model, jev.base_url) == (
        "Jev 1.13 (2026-09-17)",
        "typesafe/jev-1.13",
        "https://openrouter.ai/api",
    )
    assert jev.extra_body == {"provider": {"only": ["typesafe"], "allow_fallbacks": False}}
    assert [type(r).__name__ for r in jev.requirements] == ["SystemOneResponseModelId", "OpenRouterResponseProvider"]
    assert [type(r).__name__ for r in ms["decider-2026-10-16"].requirements] == ["RequestDateRange"]
    assert [type(r).__name__ for r in ms["jev-cheap"].requirements] == ["MaxCost"]
    assert ms["decider-4b"].base_url == "http://localhost:8000"
    assert not ms["decider-any-provider"].cache
    assert not ms["uniform-uncached"].cache
