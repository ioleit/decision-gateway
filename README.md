# decision-gateway

A gateway for System One decision models such as Jev, under TypeSafe's SDK client
([`typesafe-sdk`](https://pypi.org/project/typesafe-sdk/)). Requests from the SDK client go
through it: they are routed by model name, answered from the store when the same request was
answered before, and recorded.

Status: early. Models are reached through TypeSafe's API, OpenRouter, any System One server,
or `uniform`, a local baseline that gives every option equal probability.

## Install

```bash
pip install decision-gateway
```

## Use

```python
from typesafe_sdk import Noul

from decision_gateway import Router, SQLiteStore, labels, models

router = Router(models.load("models.toml"), SQLiteStore("evals.sqlite"), project="evals", run="2026-10")
client = router.client("jev")  # a typesafe_sdk.TypeSafeClient; router.async_client() for async

with labels(item=17):
    response = client.system_one(
        state="I was charged twice for my subscription.",
        questions={"refund": Noul(instructions="Is the customer asking for money back?")},
    )
response.nouls["refund"].noul
```

The client is the SDK's own, so everything the SDK offers works as before. Running the same
requests again sends only what is not in the store.

`models.toml` says which models there are, how the client for each is configured (endpoint,
key, model id, provider pin) and which answers each accepts.
[`models.example.toml`](models.example.toml) describes every field, with examples; copy it to
start.

The gateway is an httpx transport, so it also works with a client you configure yourself:

```python
from typesafe_sdk import TypeSafeClient

from decision_gateway import GatewayTransport, SQLiteStore, models

gateway = GatewayTransport(models.load("models.toml")["jev"], SQLiteStore("evals.sqlite"))
client = TypeSafeClient(model="jev-1.13", transport=gateway)
```

## What is recorded

One store, append-only (`SQLiteStore` for now; `Store` is the interface):

- **observations**: every response received, with what was sent, where, the response as
  received, the model and provider it reports, when, and the cost. Responses a model's
  requirements did not accept are kept too.
- **requests**: every request made through the gateway: when, project, run, labels, model
  name, which observation answered it, whether it came from the store, and whether it was
  accepted.

A request is answered from the store when there is an observation for the same request (the
body as sent, to the same endpoint) that the model's requirements accept. The key is frozen by
golden hashes (`src/decision_gateway/key_test.py`).

Errors (HTTP errors, timeouts) are raised by the SDK as usual and not recorded. Requests with
assets (images) are sent but not recorded yet.

## Requirements

Which answers a model name accepts. Used to prevent different models served by the same
backend configuration from sharing answers, for example minor updates without a version jump:

```toml
[models.jev.requirements]
systemone_response_model_id = "typesafe/jev-1.13-20260917"   # the model the response reports
openrouter_response_provider = "TypeSafe"                    # the provider OpenRouter reports
```

A response that is not accepted is still recorded, and the call raises
`RequirementNotMetError`. When a model changes, a new name with requirements for the new
version uses the responses already recorded from it, without asking again. See
`models.example.toml` for all built-ins and for writing your own.

## Layout

```
src/decision_gateway/
  transport.py       the gateway: GatewayTransport and AsyncGatewayTransport, labels()
  router.py          Router: SDK clients by model name, through the gateway
  models.py          models.toml -> client configuration
  requirements.py    built-in requirements and the base class for your own
  store.py           Store, SQLiteStore, Observation, RequestEvent
  key.py             the request key
  systemone.py       RoutedResponse: the SDK's response, keeping fields beyond the API
  uniform.py         the uniform baseline, as a local transport
  testing.py         FakeServer (a transport) and request helpers, for tests
tests/               tests that span the package (the built wheel)
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
