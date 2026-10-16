# decision-gateway

A drop-in replacement for TypeSafe's SDK client ([`typesafe-sdk`](https://pypi.org/project/typesafe-sdk/))
for System One decision models such as Jev. It routes each request by model name to a
configured SDK client, and caches the answers, so the same question is never asked twice.

Status: early. Models are reached through TypeSafe's API, OpenRouter, any System One server,
or `uniform`, a local baseline that gives every option equal probability. `examples/smoke`
walks through asking, querying and preheating, with uniform or live with Jev through
OpenRouter.

## Parts

- **Router**: `Router.system_one(...)` takes the same arguments as `TypeSafeClient.system_one`
  and returns the same response. `model` is a name in `models.toml`, which says how the SDK
  client for it is configured. `AsyncRouter` does the same for `AsyncTypeSafeClient`.
- **Cache**: one SQLite file (WAL), shared by every process on a machine. An answer is keyed
  by the model's name, its requirements and the request body as sent, and is final.
- **Requirements**: reject responses that don't come from the model a name stands for (see
  `models.example.toml`).
- **Labels**: what a question is about, in the caller's terms: any JSON object, several per
  answer. Never part of the key and never used to find an answer; only for queries.
- **Query** (`decision_gateway.query`): read-only SQL with DuckDB over the cache or an export,
  without asking any model. A Python library first, with a CLI on top.
- **Export / preheat**: write the answers a query selects to parquet (and a Hugging Face
  dataset), and load such an export into a cache, for instance to serve a deployment that never
  calls a model.

## Install

```bash
pip install -e .            # router and cache; brings typesafe-sdk (pydantic, httpx2, ...)
pip install -e '.[query]'   # + DuckDB, for query and export
pip install -e '.[hub]'     # + huggingface_hub, for push and hf:// preheat
pip install -e '.[dev]'     # + pytest, build, ruff, mypy (and DuckDB, huggingface_hub)
```

## Use

Where code uses the SDK's client:

```python
from typesafe_sdk import Noul, TypeSafeClient

state = "I was charged twice for my subscription."
questions = {"refund": Noul(instructions="Is the customer asking for money back?")}

client = TypeSafeClient(model="jev-1.13")
response = client.system_one(state=state, questions=questions)
```

the router takes its place:

```python
from decision_gateway import Cache, Router, models

client = Router(models.load("models.toml"), Cache(), default_model="jev")
response = client.system_one(state=state, questions=questions)
response.nouls["refund"].noul  # the SDK's SystemOneResponse (a subclass of it)

client.system_one(state=state, questions=questions, model="uniform", labels={"study": "demo"})
client.cached(state=state, questions=questions)  # from the cache only; None if not there
```

Fields a server adds beyond the System One API, such as OpenRouter's `provider`, are kept in
`response.model_extra`. Requests with assets (images) are sent but not cached yet.

`models.toml` says which models there are and how each is reached.
[`models.example.toml`](models.example.toml) describes every field, with examples; copy it to
start.

```python
from decision_gateway import query

con = query.connect()  # the cache; or query.connect("exports/run-1")
con.sql("""SELECT model, labels->>'task' AS task, count(*) AS n
           FROM answers JOIN labels USING (key) GROUP BY ALL""").show()
```

```bash
decision-gateway query "SELECT model, count(*) FROM answers GROUP BY ALL"
decision-gateway export exports/run-1 --keys "SELECT key FROM answers WHERE model = 'uniform'"
decision-gateway export exports/run-1 --push you/decision-answers      # private by default
decision-gateway preheat hf://you/decision-answers
```

The cache is `~/.local/share/decision-gateway/cache.sqlite`, or `$DECISION_GATEWAY_CACHE`, or
`--cache`. Reading it from DuckDB uses DuckDB's `sqlite` extension, which DuckDB downloads on
first use.

## The cache key

`sha256(json.dumps([model, requirements, request], sort_keys=True, ensure_ascii=False))`:
the model's name in `models.toml`, its `requirements` table as written, and the request body as
the SDK sends it. The name stands for one configuration (model id, provider pin and
requirements): answers are shared by every project that uses the same name for the same
configuration, and renaming an entry starts a new set of answers.

The format is frozen by golden hashes (`src/decision_gateway/cache/key_test.py`), so an
export preheats any cache to the same hits.

## Layout

```
src/decision_gateway/
  router.py          Router and AsyncRouter: system_one routed by name, cached
  models.py          models.toml -> configured TypeSafe SDK clients
  systemone.py       the request body as sent, the response type, checks
  requirements.py    built-in requirements and the base classes for your own
  uniform.py         the uniform baseline, as a local transport for the SDK
  cache/             key.py, schema.sql, sqlite.py, export.py, preheat.py
  query.py           DuckDB over a cache file or an export
  cli.py             decision-gateway query | export | preheat
  testing.py         FakeServer (a transport for the SDK) and request helpers, for tests
tests/               tests that span the package: the built wheel, the examples
examples/smoke/      ten yes/no questions: ask 5, query, preheat 5 from golden/, ask all again
```

Each module's unit tests sit next to it (`router.py`, `router_test.py`), one of the two layouts
pytest describes in [Choosing a test layout](https://docs.pytest.org/en/stable/explanation/goodpractices.html#choosing-a-test-layout).
They are left out of the wheel.

## Development

```bash
pip install -e '.[dev]'
ruff check . && ruff format --check .   # every rule, with the exceptions listed in pyproject.toml
mypy                                    # strict
pytest                                  # warnings are errors
```

CI runs the same on every pull request (`.github/workflows/ci.yml`), with pytest on Python
3.11 to 3.14.

## License

Apache-2.0
