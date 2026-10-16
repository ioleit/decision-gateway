"""The cache key: what makes two questions the same question.

key = sha256 of the JSON array [model, version, wire], with sorted object keys:

    model    the name the answer is kept under ("jev")
    version  what answered: pinned weights ("org/repo@<commit>"), a dated API model id, ...
    wire     the request exactly as it goes over the network

Labels (what the question is about) are not part of the key. The key must be the same on
every machine, so a preheated cache hits exactly where the exporting cache did; the format is
frozen by golden hashes in tests/test_key.py.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def key(model: str, version: str, wire: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps([model, version, wire], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def canonical(obj: Any) -> str:  # noqa: ANN401 (any JSON value)
    """JSON text with sorted keys, so equal objects are equal strings (labels, stored bodies)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
