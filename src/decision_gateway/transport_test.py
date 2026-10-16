import asyncio
import json

import httpx2
import pytest
from typesafe_sdk import RetryPolicy, TypeSafeClient, TypeSafeInternalServerError

from decision_gateway import Model, RequirementNotMetError, RoutedResponse, Router, SQLiteStore, labels
from decision_gateway.testing import FakeServer, choice
from decision_gateway.transport import GatewayTransport

PAST = ["2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z"]


def rows(store: SQLiteStore, sql: str) -> list[tuple[object, ...]]:
    return store.con.execute(sql).fetchall()


def test_a_miss_is_sent_and_recorded_then_a_hit_is_not(store: SQLiteStore, server: FakeServer) -> None:
    client = Router({"m": server.model("m")}, store, project="evals", run="r1").client("m")
    first = client.system_one(**choice("A", "B"))
    second = client.system_one(**choice("A", "B"))
    assert server.calls == 1
    assert first == second
    assert rows(store, "SELECT count(*) FROM observations") == [(1,)]
    assert rows(store, "SELECT project, run, model, hit, accepted FROM requests ORDER BY at") == [
        ("evals", "r1", "m", 0, 1),
        ("evals", "r1", "m", 1, 1),
    ]


def test_the_client_is_the_sdks_own(store: SQLiteStore, server: FakeServer) -> None:
    client = Router({"m": server.model("m")}, store).client("m")
    assert type(client) is TypeSafeClient


def test_what_is_recorded(store: SQLiteStore) -> None:
    jev = FakeServer(served="typesafe/jev-1.13-20260917", provider="TypeSafe")
    model = jev.model("jev", model="typesafe/jev-1.13", base_url="https://openrouter.ai/api")
    Router({"jev": model}, store).client("jev").system_one(**choice("A", "B"))
    endpoint, request, model_id, provider, cost, response = rows(
        store, "SELECT endpoint, request, model, provider, cost, response FROM observations"
    )[0]
    assert endpoint == "https://openrouter.ai/api/v1/systemone"
    assert json.loads(str(request))["model"] == "typesafe/jev-1.13"  # what was asked
    assert (model_id, provider, cost) == ("typesafe/jev-1.13-20260917", "TypeSafe", 0.001)  # who answered
    assert json.loads(str(response))["id"] == "gen-1"  # the response as received, fields beyond the API too


def test_labels_and_extra_fields(store: SQLiteStore, server: FakeServer) -> None:
    client = Router({"m": server.model("m")}, store).client("m")
    with labels(study="demo"), labels(item=17):
        response = client.system_one(**choice("A", "B"), response_model=RoutedResponse)
    client.system_one(**choice("A", "B"))
    assert response.model_extra == {"id": "gen-1", "provider": "Fake"}
    assert rows(store, "SELECT labels FROM requests ORDER BY at") == [('{"item":17,"study":"demo"}',), ("{}",)]


def test_extra_body_from_the_config_is_sent_and_keyed(store: SQLiteStore, server: FakeServer) -> None:
    pin = {"provider": {"only": ["typesafe"], "allow_fallbacks": False}}
    client = Router({"m": server.model("m", extra_body=pin)}, store).client("m")
    client.system_one(**choice("A", "B"))
    client.system_one(**choice("A", "B"), extra_body={"provider": {"only": ["other"]}})  # the call's own wins
    assert server.requests[0]["provider"] == pin["provider"]
    assert server.requests[1]["provider"] == {"only": ["other"]}
    assert server.calls == 2


def test_different_requests_are_different_keys(store: SQLiteStore, server: FakeServer) -> None:
    client = Router({"m": server.model("m")}, store).client("m")
    client.system_one(**choice("A", "B"))
    client.system_one(**choice("A", "B", "C"))
    client.system_one(**choice("A", "B", state={"case": 2}))
    client.system_one(**choice("A", "B"), model="m2")
    assert server.calls == 4


def test_names_share_answers_for_the_same_request(store: SQLiteStore, server: FakeServer) -> None:
    # the name is not part of the key: another name for the same configuration finds the answers
    url = "http://shared.fake.invalid"
    Router({"a": server.model("a", model="m", base_url=url)}, store).client("a").system_one(**choice("A", "B"))
    Router({"b": server.model("b", model="m", base_url=url)}, store).client("b").system_one(**choice("A", "B"))
    assert server.calls == 1


def test_a_rejected_response_is_kept_and_counts_for_a_name_that_accepts_it(store: SQLiteStore) -> None:
    moved = FakeServer(served="m-20261101")
    url = "http://m.fake.invalid"
    old = moved.model("old", model="m", base_url=url, requirements_table={"systemone_response_model_id": "m-20260917"})
    new = moved.model("new", model="m", base_url=url, requirements_table={"systemone_response_model_id": "m-20261101"})
    with pytest.raises(RequirementNotMetError, match="response not accepted, served by 'm-20261101', not 'm-20260917'"):
        Router({"old": old}, store).client("old").system_one(**choice("A", "B"))
    response = Router({"new": new}, store).client("new").system_one(**choice("A", "B"))
    assert response.model == "m-20261101"
    assert moved.calls == 1  # paid once
    assert rows(store, "SELECT model, hit, accepted, reason IS NULL FROM requests ORDER BY at") == [
        ("old", 0, 0, 0),
        ("new", 1, 1, 1),
    ]


def test_a_request_outside_the_date_range_is_not_sent(store: SQLiteStore, server: FakeServer) -> None:
    late = server.model("m", requirements_table={"request_date_range": PAST})
    with pytest.raises(RequirementNotMetError, match="not sent, now is"):
        Router({"m": late}, store).client("m").system_one(**choice("A", "B"))
    assert server.calls == 0


def test_stored_answers_outside_the_date_range_are_not_used(store: SQLiteStore, server: FakeServer) -> None:
    url = "http://m.fake.invalid"
    Router({"any": server.model("any", model="m", base_url=url)}, store).client("any").system_one(**choice("A", "B"))
    window = server.model("window", model="m", base_url=url, requirements_table={"request_date_range": PAST})
    with pytest.raises(RequirementNotMetError, match="not sent"):  # the stored answer is too recent, and so is now
        Router({"window": window}, store).client("window").system_one(**choice("A", "B"))
    assert server.calls == 1


def test_cache_off_records_but_never_serves(store: SQLiteStore, server: FakeServer) -> None:
    client = Router({"m": server.model("m", cache=False)}, store).client("m")
    client.system_one(**choice("A", "B"))
    client.system_one(**choice("A", "B"))
    assert server.calls == 2
    assert rows(store, "SELECT count(*) FROM observations") == [(2,)]


def test_errors_are_not_recorded_and_the_sdk_retries(store: SQLiteStore, server: FakeServer) -> None:
    client = Router({"m": server.model("m", max_retries=1)}, store).client("m")
    server.statuses = [503, 502, 502]
    with pytest.raises(TypeSafeInternalServerError):
        client.system_one(**choice("A", "B"))
    assert server.calls == 2  # the SDK's retry
    client.system_one(**choice("A", "B"))  # 502, retried, then answered
    assert server.calls == 4
    assert rows(store, "SELECT count(*) FROM observations") == [(1,)]


def test_a_response_that_answers_other_questions_is_not_recorded(store: SQLiteStore, server: FakeServer) -> None:
    server.wrong = True
    Router({"m": server.model("m")}, store).client("m").system_one(**choice("A", "B"))
    assert rows(store, "SELECT count(*) FROM observations") == [(0,)]


@pytest.mark.parametrize(
    "headers",
    [
        {"content-type": "application/json", "content-encoding": "zstd"},  # compressed
        {"content-type": "multipart/form-data; boundary=x"},  # with assets
    ],
)
def test_compressed_and_multipart_requests_pass_through_unrecorded(
    store: SQLiteStore, server: FakeServer, headers: dict[str, str]
) -> None:
    passed = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        passed.append(request)
        return httpx2.Response(200, json={})

    gateway = GatewayTransport(server.model("m"), store, transport=httpx2.MockTransport(handler))
    request = httpx2.Request("POST", "http://m.invalid/v1/systemone", headers=headers, content=b"not json")
    assert gateway.handle_request(request).status_code == 200
    assert passed == [request]
    assert rows(store, "SELECT count(*) FROM requests") == [(0,)]


def test_other_endpoints_pass_through(store: SQLiteStore) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"models": [{"name": "m", "description": "d", "release_date": "2026-01-01"}]})

    model = Model(name="m", backend="uniform", transport=httpx2.MockTransport(handler))
    client = Router({"m": model}, store).client("m")
    assert [m.name for m in client.models.list().models] == ["m"]
    assert rows(store, "SELECT count(*) FROM requests") == [(0,)]


def test_async(store: SQLiteStore, server: FakeServer) -> None:
    router = Router({"m": server.model("m")}, store, project="web")

    async def run() -> None:
        async with router.async_client("m") as client:
            with labels(page="ask"):
                await client.system_one(**choice("A", "B"))
                await client.system_one(**choice("A", "B"))

    asyncio.run(run())
    assert server.calls == 1
    assert rows(store, "SELECT project, hit, labels FROM requests ORDER BY at") == [
        ("web", 0, '{"page":"ask"}'),
        ("web", 1, '{"page":"ask"}'),
    ]


def test_uniform(store: SQLiteStore) -> None:
    client = Router({"u": Model(name="u", backend="uniform")}, store).client("u")
    r = client.system_one(**choice("A", "B", "C"))
    assert r.model == "uniform"
    assert r.choices["pick"].probabilities["B"] == pytest.approx(1 / 3)


def test_unknown_model_and_missing_key(store: SQLiteStore) -> None:
    router = Router({"jev": Model(name="jev", backend="openrouter", key_env="NO_SUCH_KEY")}, store)
    with pytest.raises(KeyError, match="unknown model"):
        router.client("nope")
    with pytest.raises(Exception, match="NO_SUCH_KEY"):
        router.client("jev")


def test_a_custom_retry_policy_still_applies(store: SQLiteStore, server: FakeServer) -> None:
    client = Router({"m": server.model("m")}, store).client("m")
    server.statuses = [503]
    with pytest.raises(TypeSafeInternalServerError):
        client.system_one(**choice("A", "B"), retry=RetryPolicy(max_retries=0))
    assert server.calls == 1
