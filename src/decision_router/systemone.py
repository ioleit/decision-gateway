"""The System One API as the router uses it, with the types of TypeSafe's SDK (typesafe-sdk).

Spec: https://docs.typesafe.ai/api (OpenAPI: https://api.typesafe.ai/openapi.json). Questions
are the SDK's question objects (Noul, Choice, Score, Box) or the matching dictionaries;
responses are the SDK's SystemOneResponse.

The cache keeps requests and responses as JSON exactly as they went over the network, so
fields a server adds beyond the spec (OpenRouter's `provider`, `id`, `usage.cost`) are kept,
although SystemOneResponse leaves them out.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError
from typesafe_sdk import Box, Choice, Noul, Score, SystemOneResponse

if TYPE_CHECKING:
    from collections.abc import Mapping

    from typesafe_sdk import Question

    JSONObject = dict[str, Any]

QUESTION_TYPES: dict[str, type[BaseModel]] = {"noul": Noul, "choice": Choice, "score": Score, "box": Box}


class InvalidRequestError(ValueError):
    """A question that the System One API does not accept."""


class InvalidResponseError(ValueError):
    """A response that is not a System One response to the questions asked; not cached."""


def wire_questions(questions: Mapping[str, Question]) -> JSONObject:
    """Questions as JSON for the request body, each validated by its SDK class."""
    if not questions:
        raise InvalidRequestError("at least one question is required")
    out: JSONObject = {}
    for name, question in questions.items():
        if isinstance(question, BaseModel):
            out[name] = question.model_dump(mode="json")
            continue
        cls = QUESTION_TYPES.get(str(question.get("type")))
        if cls is None:
            raise InvalidRequestError(f"question {name!r}: unknown type {question.get('type')!r}")
        try:
            out[name] = cls.model_validate(question).model_dump(mode="json")
        except ValidationError as e:
            raise InvalidRequestError(f"question {name!r}: {e}") from None
    for name, question in out.items():
        _check_question(name, question)
    return out


def _check_question(name: str, q: JSONObject) -> None:
    """What the SDK checks beyond its types before sending (typesafe_sdk/_core/questions.py)."""
    if q["type"] in ("choice", "score") and not q.get("criteria"):
        raise InvalidRequestError(f"{q['type']} question {name!r} has no criteria")
    if q["type"] == "noul" and q.get("instructions") is None:
        criteria = q.get("criteria") or {}
        if not any(v is not None for v in criteria.values()):
            raise InvalidRequestError(f"noul question {name!r} has neither instructions nor criteria")


def parse_response(raw: JSONObject, questions: Mapping[str, object]) -> SystemOneResponse:
    """raw as the SDK's SystemOneResponse, if it is a valid response with one answer per question."""
    try:
        response = SystemOneResponse.model_validate_json(json.dumps(raw))
    except ValidationError as e:
        raise InvalidResponseError(f"not a System One response: {e}") from None
    if set(response.answers) != set(questions):
        raise InvalidResponseError(
            f"answers {sorted(response.answers)} do not match the questions asked {sorted(questions)}"
        )
    return response
