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
