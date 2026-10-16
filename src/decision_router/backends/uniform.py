"""The baseline: equal probability for every option of every question. No network, no cost."""

from __future__ import annotations

from typing import Any

from .base import Backend, JSONObject, Reply


class Uniform(Backend):
    def call(self, wire: JSONObject, request: JSONObject) -> Reply:
        answers: JSONObject = {}
        for name, q in wire["questions"].items():
            kind = q.get("type", "choice")
            criteria = q.get("criteria") or {}
            options = list(criteria) if isinstance(criteria, dict) else [str(c) for c in criteria]
            if kind == "noul":
                answers[name] = {"type": kind, "noul": 0.5, "probabilities": {"true": 0.5, "false": 0.5}}
                continue
            if not options:
                options = ["true", "false"]
            p = 1 / len(options)
            answer: dict[str, Any] = {"type": kind, "probabilities": dict.fromkeys(options, p)}
            answer["score" if kind == "score" else "choice"] = options[0]
            answers[name] = answer
        return Reply({"model": self.name, "answers": answers}, cost=0.0)
