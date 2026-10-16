"""TypeSafe's System One API, as the gateway uses it.

Spec: https://docs.typesafe.ai/api (OpenAPI: https://api.typesafe.ai/openapi.json). Clients,
requests and response types are TypeSafe's SDK (typesafe-sdk).
"""

from __future__ import annotations

from pydantic import ConfigDict
from typesafe_sdk import SystemOneResponse


class RoutedResponse(SystemOneResponse):
    """SystemOneResponse that keeps fields a server adds beyond the spec, such as OpenRouter's
    `provider` and `id`, in model_extra. Pass it as response_model to see them:

        client.system_one(..., response_model=RoutedResponse).model_extra["provider"]
    """

    model_config = ConfigDict(extra="allow")
