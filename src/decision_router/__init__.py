"""A drop-in replacement for TypeSafe's SDK client that routes by model name and caches.

    from decision_router import Cache, Router, models

    client = Router(models.load("models.toml"), Cache())
    response = client.system_one(state=..., questions={...}, model="jev")

Querying the cache: decision_router.query. Export and preheat: decision_router.cache.
"""

from . import models
from .cache import Cache, Record
from .models import Model
from .router import AsyncRouter, Router
from .systemone import RoutedResponse

__all__ = ["AsyncRouter", "Cache", "Model", "Record", "RoutedResponse", "Router", "models"]
