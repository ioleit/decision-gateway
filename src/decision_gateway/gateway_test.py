import asyncio

import pytest
from typesafe_sdk import AsyncTypeSafeClient, TypeSafeClient

from decision_gateway import Gateway, ModelConfig, SQLiteStore, labels
from decision_gateway.config import MissingKeyError
from decision_gateway.testing import FakeTransport, choice


def test_the_client_is_the_sdks_own(store: SQLiteStore, fake: FakeTransport) -> None:
    client = Gateway({"m": fake.model("m")}, store).client("m")
    assert type(client) is TypeSafeClient


def test_the_async_client_is_the_sdks_own(store: SQLiteStore, fake: FakeTransport) -> None:
    client = Gateway({"m": fake.model("m")}, store).async_client("m")
    assert type(client) is AsyncTypeSafeClient
    asyncio.run(client.aclose())


def test_the_gateways_labels_go_with_every_client(store: SQLiteStore, fake: FakeTransport) -> None:
    gateway = Gateway({"m": fake.model("m"), "n": fake.model("n")}, store, labels={"project": "evals"})
    gateway.client("m").system_one(**choice("A", "B"))
    with labels(item=1):
        gateway.client("n").system_one(**choice("A", "B"))
    rows = store.con.execute("SELECT model, labels FROM requests ORDER BY at").fetchall()
    assert rows == [("m", '{"project":"evals"}'), ("n", '{"item":1,"project":"evals"}')]


def test_unknown_model_and_missing_key(store: SQLiteStore) -> None:
    gateway = Gateway({"jev": ModelConfig(name="jev", backend="openrouter", key_env="NO_SUCH_KEY")}, store)
    with pytest.raises(KeyError, match="unknown model"):
        gateway.client("nope")
    with pytest.raises(MissingKeyError, match="NO_SUCH_KEY"):
        gateway.client("jev")
