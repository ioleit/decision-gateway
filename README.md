# decision-gateway

Scaffolding to work with decision models, allowing to divert traffic to different models based and keep a decision log that can serve both as as a cache but also exported and queried in offline analysis of decisions. 

The gateway sits underneath TypeSafe's Python SDK
([`typesafe-sdk`](https://pypi.org/project/typesafe-sdk/)). Code keeps using the SDK's own client, but its requests pass through the gateway, which

- **routes** each model name to its configuration: endpoint, key, model id, customizable other constraints
- **records decisions**: every request and every response, with arbirraty application side labels.
- **answers locally**: with single forward pass, decision models are close to determinstic, so the answers can be source from an application-side cache.


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

Labels are arbitrary data attached to a request that are used to query the decision log.

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

## Decision Store

Decision Store keeps:

- **observations**: every response received, with what was sent, where, the response as
  received, the model and provider it reports, when, and the cost. Responses a model's
  requirements did not accept are kept too.
- **requests**: every request made through the gateway: when, labels, model name, which
  observation answered it, whether it came from the store, and whether it was accepted.

A request is answered from the store when there is an observation for the same request (the
body as sent, to the same endpoint) that the model's requirements accept. 

Currently there is only a simple `SQLiteStore` implementation of `Store` that is useful for single-task exploration or demos.


## Model Configuration

The set of available models can be defined in `models.toml`.

See `models.example.toml` for all built-ins and the details.


## License

Apache-2.0
