"""Fixtures shared by the tests next to the modules (src/) and the ones in tests/."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from decision_gateway import SQLiteStore
from decision_gateway.testing import FakeServer


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SQLiteStore]:
    s = SQLiteStore(tmp_path / "store.sqlite")
    yield s
    s.close()


@pytest.fixture
def server() -> FakeServer:
    return FakeServer()
