# decision-gateway

Scaffolding to work with decision models: it diverts traffic to different models by name and
keeps a decision log that serves both as a cache and as data to export and query in offline
analysis of decisions.

The gateway sits underneath TypeSafe's Python SDK
([`typesafe-sdk`](https://pypi.org/project/typesafe-sdk/)). Code keeps using the SDK's own
client, but its requests pass through the gateway, which

- **routes** each model name to its configuration: endpoint, key, model id and other
  customizable constraints;
- **records decisions**: every request and every response, with arbitrary application-side
  labels;
- **answers locally**: with a single forward pass, decision models are close to deterministic,
  so answers can be sourced from an application-side cache.

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

### Decision Log Labels

Labels are arbitrary data attached to a request and used to query the decision log. They can be
set in three places:

- the gateway's: `Gateway(..., labels={"project": "evals"})`, on every request;
- `labels(...)` around the call, as a context manager or as a decorator on a sync or async
  function: `@labels(study="demo")`;
- `label_headers(...)` passed with the call: `client.system_one(..., extra_headers=label_headers(item=17))`.

`labels(...)` follows `await`, asyncio tasks and `asyncio.to_thread`, but not calls made in a
`ThreadPoolExecutor` or `run_in_executor`, which don't carry context variables. Use
`label_headers(...)` there: it goes with the request, and the gateway removes it before
anything is sent.

## Decision Store

The decision store keeps:

- **observations**: every response received, with what was sent, where, the response as
  received, the model and provider it reports, when, and the cost. Responses a model's
  requirements did not accept are kept too.
- **requests**: every request made through the gateway: when, labels, model name, which
  observation answered it, whether it came from the store, and whether it was accepted.

A request is answered from the store when there is an observation for the same request (the
body as sent, to the same endpoint) that the model's requirements accept.

Currently, `SQLiteStore` is the only implementation of `Store`; it is useful for single-task
exploration or demos.

## Model Configuration

The available models are defined in `models.toml`: how the client for each is configured
(endpoint, key, model id, provider pin) and which answers each accepts.
[`models.example.toml`](models.example.toml) describes every field and the built-ins, with
examples; copy it to start.

## License

Apache-2.0
