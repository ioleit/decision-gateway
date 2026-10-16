from pathlib import Path

import duckdb
import pytest
from typesafe_sdk import Choice, Noul, Question

from decision_router.systemone import (
    InvalidRequestError,
    InvalidResponseError,
    NotCacheableError,
    RoutedResponse,
    check_answers,
    request_body,
    wire_questions,
)

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
        response = RoutedResponse.model_validate_json(raw)
        assert response.model == "typesafe/jev-1.13-20260917"
        assert response.model_extra is not None
        assert response.model_extra["provider"] == "TypeSafe"  # beyond the System One API, kept


def test_answers_must_match_the_questions() -> None:
    response = RoutedResponse.model_validate(
        {"model": "m", "answers": {"other": {"type": "noul", "noul": 0.5}}, "usage": {}}
    )
    with pytest.raises(InvalidResponseError, match="do not match the questions asked"):
        check_answers(response, {"q": None})


def test_request_body_is_what_the_sdk_sends() -> None:
    body = request_body("s", {"q": Noul(instructions="x?")}, "typesafe/jev-1.13", {"provider": {"only": ["typesafe"]}})
    assert body == {
        "state": "s",
        "model": "typesafe/jev-1.13",
        "questions": {"q": {"type": "noul", "instructions": "x?"}},
        "provider": {"only": ["typesafe"]},
    }


def test_a_request_with_assets_is_not_cacheable() -> None:
    with pytest.raises(NotCacheableError, match="assets"):
        request_body(object(), {"q": Noul(instructions="x?")}, "m", None)
