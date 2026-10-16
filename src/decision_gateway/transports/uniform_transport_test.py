import pytest
from typesafe_sdk import Box, Choice, Noul, Score

from decision_gateway import Gateway, ModelConfig, SQLiteStore
from decision_gateway.transports.uniform_transport import respond


def test_every_question_type_gets_a_valid_answer_through_the_sdk(store: SQLiteStore) -> None:
    client = Gateway({"u": ModelConfig(name="u", backend="uniform")}, store).client("u")
    r = client.system_one(
        state="s",
        questions={
            "pick": Choice(criteria={"A": None, "B": "b", "C": None, "D": None}),
            "yes": Noul(instructions="Is it?"),
            "rate": Score(criteria=["low", "mid", "high"]),
            "find": Box(instructions="the dog"),
        },
    )
    assert r.choices["pick"].choice == "A"
    assert r.choices["pick"].probabilities == dict.fromkeys("ABCD", 0.25)
    assert r.nouls["yes"].noul == 0.5
    assert r.scores["rate"].score == pytest.approx(1.0)  # the expected level: 0, 1 or 2 with 1/3 each
    assert r.scores["rate"].legend == {0: "low", 1: "mid", 2: "high"}
    assert r.boxes["find"].box.bottom == 1.0


def test_respond() -> None:
    body = {"model": "x", "questions": {"q": {"type": "noul", "instructions": "?"}}}
    assert respond(body) == {
        "model": "uniform",
        "answers": {"q": {"type": "noul", "noul": 0.5}},
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }
