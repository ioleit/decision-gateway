"""Helpers for testing code that uses the gateway, without a network or a real model.

    from decision_gateway.testing import FakeTransport, choice

See transports/fake_transport.py.
"""

from __future__ import annotations

from typing import Any

from decision_gateway.transports.fake_transport import FakeTransport

__all__ = ["FakeTransport", "choice"]


def choice(*options: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """system_one arguments: one choice question, "pick", between the given options."""
    return {
        "state": state or {"case": 1},
        "questions": {"pick": {"type": "choice", "criteria": {o: o for o in options}}},
    }
