"""models.toml: which models there are and how each is reached.

models.example.toml at the top of the repository describes every field, with examples.
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
