"""The System One API as the router uses it: TypeSafe's SDK (typesafe-sdk) and its types.

Spec: https://docs.typesafe.ai/api (OpenAPI: https://api.typesafe.ai/openapi.json).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, ValidationError
from typesafe_sdk import Box, Choice, Noul, Score, SystemOneResponse

if TYPE_CHECKING:
    from collections.abc import Mapping

    from typesafe_sdk import Question

JSONObject = dict[str, Any]

QUESTION_TYPES: dict[str, type[BaseModel]] = {"noul": Noul, "choice": Choice, "score": Score, "box": Box}


class RoutedResponse(SystemOneResponse):
    """SystemOneResponse that keeps fields a server adds beyond the spec, such as OpenRouter's
    `provider` and `id` (in model_extra)."""

    model_config = ConfigDict(extra="allow")


class InvalidRequestError(ValueError):
    """A question that the System One API does not accept."""


class InvalidResponseError(ValueError):
    """A response that does not answer the questions asked; not cached."""


class NotCacheableError(ValueError):
    """A request the cache cannot key yet: assets (images) in it."""


def wire_questions(questions: Mapping[str, Question]) -> JSONObject:
    """Questions as JSON, as the SDK sends them, each validated by its SDK class."""
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


def request_body(
    state: object,
    questions: Mapping[str, Question],
    model: str,
    extra_body: Mapping[str, object] | None,
) -> JSONObject:
    """The JSON body the SDK sends for a request without assets: state, model, questions, then
    extra_body merged over them. NotCacheableError if the state holds assets."""
    body: JSONObject = {"state": state, "model": model, "questions": wire_questions(questions), **(extra_body or {})}
    try:
        json.dumps(body)
    except TypeError:
        raise NotCacheableError("the request holds assets (images), which the cache does not key yet") from None
    return body


def check_answers(response: SystemOneResponse, questions: Mapping[str, object]) -> None:
    if set(response.answers) != set(questions):
        raise InvalidResponseError(
            f"answers {sorted(response.answers)} do not match the questions asked {sorted(questions)}"
        )


def _check_question(name: str, q: JSONObject) -> None:
    """What the SDK checks beyond its types before sending (typesafe_sdk/_core/questions.py)."""
    if q["type"] in ("choice", "score") and not q.get("criteria"):
        raise InvalidRequestError(f"{q['type']} question {name!r} has no criteria")
    if q["type"] == "noul" and q.get("instructions") is None:
        criteria = q.get("criteria") or {}
        if not any(v is not None for v in criteria.values()):
            raise InvalidRequestError(f"noul question {name!r} has neither instructions nor criteria")
