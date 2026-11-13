"""Gateway: TypeSafe SDK clients by model name, all going through the gateway into one store.

    from decision_gateway import Gateway, SQLiteStore, config

    gateway = Gateway(config.load("models.toml"), SQLiteStore("evals.sqlite"), labels={"run": "2026-10"})
    client = gateway.client("jev")              # a typesafe_sdk.TypeSafeClient
    client.system_one(state=..., questions={...})

A name routes to the configuration in models.toml: where requests go, with which key, model
id and requirements. The clients are the SDK's own, so everything the SDK offers is there.
Every request made through them is recorded with the gateway's labels (and any set with
labels() around the call).

With cache_only=True nothing is sent: requests are answered from the store, and anything not
stored raises CacheMissError. No API keys are needed then, so a page or a report can read the
store without them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from typesafe_sdk import AsyncTypeSafeClient, TypeSafeClient

    from decision_gateway.config import ModelConfig
    from decision_gateway.store import Store


class Gateway:
    def __init__(
        self,
        models: Mapping[str, ModelConfig],
        store: Store,
        labels: dict[str, Any] | None = None,
        *,
        cache_only: bool = False,
    ) -> None:
        self.models = dict(models)
        self.store = store
        self.labels = dict(labels or {})
        self.cache_only = cache_only

    def model(self, name: str) -> ModelConfig:
        try:
            return self.models[name]
        except KeyError:
            raise KeyError(f"unknown model {name!r}; known: {', '.join(self.models)}") from None

    def client(self, name: str) -> TypeSafeClient:
        """A TypeSafeClient for the model `name`, through the gateway."""
        return self.model(name).client(self.store, self.labels, cache_only=self.cache_only)

    def async_client(self, name: str) -> AsyncTypeSafeClient:
        """An AsyncTypeSafeClient for the model `name`, through the gateway."""
        return self.model(name).async_client(self.store, self.labels, cache_only=self.cache_only)
