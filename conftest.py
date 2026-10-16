"""Fixtures shared by the tests next to the modules (src/) and the ones in tests/."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from decision_router import Cache, Router
from decision_router.backends import Uniform
from decision_router.testing import Fake


@pytest.fixture
def cache(tmp_path: Path) -> Iterator[Cache]:
    c = Cache(tmp_path / "cache.sqlite")
    yield c
    c.close()


@pytest.fixture
def fake() -> Fake:
    return Fake("fake", {"version": "fake/1"})


@pytest.fixture
def router(cache: Cache, fake: Fake) -> Router:
    return Router({"fake": fake, "uniform": Uniform("uniform")}, cache)
