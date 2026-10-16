"""The request key: what makes two requests the same request.

key = sha256 of the canonical JSON of {"endpoint": ..., "body": ..., "assets": [...]}:

    endpoint  where the request was sent ("https://openrouter.ai/api/v1/systemone")
    body      the System One request body as sent: state, model id, questions and any extra
              fields such as a provider pin
    assets    the sha256 of each asset sent with the request, in order; empty for requests
              without assets (requests with assets are not stored yet)

The model's name in models.toml and its requirements are not part of the key: they decide
which stored answers a name accepts, not what a request is. The format is frozen by golden
hashes in key_test.py.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence


def key(endpoint: str, body: dict[str, Any], assets: Sequence[str] = ()) -> str:
    return hashlib.sha256(canonical({"endpoint": endpoint, "body": body, "assets": list(assets)}).encode()).hexdigest()


def canonical(obj: Any) -> str:  # noqa: ANN401 (any JSON value)
    """JSON text with sorted keys and no spaces, so equal objects are equal strings."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
