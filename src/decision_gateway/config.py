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

from decision_gateway import constraints
from decision_gateway.transports.gateway_transport import AsyncGatewayTransport, GatewayTransport
from decision_gateway.transports.uniform_transport import BASE_URL as UNIFORM_URL
from decision_gateway.transports.uniform_transport import UniformTransport

if TYPE_CHECKING:
    import httpx2

    from decision_gateway.store import Store

# Defaults per backend: where the SDK sends requests, which variable holds the key, compression.
BACKENDS: dict[str, dict[str, Any]] = {
    "typesafe": {"base_url": None, "key_env": "TYPESAFE_API_KEY", "compression": None},
    "openrouter": {"base_url": "https://openrouter.ai/api", "key_env": "OPENROUTER_API_KEY", "compression": False},
    "uniform": {"base_url": UNIFORM_URL, "key_env": None, "compression": False},
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
            self.transport = UniformTransport()
        self.requirements: list[constraints.Constraint] = constraints.from_config(self.requirements_table)

    def client_options(self, *, cache_only: bool = False) -> dict[str, Any]:
        """Keyword arguments for TypeSafeClient and AsyncTypeSafeClient, without the transport.
        cache_only: nothing is sent, so no key is needed."""
        if self.key_env is None or cache_only:
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

    def client(self, store: Store, labels: dict[str, Any] | None = None, *, cache_only: bool = False) -> TypeSafeClient:
        """A TypeSafeClient for this model whose requests go through the gateway, recorded with
        these labels. cache_only: answered from the store only, nothing is sent."""
        transport: httpx2.BaseTransport | None = self.transport
        gateway = GatewayTransport(self, store, labels, transport=transport, cache_only=cache_only)
        return TypeSafeClient(**self.client_options(cache_only=cache_only), transport=gateway)

    def async_client(
        self, store: Store, labels: dict[str, Any] | None = None, *, cache_only: bool = False
    ) -> AsyncTypeSafeClient:
        """An AsyncTypeSafeClient for this model whose requests go through the gateway."""
        transport: httpx2.AsyncBaseTransport | None = self.transport
        gateway = AsyncGatewayTransport(self, store, labels, transport=transport, cache_only=cache_only)
        return AsyncTypeSafeClient(**self.client_options(cache_only=cache_only), transport=gateway)


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
