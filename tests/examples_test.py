"""The examples run as documented."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def test_smoke_example() -> None:
    out = subprocess.run(
        [sys.executable, str(ROOT / "examples/smoke/run.py")], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    assert "1. asked uniform 5 new question(s) of 5" in out.stdout
    assert "2. preheated 5 answer(s)" in out.stdout
    assert "3. all 10 again: 0 new question(s) asked" in out.stdout


def test_jev_golden_serves_without_a_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real Jev answers (asked 2026-10-16), preheated: served with no key and no network."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.syspath_prepend(str(ROOT / "examples/smoke"))
    from common import GOLDEN, HERE, request, router

    from decision_router import Cache
    from decision_router.cache.preheat import preheat

    with Cache(tmp_path / "cache.sqlite") as cache:
        r = router(cache)
        assert preheat(HERE / "golden" / "jev", cache) == (5, 5)
        for q in GOLDEN:
            response = r.ask("jev", **request(q)).response
            assert response is not None
            assert response.model == "typesafe/jev-1.13-20260917"
