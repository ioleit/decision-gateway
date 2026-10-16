"""What run.py and make_golden.py share: the questions as requests, and the router."""

import json
from pathlib import Path

from decision_router import Cache, Router, models

HERE = Path(__file__).parent
QUESTIONS = json.loads((HERE / "questions.json").read_text())
LIVE = [q for q in QUESTIONS if q["id"] <= 5]     # asked by run.py
GOLDEN = [q for q in QUESTIONS if q["id"] > 5]    # answered in golden/, loaded by preheat


def request(q: dict) -> dict:
    """One yes/no question, as a Jev request."""
    return {"state": {"case": q["case"]}, "questions": {"q": {"type": "noul", "instructions": q["question"]}}}


def labels(q: dict, origin: str) -> dict:
    return {"example": "smoke", "id": q["id"], "origin": origin}


def router(cache_path) -> Router:
    return Router(models.load(HERE / "models.toml"), Cache(cache_path))
