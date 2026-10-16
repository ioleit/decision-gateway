"""A gateway for TypeSafe's System One API: requests from the SDK client go through it, are
routed by model name, answered from what is already known, and recorded.

    from decision_gateway import Router, SQLiteStore, models

    router = Router(models.load("models.toml"), SQLiteStore("evals.sqlite"), project="evals")
    client = router.client("jev")                 # a typesafe_sdk.TypeSafeClient
    with labels(item=17):
        client.system_one(state=..., questions={...})
"""

from . import models
from .models import Model
from .requirements import Requirement, RequirementNotMetError
from .router import Router
from .store import Observation, RequestEvent, SQLiteStore, Store
from .systemone import RoutedResponse
from .transport import AsyncGatewayTransport, GatewayTransport, labels

__all__ = [
    "AsyncGatewayTransport",
    "GatewayTransport",
    "Model",
    "Observation",
    "RequestEvent",
    "Requirement",
    "RequirementNotMetError",
    "RoutedResponse",
    "Router",
    "SQLiteStore",
    "Store",
    "labels",
    "models",
]
