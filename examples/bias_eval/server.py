"""The picks page and its API: who gets the coin, from the answers in the decision store.

    python server.py [--port 8900] [--store PATH]      # then open http://127.0.0.1:8900

The page (picks.html) shows a scenario, four players and the model's picks among three of
them at a time; the one picked gets a coin. Answers come from a cache-only gateway: nothing is
asked, so the server needs no API keys and costs nothing. A pick that is not in the store
flashes red; scrape.py fills the store.

    GET  /api/models                                       the models of models.toml
    GET  /api/datasets/discrim-eval-explicit               dimensions of a case, tasks (= templates)
    GET  /api/datasets/discrim-eval-explicit/scenarios     their questions
    GET  /api/datasets/.../scenarios/{s}/cases/{key}       a case, the words that vary in **bold**
    GET  /api/datasets/.../tasks/{task}?scenario=          a template's instructions, filled in
    POST /api/decide/ask                                   the probabilities for groups of cases
    POST /api/decide/raw                                   the request as sent and its response

Schema at /api/docs.
"""

from __future__ import annotations

import argparse
import json
import threading
from typing import TYPE_CHECKING, Any, Literal

import discrim
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from decision_gateway import CacheMissError, ConstraintViolatedError, Gateway, labels

if TYPE_CHECKING:
    from typesafe_sdk import TypeSafeClient

    from decision_gateway import SQLiteStore

PAGE = discrim.HERE / "picks.html"
SOURCE = "picks_page"  # the `source` label of the page's lookups

app = FastAPI(title="Who gets the coin", docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
state: dict[str, Gateway] = {}
_clients: dict[str, TypeSafeClient] = {}
_lock = threading.Lock()


def gateway() -> Gateway:
    if "gateway" not in state:
        state["gateway"] = discrim.gateway(cache_only=True)
    return state["gateway"]


def client(model: str) -> TypeSafeClient:
    if model not in gateway().models:
        raise HTTPException(422, f"model must be one of {list(gateway().models)}")
    with _lock:
        if model not in _clients:
            _clients[model] = gateway().client(model)
        return _clients[model]


# ---- shapes ----


class Dimension(BaseModel):
    name: str
    values: list[str]


class TaskInfo(BaseModel):
    id: str = Field(description="a template in templates/")
    mode: Literal["one-of"] = "one-of"


class Dataset(BaseModel):
    id: str
    title: str
    kind: str
    dimensions: list[Dimension]
    tasks: list[TaskInfo]


class Scenario(BaseModel):
    id: str
    short_summary: str


class Case(BaseModel):
    key: str = Field(examples=["30|male|white"])
    text: str = Field(description="markdown; the words that change with the person are **bold**")


class Instructions(BaseModel):
    task: str
    size: int
    instructions: str


class Model(BaseModel):
    id: str
    label: str
    available: bool = True
    unavailable_reason: str | None = None


class AskRequest(BaseModel):
    model: str = Field(examples=["clef-flash"])
    dataset: str = Field(examples=[discrim.DATASET])
    scenario: str = Field(examples=["87"])
    groups: list[list[str]] = Field(min_length=1, max_length=24, description="case keys; each group is one question")
    tasks: list[str] = Field(min_length=1, examples=[["pick-one-v2"]])


class GroupResult(BaseModel):
    status: Literal["answered", "missing", "failed"] = Field(
        description="answered: numbers for every task; missing: not in the store; failed: see error"
    )
    tasks: dict[str, list[float] | None] = Field(description="task -> the probability of each candidate, in order")
    error: str | None = None


class AskResponse(BaseModel):
    results: list[GroupResult]
    in_flight: int = Field(0, description="always 0: the page reads stored answers only")


class RawRequest(BaseModel):
    model: str
    dataset: str
    scenario: str
    group: list[str]
    tasks: list[str] = Field(min_length=1)


class Raw(BaseModel):
    request: dict[str, Any] = Field(description="the request as sent; if never asked, as it would be built")
    response: dict[str, Any] | None = Field(description="its stored answer; None if never asked")


class RawResponse(BaseModel):
    tasks: dict[str, list[Raw]]


# ---- checks ----


def _dataset(dataset: str) -> None:
    if dataset != discrim.DATASET:
        raise HTTPException(404, f"no dataset {dataset!r}; there is {discrim.DATASET}")


def _scenario(scenario: str) -> int:
    if not scenario.isdigit() or int(scenario) not in discrim.scenarios():
        raise HTTPException(404, f"no scenario {scenario!r} in {discrim.DATASET}")
    return int(scenario)


def _template(task: str) -> discrim.Template:
    try:
        return discrim.template(task)
    except LookupError as e:
        raise HTTPException(404, str(e).strip("'\"")) from None


def _group(template: discrim.Template, keys: list[str]) -> tuple[discrim.Person, ...]:
    try:
        group = tuple(discrim.Person.from_key(k) for k in keys)
    except LookupError as e:
        raise HTTPException(404, str(e).strip("'\"")) from None
    if len(group) != len(template.letters):
        raise HTTPException(422, f"{template.name} takes groups of {len(template.letters)} cases, not {len(group)}")
    return group


# ---- routes ----


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse("/picks.html")


@app.get("/picks.html", response_class=HTMLResponse, include_in_schema=False)
def page() -> HTMLResponse:
    return HTMLResponse(PAGE.read_text(), headers={"Cache-Control": "no-store"})


@app.get("/api/models", response_model=list[Model])
def models() -> list[Model]:
    return [Model(id=name, label=m.display_name) for name, m in gateway().models.items()]


@app.get("/api/datasets/{dataset}", response_model=Dataset)
def dataset_info(dataset: str) -> Dataset:
    _dataset(dataset)
    return Dataset(
        id=discrim.DATASET,
        title="Anthropic discrim-eval (explicit)",
        kind="people",
        dimensions=[Dimension(name=n, values=v) for n, v in discrim.DIMENSIONS.items()],
        tasks=[TaskInfo(id=name) for name in discrim.templates()],
    )


@app.get("/api/datasets/{dataset}/scenarios", response_model=list[Scenario])
def scenarios(dataset: str) -> list[Scenario]:
    _dataset(dataset)
    return [Scenario(id=str(s), short_summary=q) for s, q in discrim.scenarios().items()]


@app.get("/api/datasets/{dataset}/scenarios/{scenario}/cases/{key}", response_model=Case)
def case(dataset: str, scenario: str, key: str) -> Case:
    _dataset(dataset)
    s = _scenario(scenario)
    try:
        person = discrim.Person.from_key(key)
    except LookupError as e:
        raise HTTPException(404, str(e).strip("'\"")) from None
    return Case(key=key, text=discrim.marked(s, person))


@app.get("/api/datasets/{dataset}/tasks/{task}", response_model=Instructions)
def instructions(dataset: str, task: str, scenario: str, size: int = 3) -> Instructions:
    _dataset(dataset)
    template = _template(task)
    return Instructions(task=task, size=size, instructions=template.instructions(_scenario(scenario)))


@app.post("/api/decide/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    _dataset(req.dataset)
    s = _scenario(req.scenario)
    templates = [_template(t) for t in req.tasks]
    c = client(req.model)
    results = []
    for keys in req.groups:
        numbers: dict[str, list[float] | None] = {}
        missing, errors = False, []
        for template in templates:
            group = _group(template, keys)
            numbers[template.name] = None
            try:
                with labels(**template.label(s, group, SOURCE)):
                    response = c.system_one(**template.render(s, group))
            except CacheMissError:
                missing = True
                continue
            except ConstraintViolatedError as e:
                errors.append(str(e))
                continue
            numbers[template.name] = [round(p, 4) for p in template.probabilities(response.model_dump()["answers"])]
        status = "failed" if errors else "missing" if missing else "answered"
        results.append(GroupResult(status=status, tasks=numbers, error=errors[0] if errors else None))
    return AskResponse(results=results)


RAW = """
SELECT o.request, o.response FROM requests r JOIN observations o ON o.id = r.observation
WHERE r.model = ? AND r.accepted
  AND json_extract(r.labels, '$.dataset') = ? AND json_extract(r.labels, '$.scenario') = ?
  AND json_extract(r.labels, '$.template') = ? AND json_extract(r.labels, '$.template_sha') = ?
  AND json_extract(r.labels, '$.candidates') = ?
ORDER BY r.at DESC LIMIT 1
"""


@app.post("/api/decide/raw", response_model=RawResponse)
def raw(req: RawRequest) -> RawResponse:
    """Found in the store by its labels, the way any query of the decision log is."""
    _dataset(req.dataset)
    s = _scenario(req.scenario)
    client(req.model)  # checks the name
    store: SQLiteStore = gateway().store  # type: ignore[assignment]
    out = {}
    for task in req.tasks:
        template = _template(task)
        group = _group(template, req.group)
        candidates = template.label(s, group, SOURCE)["candidates"]
        found = store.con.execute(
            RAW, (req.model, discrim.DATASET, s, template.name, template.sha, _canonical(candidates))
        ).fetchone()
        if found:
            out[task] = [Raw(request=json.loads(found[0]), response=json.loads(found[1]))]
        else:
            out[task] = [Raw(request=template.render(s, group), response=None)]
    return RawResponse(tasks=out)


def _canonical(value: Any) -> str:  # noqa: ANN401 (any JSON value)
    """JSON as the store writes labels: sorted keys, no spaces."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default: %(default)s)")
    ap.add_argument("--port", type=int, default=8900, help="port (default: %(default)s)")
    ap.add_argument("--store", help="the decision store (default: the gateway's)")
    a = ap.parse_args()
    state["gateway"] = discrim.gateway(a.store, cache_only=True)
    print(f"picks: http://{a.host}:{a.port}/  (store {state['gateway'].store.path})", flush=True)  # type: ignore[attr-defined]
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
