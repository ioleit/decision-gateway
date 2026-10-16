"""The baseline: equal probability for every option of every question. No network, no cost."""

from __future__ import annotations

from .base import Backend, Reply

VERSION = "uniform/1"  # change when the answers it gives change


class Uniform(Backend):
    def version(self) -> str:
        return self.entry.get("version", VERSION)

    def call(self, wire: dict, request: dict) -> Reply:
        answers = {}
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
            answer = {"type": kind, "probabilities": {o: p for o in options}}
            answer["score" if kind == "score" else "choice"] = options[0]
            answers[name] = answer
        return Reply({"model": self.name, "answers": answers}, cost=0.0)
