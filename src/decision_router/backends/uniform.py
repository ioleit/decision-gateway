"""The baseline: equal probability for every option of every question. No network, no cost.

    noul    noul = 0.5
    choice  every option 1/n; the first option, confidence 1/n
    score   every level 1/n; the expected level, confidence 1/n
    box     the whole image, no confidence

Its answers are valid System One answers, so it stands in for any model in tests and demos.
"""

from __future__ import annotations

from typing import Any

from .base import Backend, JSONObject, Reply


class Uniform(Backend):
    def call(self, wire: JSONObject, request: JSONObject) -> Reply:
        answers = {name: _answer(q) for name, q in wire["questions"].items()}
        usage = {"input_tokens": 0, "output_tokens": 0}
        return Reply({"model": self.name, "answers": answers, "usage": usage}, cost=0.0)


def _answer(question: JSONObject) -> dict[str, Any]:
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
