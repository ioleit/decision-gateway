"""models.toml: the models the router can ask, by name. Each name routes to a configured
TypeSafe SDK client. models.example.toml at the top of the repository describes every field.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy, TypeSafeClient

from . import requirements, uniform

if TYPE_CHECKING:
    import httpx2

# Defaults per backend: where the SDK sends requests, which variable holds the key, compression.
BACKENDS: dict[str, dict[str, Any]] = {
    "typesafe": {"base_url": None, "key_env": "TYPESAFE_API_KEY", "compression": None},
    "openrouter": {"base_url": "https://openrouter.ai/api", "key_env": "OPENROUTER_API_KEY", "compression": False},
    "uniform": {"base_url": None, "key_env": None, "compression": False},
}

FIELDS = {
    "backend", "model", "display_name", "base_url", "key_env", "extra_body", "compression", "timeout", "max_retries",
    "cache", "requirements",
}  # fmt: skip


class MissingKeyError(Exception):
    """The API key of a model is not in the environment."""


@dataclass
class Model:
    """One entry of models.toml: how a name is routed to a TypeSafe SDK client."""

    name: str
    backend: str = "typesafe"
    model: str = ""  # the id sent as the request's `model`; default: the name
    display_name: str = ""  # default: the name
    base_url: str | None = None
    key_env: str | None = None
    extra_body: dict[str, Any] = field(default_factory=dict)  # merged into every request, e.g. a provider pin
    compression: bool | None = None  # False: off; None: the backend's default
    timeout: float | None = None
    max_retries: int | None = None
    cache: bool = True
    requirements_table: dict[str, Any] = field(default_factory=dict)
    transport: httpx2.BaseTransport | None = None  # an httpx2 transport, for tests; uniform brings its own

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
        self.requirements_spec = requirements.spec(self.requirements_table)  # as written, for the cache key

    def client_options(self) -> dict[str, Any]:
        """Keyword arguments for TypeSafeClient and AsyncTypeSafeClient. Reads the API key, so it
        is called only when a question is not in the cache."""
        if self.key_env is None:
            api_key = "none"
        elif not (api_key := os.environ.get(self.key_env, "")):
            raise MissingKeyError(f"{self.name} needs {self.key_env} in the environment to ask new questions")
        options: dict[str, Any] = {"api_key": api_key, "model": self.model, "base_url": self.base_url}
        if self.compression is False:
            options["compression"] = False
        if self.timeout is not None:
            options["timeout"] = self.timeout
        if self.max_retries is not None:
            options["retry"] = RetryPolicy(max_retries=self.max_retries)
        if self.transport is not None:
            options["transport"] = self.transport
        return options

    def client(self) -> TypeSafeClient:
        return TypeSafeClient(**self.client_options())

    def async_client(self) -> AsyncTypeSafeClient:
        return AsyncTypeSafeClient(**self.client_options())


def load(path: str | Path) -> dict[str, Model]:
    with Path(path).open("rb") as f:
        return from_config(tomllib.load(f))


def from_config(cfg: dict[str, Any]) -> dict[str, Model]:
    out = {}
    for name, entry in cfg.get("models", {}).items():
        unknown = set(entry) - FIELDS
        if unknown:
            raise ValueError(f"models.toml: {name} has unknown fields {sorted(unknown)}; known: {sorted(FIELDS)}")
        fields = {k: v for k, v in entry.items() if k != "requirements"}
        out[name] = Model(name=name, requirements_table=entry.get("requirements", {}), **fields)
    return out
