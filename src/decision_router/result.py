"""What the router returns for a request: the model's answers, or its refusal.

    result = router.ask("jev", state=..., questions=...)
    if result.response is not None:
        result.response.nouls["refund"].noul       # typesafe_sdk's SystemOneResponse
    else:
        result.router.refusal.message              # the provider declined to answer

A refusal is not part of the System One API, which only has answers: OpenRouter, for example,
reports one as an HTTP error. It is still a result, so the router returns and caches it like
an answer, and never asks that question again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typesafe_sdk import SystemOneResponse

    from .backends.base import JSONObject


@dataclass(frozen=True)
class Refusal:
    """The provider declined to answer."""

    message: str  # what the provider said: 'OpenAI refused to answer question "q"'
    status: int | None = None  # the HTTP status it came with, if any (502)


@dataclass(frozen=True)
class RouterInfo:
    """What the router knows about a result beyond the System One API."""

    refusal: Refusal | None = None
    response_json: JSONObject | None = None  # the response exactly as received, with fields the SDK leaves out


@dataclass(frozen=True)
class DecisionResult:
    """The model's answers (response), or why there are none (router.refusal)."""

    response: SystemOneResponse | None
    router: RouterInfo
