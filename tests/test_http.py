"""The HTTP / OpenRouter backend against a local server that replays recorded reply shapes."""

import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from conftest import choice
from decision_router import Router
from decision_router.backends import OpenRouter
from decision_router.backends.http import HTTP, MissingKey, ModelChanged, NotPinned, Transient

# The shape of an OpenRouter answer from typesafe/jev-1.13.
SERVED = "typesafe/jev-1.13-20260917"


def answer(body, model=SERVED):
    return {"answers": {n: {"type": "choice", "choice": "A", "confidence": 0.62,
                            "probabilities": {"A": 0.75, "B": 0.25}} for n in body["questions"]},
            "id": "gen-dec-1", "model": model, "provider": "TypeSafe",
            "usage": {"cost": 3.1752e-05, "input_tokens": 756, "output_tokens": 38}}


class Server:
    def __init__(self):
        self.requests, self.replies = [], []  # replies: (status, body) or a callable(body) -> body
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                server.requests.append({"body": body, "auth": self.headers.get("Authorization")})
                status, reply = server.replies.pop(0) if server.replies else (200, answer(body))
                data = json.dumps(reply(body) if callable(reply) else reply).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/api/v1/systemone"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def server():
    s = Server()
    yield s
    s.httpd.shutdown()


@pytest.fixture
def jev(server, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    return OpenRouter("jev", {"url": server.url, "model": "typesafe/jev-1.13",
                              "provider": {"only": ["typesafe"], "allow_fallbacks": False},
                              "version": f"openrouter:{SERVED}@typesafe", "served": SERVED, "retries": 2})


def test_wire_and_provenance(server, jev, cache):
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


def test_wire(jev):
    # the request as sent: the upstream model id, the caller's fields, the provider pin
    expected = {"model": "typesafe/jev-1.13", "state": {"case": 1},
                "questions": {"pick": {"type": "choice", "criteria": {"A": "A", "B": "B"}}},
                "provider": {"only": ["typesafe"], "allow_fallbacks": False}}
    assert jev.wire({**choice("A", "B"), "model": "jev"}) == expected


def test_another_model_answering_is_not_cached(server, jev, cache):
    server.replies.append((200, lambda body: answer(body, model="typesafe/jev-1.14-20261101")))
    with pytest.raises(ModelChanged):
        Router({"jev": jev}, cache).ask("jev", choice("A", "B"))
    assert cache.counts() == (0, 0)


def test_refusal_is_a_cached_failed_answer(server, jev, cache):
    server.replies.append((502, {"error": {"message": 'OpenAI refused to answer question "pick"'}}))
    r = Router({"jev": jev}, cache).ask("jev", choice("A", "B"))
    assert r["answers"]["pick"]["failed"].startswith("refusal: OpenAI refused")
    assert cache.counts()[0] == 1


def test_transient_errors_are_retried(server, jev, cache, monkeypatch):
    monkeypatch.setattr("decision_router.backends.http.time.sleep", lambda s: None)
    server.replies.append((503, {"error": "busy"}))
    Router({"jev": jev}, cache).ask("jev", choice("A", "B"))
    assert len(server.requests) == 2
    server.replies += [(429, {}), (500, {})]
    with pytest.raises(Transient):
        Router({"jev": jev}, cache).ask("jev", choice("A", "B", "C"))
    assert cache.counts()[0] == 1


def test_client_errors_are_not_retried(server, jev, cache):
    server.replies.append((400, {"error": "bad request"}))
    with pytest.raises(RuntimeError, match="HTTP 400"):
        Router({"jev": jev}, cache).ask("jev", choice("A", "B"))
    assert len(server.requests) == 1


def test_without_a_key_cached_answers_are_still_served(server, jev, cache, monkeypatch):
    router = Router({"jev": jev}, cache)
    router.ask("jev", choice("A", "B"))
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert router.ask("jev", choice("A", "B"))["model"] == SERVED
    with pytest.raises(MissingKey, match="OPENROUTER_API_KEY"):
        router.ask("jev", choice("A", "B", "C"))
    assert len(server.requests) == 1


def test_unpinned_window(server, monkeypatch, cache):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    now = datetime.now(timezone.utc)
    entry = {"url": server.url, "model": "example/undated", "version": "undated run 1"}
    fresh = OpenRouter("undated", {**entry, "unpinned": now.isoformat()})
    old = OpenRouter("undated", {**entry, "unpinned": (now - timedelta(hours=25)).isoformat()})
    Router({"undated": fresh}, cache).ask("undated", choice("A", "B"))
    stale = Router({"undated": old}, cache)
    assert stale.ask("undated", choice("A", "B"))["model"] == SERVED  # cached: still served
    with pytest.raises(NotPinned):
        stale.ask("undated", choice("A", "B", "C"))


def test_plain_http_without_model_or_key(server, cache):
    local = HTTP("local", {"url": server.url, "model": "", "version": "org/repo@abc"})
    Router({"local": local}, cache).ask("local", choice("A", "B"))
    assert "model" not in server.requests[0]["body"] and server.requests[0]["auth"] is None


def test_unwrap(server, cache):
    server.replies.append((200, lambda body: {"result": answer(body), "success": True}))
    cf = HTTP("cf", {"url": server.url, "version": "v", "unwrap": "result"})
    Router({"cf": cf}, cache).ask("cf", choice("A", "B"))
    raw = cache.con.execute("SELECT raw FROM answers").fetchone()[0]
    assert json.loads(raw)["success"] is True
