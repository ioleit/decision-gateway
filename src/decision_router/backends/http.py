"""Jev / SystemOne over HTTP: OpenRouter, or any endpoint that takes the request as its body.

Configured in models.toml (backend = "openrouter" or "http"); models.example.toml describes
every field, with examples.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from http import HTTPStatus

from .base import Backend, JSONObject, Reply

OPENROUTER_URL = "https://openrouter.ai/api/v1/systemone"


class TransientError(Exception):
    """A failure worth retrying: HTTP 429 or 5xx, a timeout, a dropped connection."""


class MissingKeyError(Exception):
    """The API key (or a variable in the url) is not in the environment."""


class HTTP(Backend):
    default_url: str | None = None
    default_key_env = ""

    def __init__(self, name: str, entry: JSONObject | None = None, timeout: float = 900, retries: int = 3) -> None:
        super().__init__(name, entry)
        self.timeout: float = self.entry.get("timeout", timeout)
        self.retries: int = self.entry.get("retries", retries)  # attempts per call; 1 = no retry
        self.upstream: str = self.entry.get("model", name)  # "" : the server takes no model field

    def wire(self, request: JSONObject) -> JSONObject:
        body = {k: v for k, v in request.items() if k != "model"}
        if self.upstream:
            body = {"model": self.upstream, **body}
        if "provider" in self.entry:
            body["provider"] = self.entry["provider"]
        return body

    def _url_and_headers(self) -> tuple[str, dict[str, str]]:
        url: str | None = self.entry.get("url", self.default_url)
        if not url:
            raise ValueError(f"{self.name}: no url")
        if not url.startswith(("https://", "http://")):
            raise ValueError(f"{self.name}: url must be http(s), not {url!r}")
        env = {**self.entry.get("env_defaults", {}), **os.environ}
        missing = [v for v in re.findall(r"\{(\w+)\}", url) if not env.get(v)]
        key_env: str = self.entry.get("key_env", self.default_key_env)
        if key_env and not os.environ.get(key_env):
            missing.append(key_env)
        if missing:
            raise MissingKeyError(f"{self.name} needs {', '.join(missing)} in the environment to ask new questions")
        headers = {"Content-Type": "application/json"}
        if key_env:
            headers["Authorization"] = f"Bearer {os.environ[key_env]}"
        return url.format_map(env), headers

    def call(self, wire: JSONObject, request: JSONObject) -> Reply:
        raw = self._post_with_retries(*self._url_and_headers(), wire)
        if "refusal" in raw:  # the model's answer: stored as failed answers
            why = raw["refusal"].get("message") if isinstance(raw["refusal"], dict) else raw["refusal"]
            response = {
                "model": wire.get("model"),
                "answers": {
                    n: {"type": q.get("type", "choice"), "failed": f"refusal: {why}"}
                    for n, q in wire["questions"].items()
                },
            }
            return Reply(response, raw=raw)
        wrapper = self.entry.get("unwrap")
        response = raw[wrapper] if wrapper else raw
        usage = response.get("usage") or {}
        provenance = {
            k: v for k, v in (("generation", response.get("id")), ("provider", response.get("provider"))) if v
        }
        return Reply(response, raw=raw if wrapper else None, cost=usage.get("cost"), provenance=provenance or None)

    def _post_with_retries(self, url: str, headers: dict[str, str], wire: JSONObject) -> JSONObject:
        for attempt in range(1, self.retries):
            try:
                return self._post(url, headers, wire)
            except TransientError:
                time.sleep(2 ** (attempt - 1))
        return self._post(url, headers, wire)  # the last attempt raises

    def _post(self, url: str, headers: dict[str, str], wire: JSONObject) -> JSONObject:
        req = urllib.request.Request(url, json.dumps(wire).encode(), headers, method="POST")  # noqa: S310 (http(s) checked)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 (http(s) checked)
                reply: JSONObject = json.load(r)
                return reply
        except urllib.error.HTTPError as e:
            with e:  # an HTTPError holds the open response
                text = e.read().decode(errors="replace")
            # A refusal is an answer. OpenRouter reports one as an HTTP error whose body says
            # so, e.g. 502 {"error": {"message": "... refused to answer question \"q\""}}.
            if "refused to answer" in text:
                try:
                    return {"refusal": json.loads(text).get("error", text), "http_status": e.code}
                except ValueError:
                    return {"refusal": text, "http_status": e.code}
            transient = e.code == HTTPStatus.TOO_MANY_REQUESTS or e.code >= HTTPStatus.INTERNAL_SERVER_ERROR
            error: type[Exception] = TransientError if transient else RuntimeError
            raise error(f"{self.name}: HTTP {e.code}: {text[:300]}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise TransientError(f"{self.name}: {type(e).__name__}: {e}") from e


class OpenRouter(HTTP):
    default_url = OPENROUTER_URL
    default_key_env = "OPENROUTER_API_KEY"
