"""A gateway for TypeSafe's System One API: requests from the SDK client go through it, are
routed by model name, answered from what is already known, and recorded.

    from decision_gateway import Gateway, SQLiteStore, config

    gateway = Gateway(config.load("models.toml"), SQLiteStore("evals.sqlite"), labels={"project": "evals"})
    client = gateway.client("jev")                 # a typesafe_sdk.TypeSafeClient
    with labels(item=17):
        client.system_one(state=..., questions={...})
"""

from decision_gateway import config
from decision_gateway.config import ModelConfig
from decision_gateway.constraints import Constraint, ConstraintViolatedError
from decision_gateway.gateway import Gateway
from decision_gateway.labels import label_headers, labels
from decision_gateway.store import Observation, RequestEvent, SQLiteStore, Store
from decision_gateway.systemone import RoutedResponse
from decision_gateway.transports.gateway_transport import AsyncGatewayTransport, CacheMissError, GatewayTransport

__all__ = [
    "AsyncGatewayTransport",
    "CacheMissError",
    "Constraint",
    "ConstraintViolatedError",
    "Gateway",
    "GatewayTransport",
    "ModelConfig",
    "Observation",
    "RequestEvent",
    "RoutedResponse",
    "SQLiteStore",
    "Store",
    "config",
    "label_headers",
    "labels",
]
