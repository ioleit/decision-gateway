"""What run.py and make_golden.py share: the questions as requests, and the router."""

import json
from pathlib import Path
from typing import Any

from decision_gateway import Cache, Router, models

HERE = Path(__file__).parent
QUESTIONS: list[dict[str, Any]] = json.loads((HERE / "questions.json").read_text())
SPLIT = 5  # questions 1-5 are asked live, 6-10 come from golden/
LIVE = [q for q in QUESTIONS if q["id"] <= SPLIT]  # asked by run.py
GOLDEN = [q for q in QUESTIONS if q["id"] > SPLIT]  # answered in golden/, loaded by preheat


def request(q: dict[str, Any]) -> dict[str, Any]:
    """One yes/no question, as a Jev request."""
    return {"state": {"case": q["case"]}, "questions": {"q": {"type": "noul", "instructions": q["question"]}}}


def labels(q: dict[str, Any], origin: str) -> dict[str, Any]:
    return {"example": "smoke", "id": q["id"], "origin": origin}


def router(cache: Cache) -> Router:
    return Router(models.load(HERE / "models.toml"), cache)
