from decision_router.backends import Uniform


def test_answers_every_question_uniformly():
    wire = {"questions": {
        "pick": {"type": "choice", "criteria": {"A": "", "B": "", "C": "", "D": ""}},
        "list": {"type": "choice", "criteria": ["x", "y"]},
        "yes": {"type": "noul", "criteria": "is it?"},
        "rate": {"type": "score", "criteria": ["low", "mid", "high"]},
        "bare": {}}}
    r = Uniform("uniform").call(wire, wire)
    a = r.response["answers"]
    assert set(a) == set(wire["questions"])
    assert a["pick"]["probabilities"] == {o: 0.25 for o in "ABCD"} and a["pick"]["choice"] == "A"
    assert a["list"]["probabilities"] == {"x": 0.5, "y": 0.5}
    assert a["yes"] == {"type": "noul", "noul": 0.5, "probabilities": {"true": 0.5, "false": 0.5}}
    assert a["rate"]["score"] == "low" and len(a["rate"]["probabilities"]) == 3
    assert a["bare"]["probabilities"] == {"true": 0.5, "false": 0.5}
    assert r.cost == 0.0


def test_version():
    assert Uniform("uniform").version() == "uniform/1"
    assert Uniform("uniform", {"version": "uniform/2"}).version() == "uniform/2"
