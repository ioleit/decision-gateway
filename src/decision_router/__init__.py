"""Ask decision models through one router, with a cache that never asks twice.

    from decision_router import Router, Cache, models
    router = Router(models.load("models.toml"), Cache())
    router.ask("uniform", {"state": {...}, "questions": {"q": {"type": "choice", "criteria": {...}}}})
"""

from . import models
from .backends import Backend, Reply
from .cache import Cache, Record
from .router import Router

__all__ = ["Backend", "Cache", "Record", "Reply", "Router", "models"]
