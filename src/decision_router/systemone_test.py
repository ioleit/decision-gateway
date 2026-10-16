import json
from pathlib import Path

import duckdb
import pytest
from typesafe_sdk import Choice, Noul, Question

from decision_router.systemone import InvalidRequestError, InvalidResponseError, parse_response, wire_questions

GOLDEN_JEV = Path(__file__).parents[2] / "examples/smoke/golden/jev/answers.parquet"


def test_sdk_objects_and_dicts_give_the_same_wire() -> None:
    objects: dict[str, Question] = {"a": Noul(instructions="Is it?"), "b": Choice(criteria={"x": None, "y": "why"})}
    dicts: dict[str, Question] = {
        "a": {"type": "noul", "instructions": "Is it?"},
        "b": {"type": "choice", "criteria": {"x": None, "y": "why"}},
    }
    assert wire_questions(objects) == wire_questions(dicts) == dicts


@pytest.mark.parametrize(
    ("questions", "message"),
    [
        ({}, "at least one question"),
        ({"q": {"type": "maybe"}}, "unknown type 'maybe'"),
        ({"q": {"type": "noul", "instructions": "x", "extra": 1}}, "question 'q'"),
        ({"q": {"type": "choice", "criteria": {}}}, "has no criteria"),
        ({"q": {"type": "score", "criteria": []}}, "criteria"),
        ({"q": {"type": "noul"}}, "neither instructions nor criteria"),
    ],
)
def test_invalid_questions(questions: dict[str, object], message: str) -> None:
    with pytest.raises(InvalidRequestError, match=message):
        wire_questions(questions)  # type: ignore[arg-type]


def test_real_jev_responses_are_valid() -> None:
    rows = duckdb.sql(f"SELECT CAST(response AS VARCHAR) FROM read_parquet('{GOLDEN_JEV}')").fetchall()
    assert len(rows) == 5
    for (raw,) in rows:
        response = json.loads(raw)
        parsed = parse_response(response, response["answers"])
        assert parsed.model == "typesafe/jev-1.13-20260917"
        assert "provider" in response  # OpenRouter's extra field: kept in the cache, not in the parsed response


def test_invalid_responses() -> None:
    noul = {"type": "noul", "noul": 0.5}
    with pytest.raises(InvalidResponseError, match="usage"):
        parse_response({"model": "m", "answers": {"q": noul}}, {"q": None})
    with pytest.raises(InvalidResponseError, match="noul"):
        parse_response({"model": "m", "answers": {"q": {"type": "noul"}}, "usage": {}}, {"q": None})
    with pytest.raises(InvalidResponseError, match="do not match the questions asked"):
        parse_response({"model": "m", "answers": {"other": noul}, "usage": {}}, {"q": None})
