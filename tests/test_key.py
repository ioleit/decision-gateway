"""The key format is frozen: these hashes must never change, or exported caches stop hitting."""

from decision_router.cache.key import canonical, key


def test_golden():
    wire = {"model": "uniform", "state": {"x": 1}, "questions": {"q": {"type": "choice", "criteria": {"A": "a", "B": "b"}}}}
    assert key("uniform", "uniform/1", wire) == "cab41fbb9da231804a12653f40da683b9e95b370a1cddaab6ac9dbabcb07d051"
    assert key("example", "org/model@0123abc", {"state": "Zoë, 30", "questions": {}}) == \
        "8df436cafb18906e6442768375ea7879a4f94bb8ed9841b50571a186ca9f6522"


def test_order_of_fields_does_not_matter():
    assert key("m", "v", {"a": 1, "b": {"c": 2, "d": 3}}) == key("m", "v", {"b": {"d": 3, "c": 2}, "a": 1})


def test_model_version_and_wire_all_count():
    base = key("m", "v", {"a": 1})
    assert len({base, key("m2", "v", {"a": 1}), key("m", "v2", {"a": 1}), key("m", "v", {"a": 2})}) == 4


def test_canonical():
    assert canonical({"b": 1, "a": "é"}) == '{"a":"é","b":1}'
