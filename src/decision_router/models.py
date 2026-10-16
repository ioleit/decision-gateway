"""models.toml: which models there are, how each is reached and what version answers.

    [models.uniform]
    backend = "uniform"        # a name in backends.BACKENDS
    version = "uniform/1"      # optional for backends that know their own version
    cache = true               # optional; false: always asked, never stored

Every other field is the backend's (url, key_env, provider, ...).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .backends import BACKENDS, Backend


def load(path: str | Path) -> dict[str, Backend]:
    with Path(path).open("rb") as f:
        return from_config(tomllib.load(f))


def from_config(cfg: dict[str, Any]) -> dict[str, Backend]:
    out = {}
    for name, entry in cfg.get("models", {}).items():
        kind = entry.get("backend")
        if kind not in BACKENDS:
            raise ValueError(f"models.toml: {name} has unknown backend {kind!r}; known: {', '.join(BACKENDS)}")
        out[name] = BACKENDS[kind](name, entry)
    return out
