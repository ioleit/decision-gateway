"""Fixtures shared by the tests next to the modules (src/) and the ones in tests/."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from decision_gateway import Cache, Model, Router
from decision_gateway.testing import FakeServer


@pytest.fixture
def cache(tmp_path: Path) -> Iterator[Cache]:
    c = Cache(tmp_path / "cache.sqlite")
    yield c
    c.close()


@pytest.fixture
def server() -> FakeServer:
    return FakeServer()


@pytest.fixture
def router(cache: Cache, server: FakeServer) -> Iterator[Router]:
    with Router({"fake": server.model("fake"), "uniform": Model(name="uniform", backend="uniform")}, cache) as r:
        yield r
