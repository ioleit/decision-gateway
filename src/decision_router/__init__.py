"""Ask decision models through one router, with a cache that never asks twice.

    from decision_router import Cache, Router, models
    router = Router(models.load("models.toml"), Cache())
    router.ask("uniform", {"state": {...}, "questions": {"q": {"type": "choice", "criteria": {...}}}})

Querying the cache: decision_router.query. Export and preheat: decision_router.cache.
"""

from . import models
from .backends import Backend, Reply
from .cache import Cache, Record
from .router import Router

__all__ = ["Backend", "Cache", "Record", "Reply", "Router", "models"]
