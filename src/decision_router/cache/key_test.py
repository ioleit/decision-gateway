"""The key format is frozen: these hashes must never change, or exported caches stop hitting."""

from decision_router.cache.key import canonical, key


def test_golden() -> None:
    wire = {
        "model": "uniform",
        "state": {"x": 1},
        "questions": {"q": {"type": "choice", "criteria": {"A": "a", "B": "b"}}},
    }
    assert key("uniform", {}, wire) == "db1d06a24d0f3d30b75f1707d2e330be9a0f7174510e47cd1f187d8cbc22ad56"
    assert (
        key("example", {"systemone_response_model_id": "org/model-20260101"}, {"state": "Zoë, 30", "questions": {}})
        == "e8cf9397467e1812933df9de159cf5afa383ecef53a7156628c31d485564d6f4"
    )


def test_order_of_fields_does_not_matter() -> None:
    assert key("m", {}, {"a": 1, "b": {"c": 2, "d": 3}}) == key("m", {}, {"b": {"d": 3, "c": 2}, "a": 1})


def test_model_requirements_and_wire_all_count() -> None:
    base = key("m", {}, {"a": 1})
    other_requirements = key("m", {"request_date_range": ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"]}, {"a": 1})
    assert len({base, key("m2", {}, {"a": 1}), other_requirements, key("m", {}, {"a": 2})}) == 4


def test_canonical() -> None:
    assert canonical({"b": 1, "a": "é"}) == '{"a":"é","b":1}'
