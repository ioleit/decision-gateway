import pytest

from decision_router import Cache, Router
from decision_router.backends import Uniform

from fake_backend import Fake


def choice(*options, state=None):
    """A one-question pick request."""
    return {"state": state or {"case": 1}, "questions": {"pick": {"type": "choice", "criteria": {o: o for o in options}}}}


@pytest.fixture
def cache(tmp_path):
    c = Cache(tmp_path / "cache.sqlite")
    yield c
    c.close()


@pytest.fixture
def fake():
    return Fake("fake", {"version": "fake/1"})


@pytest.fixture
def router(cache, fake):
    return Router({"fake": fake, "uniform": Uniform("uniform")}, cache)
