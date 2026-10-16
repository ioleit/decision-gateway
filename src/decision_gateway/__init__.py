"""A gateway for TypeSafe's System One API: requests from the SDK client go through it, are
routed by model name, answered from what is already known, and recorded.

    from decision_gateway import Router, SQLiteStore, config

    router = Router(config.load("models.toml"), SQLiteStore("evals.sqlite"), labels={"project": "evals"})
    client = router.client("jev")                 # a typesafe_sdk.TypeSafeClient
    with labels(item=17):
        client.system_one(state=..., questions={...})
"""

from . import config
from .config import ModelConfig
from .labels import label_headers, labels
from .requirements import Requirement, RequirementNotMetError
from .router import Router
from .store import Observation, RequestEvent, SQLiteStore, Store
from .systemone import RoutedResponse
from .transport import AsyncGatewayTransport, GatewayTransport

__all__ = [
    "AsyncGatewayTransport",
    "GatewayTransport",
    "ModelConfig",
    "Observation",
    "RequestEvent",
    "Requirement",
    "RequirementNotMetError",
    "RoutedResponse",
    "Router",
    "SQLiteStore",
    "Store",
    "config",
    "label_headers",
    "labels",
]
