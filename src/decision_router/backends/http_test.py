"""The HTTP / OpenRouter backend against a local server that replays recorded reply shapes."""

import json
import re
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from decision_router import Cache, Router
from decision_router.backends import JSONObject, OpenRouter
from decision_router.backends.http import HTTP, MissingKeyError, TransientError
from decision_router.requirements import RequirementNotMetError
from decision_router.testing import choice

# The shape of an OpenRouter answer from typesafe/jev-1.13.
SERVED = "typesafe/jev-1.13-20260917"


def answer(body: JSONObject, model: str = SERVED) -> JSONObject:
    return {
        "answers": {
            n: {"type": "choice", "choice": "A", "confidence": 0.62, "probabilities": {"A": 0.75, "B": 0.25}}
            for n in body["questions"]
        },
        "id": "gen-dec-1",
        "model": model,
        "provider": "TypeSafe",
        "usage": {"cost": 3.1752e-05, "input_tokens": 756, "output_tokens": 38},
    }


Reply = tuple[int, JSONObject | Callable[[JSONObject], JSONObject]]  # status, body or body(request)


class Server:
    def __init__(self) -> None:
        self.requests: list[JSONObject] = []
        self.replies: list[Reply] = []  # answered in order; then answer(request)
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                server.requests.append({"body": body, "auth": self.headers.get("Authorization")})
                status, reply = server.replies.pop(0) if server.replies else (200, answer(body))
                data = json.dumps(reply(body) if callable(reply) else reply).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002 (the base class names it)
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/api/v1/systemone"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def server() -> Iterator[Server]:
    s = Server()
    yield s
    s.httpd.shutdown()
    s.httpd.server_close()


@pytest.fixture
def jev(server: Server, monkeypatch: pytest.MonkeyPatch) -> OpenRouter:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    return OpenRouter(
        "jev",
        {
            "url": server.url,
            "model": "typesafe/jev-1.13",
            "provider": {"only": ["typesafe"], "allow_fallbacks": False},
            "requirements": {"systemone_response_model_id": SERVED, "openrouter_response_provider": "TypeSafe"},
            "retries": 2,
        },
    )


def test_wire_and_provenance(server: Server, jev: OpenRouter, cache: Cache) -> None:
    router = Router({"jev": jev}, cache)
    r = router.ask("jev", choice("A", "B"))
    sent = server.requests[0]
    assert sent["auth"] == "Bearer test-key"
    assert sent["body"]["model"] == "typesafe/jev-1.13"
    assert sent["body"]["provider"] == {"only": ["typesafe"], "allow_fallbacks": False}
    assert r["model"] == SERVED
    row = cache.con.execute("SELECT wire IS NOT NULL, cost, provenance, raw FROM answers").fetchone()
    assert row == (1, 3.1752e-05, '{"generation":"gen-dec-1","provider":"TypeSafe"}', None)
    router.ask("jev", choice("A", "B"))
    assert len(server.requests) == 1


def test_wire(jev: OpenRouter) -> None:
    # the request as sent: the upstream model id, the caller's fields, the provider pin
    expected = {
        "model": "typesafe/jev-1.13",
        "state": {"case": 1},
        "questions": {"pick": {"type": "choice", "criteria": {"A": "A", "B": "B"}}},
        "provider": {"only": ["typesafe"], "allow_fallbacks": False},
    }
    assert jev.wire({**choice("A", "B"), "model": "jev"}) == expected


def test_an_answer_from_another_model_is_not_stored(server: Server, jev: OpenRouter, cache: Cache) -> None:
    server.replies.append((200, lambda body: answer(body, model="typesafe/jev-1.14-20261101")))
    with pytest.raises(RequirementNotMetError, match=re.escape("served by 'typesafe/jev-1.14-20261101'")):
        Router({"jev": jev}, cache).ask("jev", choice("A", "B"))
    assert cache.counts() == (0, 0)


REFUSAL = (502, {"error": {"message": 'OpenAI refused to answer question "pick"'}})


def test_refusal_is_a_cached_failed_answer(server: Server, cache: Cache, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    plain = OpenRouter("plain", {"url": server.url, "model": "typesafe/jev-1.13"})
    server.replies.append(REFUSAL)
    r = Router({"plain": plain}, cache).ask("plain", choice("A", "B"))
    assert r["answers"]["pick"]["failed"].startswith("refusal: OpenAI refused")
    assert cache.counts()[0] == 1


def test_a_refusal_does_not_meet_a_model_id_requirement(server: Server, jev: OpenRouter, cache: Cache) -> None:
    # a refusal names no model that answered, so it cannot be stored under a model id requirement
    server.replies.append(REFUSAL)
    with pytest.raises(RequirementNotMetError, match=re.escape("served by 'typesafe/jev-1.13'")):
        Router({"jev": jev}, cache).ask("jev", choice("A", "B"))
    assert cache.counts() == (0, 0)


def test_transient_errors_are_retried(
    server: Server, jev: OpenRouter, cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("decision_router.backends.http.time.sleep", lambda _seconds: None)
    server.replies.append((503, {"error": "busy"}))
    Router({"jev": jev}, cache).ask("jev", choice("A", "B"))
    assert len(server.requests) == 2
    server.replies += [(429, {}), (500, {})]
    with pytest.raises(TransientError):
        Router({"jev": jev}, cache).ask("jev", choice("A", "B", "C"))
    assert cache.counts()[0] == 1


def test_client_errors_are_not_retried(server: Server, jev: OpenRouter, cache: Cache) -> None:
    server.replies.append((400, {"error": "bad request"}))
    with pytest.raises(RuntimeError, match="HTTP 400"):
        Router({"jev": jev}, cache).ask("jev", choice("A", "B"))
    assert len(server.requests) == 1


def test_without_a_key_cached_answers_are_still_served(
    server: Server, jev: OpenRouter, cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    router = Router({"jev": jev}, cache)
    router.ask("jev", choice("A", "B"))
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert router.ask("jev", choice("A", "B"))["model"] == SERVED
    with pytest.raises(MissingKeyError, match="OPENROUTER_API_KEY"):
        router.ask("jev", choice("A", "B", "C"))
    assert len(server.requests) == 1


def test_plain_http_without_model_or_key(server: Server, cache: Cache) -> None:
    local = HTTP("local", {"url": server.url, "model": ""})
    Router({"local": local}, cache).ask("local", choice("A", "B"))
    assert "model" not in server.requests[0]["body"]
    assert server.requests[0]["auth"] is None


def test_unwrap(server: Server, cache: Cache) -> None:
    server.replies.append((200, lambda body: {"result": answer(body), "success": True}))
    cf = HTTP("cf", {"url": server.url, "unwrap": "result"})
    Router({"cf": cf}, cache).ask("cf", choice("A", "B"))
    raw = cache.con.execute("SELECT raw FROM answers").fetchone()[0]
    assert json.loads(raw)["success"] is True
