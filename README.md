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

from decision_gateway import Gateway, SQLiteStore, config, labels

gateway = Gateway(config.load("models.toml"), SQLiteStore("evals.sqlite"), labels={"project": "evals"})
eval_set = ["I was charged twice for my subscription.", "How do I change my password?"]

with gateway.client("jev") as client:  # a typesafe_sdk.TypeSafeClient; gateway.async_client() for async
    for item, text in enumerate(eval_set):
        with labels(item=item):
            response = client.system_one(
                state=text,
                questions={"refund": Noul(instructions="Is the customer asking for money back?")},
            )
        response.nouls["refund"].noul
```

The client is the SDK's own, so everything the SDK offers works as before. Running the same
requests again sends only what is not in the store. Each `gateway.client()` call builds a new
SDK client with its own connections: make one per model and reuse it, as above.

### Labels

Labels say what a request was about, in your terms, for queries later. They don't affect what
is sent or which answer is used. They come from three places, a later one winning for the same
key:

- the gateway's: `Gateway(..., labels={"project": "evals"})`, on every request;
- `labels(...)` around the call, as a context manager or as a decorator on a sync or async
  function: `@labels(study="demo")`;
- `label_headers(...)` passed with the call: `client.system_one(..., extra_headers=label_headers(item=17))`.

`labels(...)` follows `await`, asyncio tasks and `asyncio.to_thread`, but not calls made in a
`ThreadPoolExecutor` or `run_in_executor`, which don't carry context variables. Use
`label_headers(...)` there: it goes with the request, and the gateway removes it before
anything is sent.

`models.toml` says which models there are, how the client for each is configured (endpoint,
key, model id, provider pin) and which answers each accepts.
[`models.example.toml`](models.example.toml) describes every field, with examples; copy it to
start.

The gateway is an httpx transport, so it also works with a client you configure yourself:

```python
from typesafe_sdk import TypeSafeClient

from decision_gateway import GatewayTransport, SQLiteStore, config

gateway = GatewayTransport(config.load("models.toml")["jev"], SQLiteStore("evals.sqlite"))
client = TypeSafeClient(model="jev-1.13", transport=gateway)
```

## What is recorded

One store, append-only (`SQLiteStore` for now; `Store` is the interface):

- **observations**: every response received, with what was sent, where, the response as
  received, the model and provider it reports, when, and the cost. Responses a model's
  requirements did not accept are kept too.
- **requests**: every request made through the gateway: when, labels, model name, which
  observation answered it, whether it came from the store, and whether it was accepted.

The store's file is wherever you put it; `SQLiteStore()` without a path uses
`$DECISION_GATEWAY_STORE`, or `store.sqlite` in the platform's user data directory.

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
`ConstraintViolatedError`. When a model changes, a new name with requirements for the new
version uses the responses already recorded from it, without asking again.

A requirement of your own is a function that returns why an observation doesn't count, or
`None` if it does, named in `models.toml` as `"module:function"`:

```python
def max_cost(observation, at_most):
    cost = observation.cost or 0.0
    return None if cost <= at_most else f"cost {cost} is above {at_most}"
```

See `models.example.toml` for all built-ins and the details.

## Layout

```
src/decision_gateway/
  gateway.py                Gateway: SDK clients by model name (the entry point)
  config.py                 models.toml -> ModelConfig (with its requirements: a list of constraints)
  constraints.py            Constraint, the built-ins, FunctionConstraint, ConstraintViolatedError,
                            from_config() and the checks
  labels.py                 labels(), label_headers()
  systemone.py              RoutedResponse: the SDK's response, keeping fields beyond the API
  transports/
    gateway_transport.py      GatewayTransport, AsyncGatewayTransport
    uniform_transport.py      UniformTransport (sync and async)
    fake_transport.py         FakeTransport, for tests
  store/
    base.py                   Store, Observation, RequestEvent
    sqlite.py                 SQLiteStore
    key.py                    the request key (what lookups use)
  testing.py                choice() and FakeTransport, for tests
tests/                      tests that span the package (the built wheel)
```

Each module's unit tests sit next to it (`gateway.py`, `gateway_test.py`), one of the two layouts
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
