import re
import tomllib
from pathlib import Path

import pytest

from decision_router import models
from decision_router.backends import Uniform


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


def test_every_template_in_the_example_loads() -> None:
    """The commented-out templates in models.example.toml, uncommented, are valid models."""
    lines, in_template = [], False
    for line in (Path(__file__).parents[2] / "models.example.toml").read_text().splitlines():
        # a template: "# [models.<name>]", then "# <field> = <value>" lines
        in_template = line.startswith("# [models.") or (in_template and re.match(r"# \w+ = ", line) is not None)
        lines.append(line.removeprefix("# ") if in_template else line)
    ms = models.from_config(tomllib.loads("\n".join(lines)))
    assert set(ms) == {
        "uniform", "jev", "undated", "undated-any-provider", "local", "team-server", "wrapped", "uniform-uncached",
    }  # fmt: skip
    assert not ms["undated-any-provider"].cache
    assert not ms["uniform-uncached"].cache
