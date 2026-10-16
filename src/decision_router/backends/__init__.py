"""Backends by the name models.toml uses for them (`backend = "..."`)."""

from .base import Backend, JSONObject, Reply
from .http import HTTP, OpenRouter
from .uniform import Uniform

BACKENDS: dict[str, type[Backend]] = {"uniform": Uniform, "http": HTTP, "openrouter": OpenRouter}

__all__ = ["BACKENDS", "HTTP", "Backend", "JSONObject", "OpenRouter", "Reply", "Uniform"]
