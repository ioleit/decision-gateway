from pathlib import Path

import pytest

from decision_router import models
from decision_router.backends import Uniform


def test_example_config_loads():
    ms = models.load(Path(__file__).parent.parent / "models.example.toml")
    assert isinstance(ms["uniform"], Uniform) and ms["uniform"].cache


def test_unknown_backend():
    with pytest.raises(ValueError, match="unknown backend"):
        models.from_config({"models": {"x": {"backend": "carrier-pigeon"}}})


def test_cache_off_per_model():
    ms = models.from_config({"models": {"u": {"backend": "uniform", "cache": False}}})
    assert ms["u"].cache is False
