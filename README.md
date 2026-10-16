# decision-router

Ask decision models (Jev-style APIs that return a choice and its probabilities in one pass)
through one router, with a cache that never asks the same question twice.

Status: early. Backends: `uniform` (a no-network baseline that gives every option equal
probability), `openrouter` and `http` (any endpoint that takes a Jev request). The HTTP
backends are tested against a local server; `examples/smoke` walks through asking, querying
and preheating, with uniform or live with Jev through OpenRouter.

## Parts

- **Router**: `Router.ask(model, request, labels=...)` answers from the cache, or asks the
  model's backend and caches the answer.
- **Cache**: one SQLite file (WAL), shared by every process on a machine. An answer is keyed
  by model, version and the request exactly as sent, and is final.
- **Labels**: what a question is about, in the caller's terms: any JSON object, several per
  answer. Never part of the key and never used to find an answer; only for queries.
- **Query** (`decision_router.query`): read-only SQL with DuckDB over the cache or an export,
  without asking any model. A Python library first, with a CLI on top.
- **Export / preheat**: write the answers a query selects to parquet (and a Hugging Face
  dataset), and load such an export into a cache, for instance to serve a deployment that never
  calls a model.

## Install

```bash
pip install -e .            # router and cache only, no dependencies
pip install -e '.[query]'   # + DuckDB, for query and export
pip install -e '.[hub]'     # + huggingface_hub, for push and hf:// preheat
pip install -e '.[dev]'     # + pytest, build, ruff, mypy (and DuckDB, huggingface_hub)
```

## Use

```python
from decision_router import Cache, Router, models

router = Router(models.load("models.toml"), Cache())
request = {
    "state": {"options": ["A", "B", "C"]},
    "questions": {"pick": {"type": "choice", "criteria": {"A": "...", "B": "...", "C": "..."}}},
}
response = router.ask("uniform", request, labels={"study": "demo", "item": 7})
router.cached("uniform", request)  # the same response, without asking
```

`models.toml` says which models there are, how each is reached, and when its answers may be
cached. [`models.example.toml`](models.example.toml) describes every field, with examples;
copy it to start.

```python
from decision_router import query

con = query.connect()  # the cache; or query.connect("exports/run-1")
con.sql("""SELECT model, labels->>'task' AS task, count(*) AS n
           FROM answers JOIN labels USING (key) GROUP BY ALL""").show()
```

```bash
decision-router query "SELECT model, version, count(*) FROM answers GROUP BY ALL"
decision-router export exports/run-1 --keys "SELECT key FROM answers WHERE model = 'uniform'"
decision-router export exports/run-1 --push you/decision-answers      # private by default
decision-router preheat hf://you/decision-answers
```

The cache is `~/.local/share/decision-router/cache.sqlite`, or `$DECISION_ROUTER_CACHE`, or
`--cache`. Reading it from DuckDB uses DuckDB's `sqlite` extension, which DuckDB downloads on
first use.

## The cache key

`sha256(json.dumps([model, version, wire], sort_keys=True, ensure_ascii=False))`, where
`wire` is the request as it goes over the network. A new model version is a new key, so the
version must say exactly what answered: pinned weights (`org/repo@<commit>`) or a dated API
model id. The format is frozen by golden hashes (`src/decision_router/cache/key_test.py`), so an export preheats
any cache to the same hits.

## Layout

```
src/decision_router/
  router.py          cache lookup, backend call on a miss, store
  models.py          models.toml -> backends
  backends/          base.py (the Backend interface), uniform.py, http.py (http, openrouter)
  cache/             key.py, schema.sql, sqlite.py, export.py, preheat.py
  query.py           DuckDB over a cache file or an export
  cli.py             decision-router query | export | preheat
  testing.py         Fake backend and request helpers, for tests of code that uses the router
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
