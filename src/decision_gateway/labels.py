"""Labels: what a request was about, in your terms, recorded with it for queries later.

They come from three places, merged in this order (a later one wins for the same key):

1. the gateway's or transport's own:  Gateway(..., labels={"project": "evals"})
2. labels() around the call, as a context manager or a decorator (sync or async):

       with labels(item=17):
           client.system_one(...)

       @labels(study="demo")
       async def run_study(): ...

3. label_headers() passed with the call itself:

       client.system_one(..., extra_headers=label_headers(item=17))

labels() lives in a context variable, so it follows await, asyncio tasks and
asyncio.to_thread, but not threads started by a ThreadPoolExecutor or run_in_executor, which
don't carry context variables. For calls made in such threads, use label_headers(): it goes
with the request, and the gateway removes it before anything is sent.
"""

from __future__ import annotations

import contextvars
import functools
import inspect
import json
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

HEADER = "x-decision-gateway-labels"

P = ParamSpec("P")
R = TypeVar("R")

_current: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("decision_gateway_labels", default={})  # noqa: B039 (never mutated)


class labels:  # noqa: N801 (used like a function: with labels(...), @labels(...))
    """Labels for the requests made inside a block or a function, merged over any outer ones."""

    def __init__(self, **values: Any) -> None:  # noqa: ANN401 (any JSON value)
        self.values = values
        self._tokens: list[contextvars.Token[dict[str, Any]]] = []

    def __enter__(self) -> None:
        self._tokens.append(_current.set({**_current.get(), **self.values}))

    def __exit__(self, *exc: object) -> None:
        _current.reset(self._tokens.pop())

    def __call__(self, func: Callable[P, R]) -> Callable[P, R]:
        values = self.values
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def run_async(*args: P.args, **kwargs: P.kwargs) -> Any:  # noqa: ANN401 (func's result)
                with labels(**values):
                    return await func(*args, **kwargs)

            return run_async  # type: ignore[return-value]

        @functools.wraps(func)
        def run(*args: P.args, **kwargs: P.kwargs) -> R:
            with labels(**values):
                return func(*args, **kwargs)

        return run


def label_headers(**values: Any) -> dict[str, str]:  # noqa: ANN401 (any JSON value)
    """Labels for one call, as extra_headers for the SDK's system_one."""
    return {HEADER: json.dumps(values, sort_keys=True)}


def current() -> dict[str, Any]:
    """The labels set by labels() where this is called."""
    return dict(_current.get())
