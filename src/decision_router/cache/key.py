"""The cache key: what makes two questions the same question.

key = sha256 of the JSON array [model, requirements, request], with sorted object keys:

    model         the model's name in models.toml ("jev")
    requirements  its requirements table, as written (see requirements.py)
    request       the System One request body as sent: state, model id, questions, extra_body

Why the name: it is what the caller routes by, and it stands for one configuration, the model
id, the provider pin and the requirements together. Keyed by name, answers are shared by every
project that uses the same name for the same configuration (through export and preheat), and
renaming an entry starts a new set of answers.

Labels (what the question is about) are not part of the key. The format is frozen by golden
hashes in key_test.py, so a preheated cache hits exactly where the exporting cache did.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def key(model: str, requirements: dict[str, Any], request: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps([model, requirements, request], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def canonical(obj: Any) -> str:  # noqa: ANN401 (any JSON value)
    """JSON text with sorted keys, so equal objects are equal strings (labels, stored bodies)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
