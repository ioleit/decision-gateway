"""Router: TypeSafe SDK clients by model name, all going through the gateway into one store.

    from decision_gateway import Router, SQLiteStore, models

    router = Router(models.load("models.toml"), SQLiteStore("evals.sqlite"), project="evals", run="2026-10")
    client = router.client("jev")              # a typesafe_sdk.TypeSafeClient
    client.system_one(state=..., questions={...})

A name routes to the configuration in models.toml: where requests go, with which key, model
id and requirements. The clients are the SDK's own, so everything the SDK offers is there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from typesafe_sdk import AsyncTypeSafeClient, TypeSafeClient

    from .models import Model
    from .store import Store


class Router:
    def __init__(
        self, models: Mapping[str, Model], store: Store, project: str | None = None, run: str | None = None
    ) -> None:
        self.models = dict(models)
        self.store = store
        self.project = project
        self.run = run

    def model(self, name: str) -> Model:
        try:
            return self.models[name]
        except KeyError:
            raise KeyError(f"unknown model {name!r}; known: {', '.join(self.models)}") from None

    def client(self, name: str) -> TypeSafeClient:
        """A TypeSafeClient for the model `name`, through the gateway."""
        return self.model(name).client(self.store, self.project, self.run)

    def async_client(self, name: str) -> AsyncTypeSafeClient:
        """An AsyncTypeSafeClient for the model `name`, through the gateway."""
        return self.model(name).async_client(self.store, self.project, self.run)
