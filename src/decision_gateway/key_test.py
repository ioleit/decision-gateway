"""The key format is frozen: these hashes must never change, or stored answers stop being found."""

from decision_gateway.key import canonical, key

OPENROUTER = "https://openrouter.ai/api/v1/systemone"
UNIFORM = "http://uniform.invalid/v1/systemone"


def test_golden() -> None:
    body = {
        "state": "Zoë, 30",
        "model": "typesafe/jev-1.13",
        "questions": {"q": {"type": "noul", "instructions": "x?"}},
        "provider": {"only": ["typesafe"], "allow_fallbacks": False},
    }
    assert key(OPENROUTER, body) == "0f093d48844de096c9018f71b0a5d90894f119e0ccf64685932de7c623bc4408"
    choice = {
        "state": {"x": 1},
        "model": "uniform",
        "questions": {"q": {"type": "choice", "criteria": {"A": "a", "B": "b"}}},
    }
    assert key(UNIFORM, choice) == "73ec6d16c078512a94896018a0b3efa66e61e8d11ad522a1665d8c0942a79bf5"
    with_asset = key(UNIFORM, {"state": 1, "model": "m", "questions": {}}, ["ab" * 32])
    assert with_asset == "b74d16691386acb32230a334186cca332c7650351b191f6feb3a6454f38f2a98"


def test_order_of_fields_does_not_matter() -> None:
    assert key(UNIFORM, {"a": 1, "b": {"c": 2, "d": 3}}) == key(UNIFORM, {"b": {"d": 3, "c": 2}, "a": 1})


def test_endpoint_body_and_assets_all_count() -> None:
    body = {"model": "m", "state": 1}
    keys = {
        key(UNIFORM, body),
        key(OPENROUTER, body),
        key(UNIFORM, {**body, "state": 2}),
        key(UNIFORM, body, ["ab" * 32]),
    }
    assert len(keys) == 4


def test_canonical() -> None:
    assert canonical({"b": 1, "a": "é"}) == '{"a":"é","b":1}'
