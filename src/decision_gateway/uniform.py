"""The uniform baseline: a local System One server that gives every option equal probability.

It is an HTTP transport for the SDK, so a uniform model goes through exactly the same client,
cache and checks as a real one, without a network or a key:

    noul    noul = 0.5
    choice  every option 1/n; the first option, confidence 1/n
    score   every level 1/n; the expected level, confidence 1/n
    box     the whole image, no confidence

Its answers are valid System One answers, so it stands in for any model in tests and demos.
"""

from __future__ import annotations

import json
from typing import Any

import httpx2


def answer(question: dict[str, Any]) -> dict[str, Any]:
    kind = question["type"]
    if kind == "noul":
        return {"type": "noul", "noul": 0.5}
    if kind == "choice":
        options = list(question["criteria"])
        p = 1 / len(options)
        return {"type": "choice", "choice": options[0], "confidence": p, "probabilities": dict.fromkeys(options, p)}
    if kind == "score":
        levels = list(question["criteria"])
        p = 1 / len(levels)
        return {
            "type": "score",
            "score": sum(i * p for i in range(len(levels))),
            "confidence": p,
            "legend": dict(enumerate(levels)),
            "probabilities": dict.fromkeys(range(len(levels)), p),
        }
    if kind == "box":
        return {"type": "box", "box": {"top": 0.0, "bottom": 1.0, "left": 0.0, "right": 1.0}, "confidence": None}
    raise ValueError(f"uniform: unknown question type {kind!r}")


def respond(body: dict[str, Any], model: str = "uniform") -> dict[str, Any]:
    """The uniform response to a System One request body."""
    answers = {name: answer(q) for name, q in body["questions"].items()}
    return {"model": model, "answers": answers, "usage": {"input_tokens": 0, "output_tokens": 0}}


def transport() -> httpx2.MockTransport:
    """An httpx2 transport that answers every System One request uniformly."""
    return httpx2.MockTransport(lambda request: httpx2.Response(200, json=respond(json.loads(request.content))))
