import pytest
from typesafe_sdk import Box, Choice, Noul, Question, Score

from decision_router.backends import Uniform
from decision_router.systemone import parse_response, wire_questions


def test_every_question_type_gets_a_valid_uniform_answer() -> None:
    questions: dict[str, Question] = {
        "pick": Choice(criteria={"A": None, "B": "b", "C": None, "D": None}),
        "yes": Noul(instructions="Is it?"),
        "rate": Score(criteria=["low", "mid", "high"]),
        "find": Box(instructions="the dog"),
    }
    reply = Uniform("uniform").call({"questions": wire_questions(questions)}, {})
    r = parse_response(reply.response, questions)  # valid per the System One API

    assert r.choices["pick"].choice == "A"
    assert r.choices["pick"].probabilities == dict.fromkeys("ABCD", 0.25)
    assert r.choices["pick"].confidence == 0.25
    assert r.nouls["yes"].noul == 0.5
    assert r.scores["rate"].score == pytest.approx(1.0)  # the expected level: 0, 1 or 2 with 1/3 each
    assert r.scores["rate"].legend == {0: "low", 1: "mid", 2: "high"}
    assert r.boxes["find"].box.top == 0.0
    assert r.boxes["find"].box.bottom == 1.0
    assert reply.cost == 0.0
