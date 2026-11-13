import asyncio
import json

import httpx2
import pytest
from typesafe_sdk import RetryPolicy, TypeSafeInternalServerError

from decision_gateway import (
    CacheMissError,
    ConstraintViolatedError,
    Gateway,
    ModelConfig,
    RoutedResponse,
    SQLiteStore,
    labels,
)
from decision_gateway.testing import FakeTransport, choice
from decision_gateway.transports.gateway_transport import GatewayTransport

PAST = ["2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z"]


def rows(store: SQLiteStore, sql: str) -> list[tuple[object, ...]]:
    return store.con.execute(sql).fetchall()


def test_a_miss_is_sent_and_recorded_then_a_hit_is_not(store: SQLiteStore, fake: FakeTransport) -> None:
    client = Gateway({"m": fake.model("m")}, store, labels={"run": "r1"}).client("m")
    first = client.system_one(**choice("A", "B"))
    second = client.system_one(**choice("A", "B"))
    assert fake.calls == 1
    assert first == second
    assert rows(store, "SELECT count(*) FROM observations") == [(1,)]
    assert rows(store, "SELECT labels, model, hit, accepted FROM requests ORDER BY at") == [
        ('{"run":"r1"}', "m", 0, 1),
        ('{"run":"r1"}', "m", 1, 1),
    ]


def test_what_is_recorded(store: SQLiteStore) -> None:
    jev = FakeTransport(served="typesafe/jev-1.13-20260917", provider="TypeSafe")
    model = jev.model("jev", model="typesafe/jev-1.13", base_url="https://openrouter.ai/api")
    Gateway({"jev": model}, store).client("jev").system_one(**choice("A", "B"))
    endpoint, request, model_id, provider, cost, response = rows(
        store, "SELECT endpoint, request, model, provider, cost, response FROM observations"
    )[0]
    assert endpoint == "https://openrouter.ai/api/v1/systemone"
    assert json.loads(str(request))["model"] == "typesafe/jev-1.13"  # what was asked
    assert (model_id, provider, cost) == ("typesafe/jev-1.13-20260917", "TypeSafe", 0.001)  # who answered
    assert json.loads(str(response))["id"] == "gen-1"  # the response as received, fields beyond the API too


def test_labels_and_extra_fields(store: SQLiteStore, fake: FakeTransport) -> None:
    client = Gateway({"m": fake.model("m")}, store).client("m")
    with labels(study="demo"), labels(item=17):
        response = client.system_one(**choice("A", "B"), response_model=RoutedResponse)
    client.system_one(**choice("A", "B"))
    assert response.model_extra == {"id": "gen-1", "provider": "Fake"}
    assert rows(store, "SELECT labels FROM requests ORDER BY at") == [('{"item":17,"study":"demo"}',), ("{}",)]


def test_the_routers_labels_go_with_every_request_and_a_calls_own_win(store: SQLiteStore, fake: FakeTransport) -> None:
    client = Gateway({"m": fake.model("m")}, store, labels={"project": "evals", "run": "r1"}).client("m")
    client.system_one(**choice("A", "B"))
    with labels(run="r2", item=3):
        client.system_one(**choice("A", "B"))
    assert rows(store, "SELECT labels FROM requests ORDER BY at") == [
        ('{"project":"evals","run":"r1"}',),
        ('{"item":3,"project":"evals","run":"r2"}',),
    ]


def test_extra_body_from_the_config_is_sent_and_keyed(store: SQLiteStore, fake: FakeTransport) -> None:
    pin = {"provider": {"only": ["typesafe"], "allow_fallbacks": False}}
    client = Gateway({"m": fake.model("m", extra_body=pin)}, store).client("m")
    client.system_one(**choice("A", "B"))
    client.system_one(**choice("A", "B"), extra_body={"provider": {"only": ["other"]}})  # the call's own wins
    assert fake.requests[0]["provider"] == pin["provider"]
    assert fake.requests[1]["provider"] == {"only": ["other"]}
    assert fake.calls == 2


def test_different_requests_are_different_keys(store: SQLiteStore, fake: FakeTransport) -> None:
    client = Gateway({"m": fake.model("m")}, store).client("m")
    client.system_one(**choice("A", "B"))
    client.system_one(**choice("A", "B", "C"))
    client.system_one(**choice("A", "B", state={"case": 2}))
    client.system_one(**choice("A", "B"), model="m2")
    assert fake.calls == 4


def test_names_share_answers_for_the_same_request(store: SQLiteStore, fake: FakeTransport) -> None:
    # the name is not part of the key: another name for the same configuration finds the answers
    url = "http://shared.fake.invalid"
    Gateway({"a": fake.model("a", model="m", base_url=url)}, store).client("a").system_one(**choice("A", "B"))
    Gateway({"b": fake.model("b", model="m", base_url=url)}, store).client("b").system_one(**choice("A", "B"))
    assert fake.calls == 1


def test_a_rejected_response_is_kept_and_counts_for_a_name_that_accepts_it(store: SQLiteStore) -> None:
    moved = FakeTransport(served="m-20261101")
    url = "http://m.fake.invalid"
    old = moved.model("old", model="m", base_url=url, requirements_table={"systemone_response_model_id": "m-20260917"})
    new = moved.model("new", model="m", base_url=url, requirements_table={"systemone_response_model_id": "m-20261101"})
    with pytest.raises(
        ConstraintViolatedError, match="response not accepted, served by 'm-20261101', not 'm-20260917'"
    ):
        Gateway({"old": old}, store).client("old").system_one(**choice("A", "B"))
    response = Gateway({"new": new}, store).client("new").system_one(**choice("A", "B"))
    assert response.model == "m-20261101"
    assert moved.calls == 1  # paid once
    assert rows(store, "SELECT model, hit, accepted, reason IS NULL FROM requests ORDER BY at") == [
        ("old", 0, 0, 0),
        ("new", 1, 1, 1),
    ]


def test_a_request_outside_the_date_range_is_not_sent(store: SQLiteStore, fake: FakeTransport) -> None:
    late = fake.model("m", requirements_table={"request_date_range": PAST})
    with pytest.raises(ConstraintViolatedError, match="not sent, now is"):
        Gateway({"m": late}, store).client("m").system_one(**choice("A", "B"))
    assert fake.calls == 0


def test_stored_answers_outside_the_date_range_are_not_used(store: SQLiteStore, fake: FakeTransport) -> None:
    url = "http://m.fake.invalid"
    Gateway({"any": fake.model("any", model="m", base_url=url)}, store).client("any").system_one(**choice("A", "B"))
    window = fake.model("window", model="m", base_url=url, requirements_table={"request_date_range": PAST})
    with pytest.raises(ConstraintViolatedError, match="not sent"):  # the stored answer is too recent, and so is now
        Gateway({"window": window}, store).client("window").system_one(**choice("A", "B"))
    assert fake.calls == 1


def test_cache_off_records_but_never_serves(store: SQLiteStore, fake: FakeTransport) -> None:
    client = Gateway({"m": fake.model("m", cache=False)}, store).client("m")
    client.system_one(**choice("A", "B"))
    client.system_one(**choice("A", "B"))
    assert fake.calls == 2
    assert rows(store, "SELECT count(*) FROM observations") == [(2,)]


def test_errors_are_not_recorded_and_the_sdk_retries(store: SQLiteStore, fake: FakeTransport) -> None:
    client = Gateway({"m": fake.model("m", max_retries=1)}, store).client("m")
    fake.statuses = [503, 502, 502]
    with pytest.raises(TypeSafeInternalServerError):
        client.system_one(**choice("A", "B"))
    assert fake.calls == 2  # the SDK's retry
    client.system_one(**choice("A", "B"))  # 502, retried, then answered
    assert fake.calls == 4
    assert rows(store, "SELECT count(*) FROM observations") == [(1,)]


def test_a_response_that_answers_other_questions_is_not_recorded(store: SQLiteStore, fake: FakeTransport) -> None:
    fake.wrong = True
    Gateway({"m": fake.model("m")}, store).client("m").system_one(**choice("A", "B"))
    assert rows(store, "SELECT count(*) FROM observations") == [(0,)]


@pytest.mark.parametrize(
    "headers",
    [
        {"content-type": "application/json", "content-encoding": "zstd"},  # compressed
        {"content-type": "multipart/form-data; boundary=x"},  # with assets
    ],
)
def test_compressed_and_multipart_requests_pass_through_unrecorded(
    store: SQLiteStore, fake: FakeTransport, headers: dict[str, str]
) -> None:
    passed = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        passed.append(request)
        return httpx2.Response(200, json={})

    transport = GatewayTransport(fake.model("m"), store, transport=httpx2.MockTransport(handler))
    request = httpx2.Request("POST", "http://m.invalid/v1/systemone", headers=headers, content=b"not json")
    assert transport.handle_request(request).status_code == 200
    assert passed == [request]
    assert rows(store, "SELECT count(*) FROM requests") == [(0,)]


def test_other_endpoints_pass_through(store: SQLiteStore) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"models": [{"name": "m", "description": "d", "release_date": "2026-01-01"}]})

    model = ModelConfig(name="m", backend="uniform", transport=httpx2.MockTransport(handler))
    client = Gateway({"m": model}, store).client("m")
    assert [m.name for m in client.models.list().models] == ["m"]
    assert rows(store, "SELECT count(*) FROM requests") == [(0,)]


def test_async(store: SQLiteStore, fake: FakeTransport) -> None:
    gateway = Gateway({"m": fake.model("m")}, store, labels={"app": "web"})

    async def run() -> None:
        async with gateway.async_client("m") as client:
            with labels(page="ask"):
                await client.system_one(**choice("A", "B"))
                await client.system_one(**choice("A", "B"))

    asyncio.run(run())
    assert fake.calls == 1
    assert rows(store, "SELECT hit, labels FROM requests ORDER BY at") == [
        (0, '{"app":"web","page":"ask"}'),
        (1, '{"app":"web","page":"ask"}'),
    ]


def test_uniform(store: SQLiteStore) -> None:
    client = Gateway({"u": ModelConfig(name="u", backend="uniform")}, store).client("u")
    r = client.system_one(**choice("A", "B", "C"))
    assert r.model == "uniform"
    assert r.choices["pick"].probabilities["B"] == pytest.approx(1 / 3)


def test_a_custom_retry_policy_still_applies(store: SQLiteStore, fake: FakeTransport) -> None:
    client = Gateway({"m": fake.model("m")}, store).client("m")
    fake.statuses = [503]
    with pytest.raises(TypeSafeInternalServerError):
        client.system_one(**choice("A", "B"), retry=RetryPolicy(max_retries=0))
    assert fake.calls == 1


def test_cache_only_answers_from_the_store_and_sends_nothing(store: SQLiteStore, fake: FakeTransport) -> None:
    Gateway({"m": fake.model("m")}, store).client("m").system_one(**choice("A", "B"))
    cached = Gateway({"m": fake.model("m")}, store, cache_only=True).client("m")
    assert cached.system_one(**choice("A", "B")).answers["pick"].choice == "A"
    with pytest.raises(CacheMissError, match="not in the store"):
        cached.system_one(**choice("A", "C"))
    assert fake.calls == 1
    assert rows(store, "SELECT hit FROM requests ORDER BY at") == [(0,), (1,)]  # the miss is not recorded


def test_cache_only_needs_no_key_and_lets_nothing_through(store: SQLiteStore, fake: FakeTransport) -> None:
    model = fake.model("m", key_env="NO_SUCH_KEY")
    client = Gateway({"m": model}, store, cache_only=True).client("m")
    with pytest.raises(CacheMissError, match="not a System One request"):
        client.models.list()
    assert fake.calls == 0


def test_cache_only_async(store: SQLiteStore, fake: FakeTransport) -> None:
    async def ask() -> None:
        async with Gateway({"m": fake.model("m")}, store, cache_only=True).async_client("m") as client:
            await client.system_one(**choice("A", "B"))

    with pytest.raises(CacheMissError):
        asyncio.run(ask())
    assert fake.calls == 0
