import asyncio
from concurrent.futures import ThreadPoolExecutor

import httpx2

from decision_gateway import Gateway, SQLiteStore, label_headers, labels
from decision_gateway.labels import HEADER, current
from decision_gateway.testing import FakeTransport, choice
from decision_gateway.transports.gateway_transport import GatewayTransport


def test_context_manager_nested_and_restored() -> None:
    with labels(a=1):
        with labels(b=2, a=3):
            assert current() == {"a": 3, "b": 2}
        assert current() == {"a": 1}
    assert current() == {}


def test_decorator_on_a_function() -> None:
    @labels(study="sync")
    def run() -> dict[str, object]:
        return current()

    assert run() == {"study": "sync"}
    assert current() == {}


def test_decorator_on_an_async_function() -> None:
    @labels(study="async")
    async def run() -> dict[str, object]:
        await asyncio.sleep(0)
        return current()

    assert asyncio.run(run()) == {"study": "async"}


def test_one_instance_reused() -> None:
    demo = labels(study="demo")
    with demo, demo:
        assert current() == {"study": "demo"}
    assert current() == {}


def rows(store: SQLiteStore) -> list[tuple[object, ...]]:
    return store.con.execute("SELECT labels FROM requests ORDER BY at").fetchall()


def test_router_labels_then_context_then_headers(store: SQLiteStore, fake: FakeTransport) -> None:
    client = Gateway({"m": fake.model("m")}, store, labels={"run": "r1", "item": 0}).client("m")
    with labels(item=1, page="a"):
        client.system_one(**choice("A", "B"), extra_headers=label_headers(item=2))
    assert rows(store) == [('{"item":2,"page":"a","run":"r1"}',)]


def test_label_headers_survive_a_thread_pool(store: SQLiteStore, fake: FakeTransport) -> None:
    client = Gateway({"m": fake.model("m")}, store).client("m")
    with labels(lost="yes"), ThreadPoolExecutor(4) as pool:  # context variables don't reach pool threads
        list(
            pool.map(
                lambda i: client.system_one(**choice("A", "B", state={"i": i}), extra_headers=label_headers(item=i)),
                range(3),
            )
        )
    assert sorted(rows(store)) == [('{"item":0}',), ('{"item":1}',), ('{"item":2}',)]


def test_the_labels_header_is_never_sent(store: SQLiteStore) -> None:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(
            200, json={"model": "m", "answers": {"pick": {"type": "noul", "noul": 0.5}}, "usage": {}}
        )

    fake = FakeTransport()
    transport = GatewayTransport(fake.model("m"), store, transport=httpx2.MockTransport(handler))
    headers = {"content-type": "application/json", **label_headers(item=1)}
    body = b'{"model": "m", "state": 1, "questions": {"pick": {"type": "noul", "instructions": "?"}}}'
    transport.handle_request(httpx2.Request("POST", "http://m.invalid/v1/systemone", headers=headers, content=body))
    transport.handle_request(httpx2.Request("GET", "http://m.invalid/v1/models", headers=headers))  # passed through
    assert [HEADER in r.headers for r in sent] == [False, False]
    assert rows(store) == [('{"item":1}',)]
