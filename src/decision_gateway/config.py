"""models.toml: the models, by name, and how the TypeSafe SDK client for each is configured.
models.example.toml at the top of the repository describes every field.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy, TypeSafeClient

from . import requirements, uniform
from .transport import AsyncGatewayTransport, GatewayTransport

if TYPE_CHECKING:
    import httpx2

    from .store import Store

# Defaults per backend: where the SDK sends requests, which variable holds the key, compression.
BACKENDS: dict[str, dict[str, Any]] = {
    "typesafe": {"base_url": None, "key_env": "TYPESAFE_API_KEY", "compression": None},
    "openrouter": {"base_url": "https://openrouter.ai/api", "key_env": "OPENROUTER_API_KEY", "compression": False},
    "uniform": {"base_url": uniform.BASE_URL, "key_env": None, "compression": False},
}

FIELDS = {
    "backend", "model", "display_name", "base_url", "key_env", "extra_body", "extra_headers", "compression",
    "timeout", "max_retries", "cache", "requirements",
}  # fmt: skip


class MissingKeyError(Exception):
    """The API key of a model is not in the environment."""


@dataclass
class ModelConfig:
    """One entry of models.toml."""

    name: str
    backend: str = "typesafe"
    model: str = ""  # the model id the client sends by default; default: the name
    display_name: str = ""  # default: the name
    base_url: str | None = None
    key_env: str | None = None
    extra_body: dict[str, Any] = field(default_factory=dict)  # added to every request body, e.g. a provider pin
    extra_headers: dict[str, str] = field(default_factory=dict)
    compression: bool | None = None  # False: off; None: the backend's default
    timeout: float | None = None
    max_retries: int | None = None
    cache: bool = True  # False: always ask (answers are still recorded)
    requirements_table: dict[str, Any] = field(default_factory=dict)
    transport: Any = None  # an httpx2 transport to send through instead of the network (tests, uniform)

    def __post_init__(self) -> None:
        if self.backend not in BACKENDS:
            known = ", ".join(BACKENDS)
            raise ValueError(f"models.toml: {self.name} has unknown backend {self.backend!r}; known: {known}")
        defaults = BACKENDS[self.backend]
        self.model = self.model or self.name
        self.display_name = self.display_name or self.name
        self.base_url = self.base_url or defaults["base_url"]
        self.key_env = self.key_env or defaults["key_env"]
        if self.compression is None:
            self.compression = defaults["compression"]
        if self.backend == "uniform" and self.transport is None:
            self.transport = uniform.transport()
        self.requirements: list[requirements.Requirement] = requirements.from_config(self.requirements_table)

    def client_options(self) -> dict[str, Any]:
        """Keyword arguments for TypeSafeClient and AsyncTypeSafeClient, without the transport."""
        if self.key_env is None:
            api_key = "none"
        elif not (api_key := os.environ.get(self.key_env, "")):
            raise MissingKeyError(f"{self.name} needs {self.key_env} in the environment")
        options: dict[str, Any] = {"api_key": api_key, "model": self.model, "base_url": self.base_url}
        if self.extra_headers:
            options["headers"] = self.extra_headers
        if self.compression is False:
            options["compression"] = False
        if self.timeout is not None:
            options["timeout"] = self.timeout
        if self.max_retries is not None:
            options["retry"] = RetryPolicy(max_retries=self.max_retries)
        return options

    def client(self, store: Store, labels: dict[str, Any] | None = None) -> TypeSafeClient:
        """A TypeSafeClient for this model whose requests go through the gateway, recorded with
        these labels."""
        transport: httpx2.BaseTransport | None = self.transport
        gateway = GatewayTransport(self, store, labels, transport=transport)
        return TypeSafeClient(**self.client_options(), transport=gateway)

    def async_client(self, store: Store, labels: dict[str, Any] | None = None) -> AsyncTypeSafeClient:
        """An AsyncTypeSafeClient for this model whose requests go through the gateway."""
        transport: httpx2.AsyncBaseTransport | None = self.transport
        gateway = AsyncGatewayTransport(self, store, labels, transport=transport)
        return AsyncTypeSafeClient(**self.client_options(), transport=gateway)


def load(path: str | Path) -> dict[str, ModelConfig]:
    with Path(path).open("rb") as f:
        return from_config(tomllib.load(f))


def from_config(cfg: dict[str, Any]) -> dict[str, ModelConfig]:
    out = {}
    for name, entry in cfg.get("models", {}).items():
        unknown = set(entry) - FIELDS
        if unknown:
            raise ValueError(f"models.toml: {name} has unknown fields {sorted(unknown)}; known: {sorted(FIELDS)}")
        fields = {k: v for k, v in entry.items() if k != "requirements"}
        out[name] = ModelConfig(name=name, requirements_table=entry.get("requirements", {}), **fields)
    return out
