"""Anthropic's discrim-eval (explicit), and the request templates that put it to a decision model.

discrim-eval (https://huggingface.co/datasets/Anthropic/discrim-eval) has 70 decision
scenarios (a loan, a visa, a kidney transplant, ...), each written out for the same 135 people:
9 ages x 3 genders x 5 races. Only those words change between the versions of a scenario.

A pick question shows a model three of these versions side by side, as candidates A, B and C,
and asks which one should get the favorable decision. How it is asked is a template in
templates/<name>.json: a System One request (state and questions) with placeholders,

    {{candidate_A}}, {{candidate_B}}, ...   the scenario written out for each candidate
    {{question}}                            the scenario's question, naming no one (scenarios.json)

The candidates are the options of the template's one choice question. A new way of asking is
a new file; every request records the template's name and a hash of its text as labels, so
answers to different templates, or to different edits of one, stay apart in queries.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import urllib.request
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, NamedTuple

from decision_gateway import Gateway, SQLiteStore, config

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "explicit.jsonl"
URL = "https://huggingface.co/datasets/Anthropic/discrim-eval/resolve/main/explicit.jsonl"
TEMPLATES = HERE / "templates"

DATASET = "discrim-eval-explicit"  # the `dataset` label of every request built here
AGES = [20, 30, 40, 50, 60, 70, 80, 90, 100]
GENDERS = ["male", "female", "non-binary"]
RACES = ["white", "Black", "Asian", "Hispanic", "Native American"]
DIMENSIONS = {"age": [str(a) for a in AGES], "gender": GENDERS, "race": RACES}

PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class Person(NamedTuple):
    age: int
    gender: str
    race: str

    @property
    def key(self) -> str:
        """The case key the page uses: "30|male|white"."""
        return f"{self.age}|{self.gender}|{self.race}"

    @classmethod
    def from_key(cls, key: str) -> Person:
        parts = key.split("|")
        if len(parts) != len(DIMENSIONS) or any(v not in DIMENSIONS[d] for d, v in zip(DIMENSIONS, parts, strict=True)):
            raise LookupError(f"no case {key!r}: a key is age|gender|race, e.g. 60|male|white")
        return cls(int(parts[0]), parts[1], parts[2])

    def label(self) -> dict[str, Any]:
        return self._asdict()


def people(age: int) -> list[Person]:
    """The 15 people of one age."""
    return [Person(age, g, r) for g in GENDERS for r in RACES]


def groups(age: int, size: int) -> list[tuple[Person, ...]]:
    """Every ordered group of `size` people of one age, the same person allowed more than once
    (as on the picks page, which draws from four copies of each player): 15^3 = 3,375 trios."""
    return list(itertools.product(people(age), repeat=size))


# ---- the dataset ----


@cache
def texts() -> dict[tuple[int, Person], str]:
    """(scenario, person) -> the scenario written out for that person. Downloads the dataset
    to data/ the first time."""
    if not DATA.exists():
        DATA.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(URL, DATA)
    out = {}
    with DATA.open() as f:
        for line in f:
            item = json.loads(line)
            person = Person(int(item["age"]), item["gender"], item["race"])
            out[(int(item["decision_question_id"]), person)] = item["filled_template"]
    return out


@cache
def scenarios() -> dict[int, str]:
    """Scenario id -> its question, naming no one, for the scenarios that are asked.
    Two are left out (blocked in scenarios.json): there "yes" is the unfavorable decision."""
    meta = json.loads((HERE / "scenarios.json").read_text())
    return {
        int(k): v["short_summary"] for k, v in sorted(meta.items(), key=lambda kv: int(kv[0])) if not v.get("blocked")
    }


def text(scenario: int, person: Person) -> str:
    return texts()[(scenario, person)]


def marked(scenario: int, person: Person) -> str:
    """The case as markdown, the words that change with the person in **bold**: found by
    comparing it with the same scenario written for someone different in all three."""
    import difflib  # noqa: PLC0415 (only the page needs it)

    a = text(scenario, person)
    other = Person(
        next(x for x in AGES if x != person.age),
        next(x for x in GENDERS if x != person.gender),
        next(x for x in RACES if x != person.race),
    )
    words = [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S+", a)]
    sm = difflib.SequenceMatcher(None, [w[2] for w in words], re.findall(r"\S+", text(scenario, other)), autojunk=False)
    out, at = "", 0
    for op, i1, i2, _, _ in sm.get_opcodes():
        if op != "equal" and i2 > i1:
            start, end = words[i1][0], words[i2 - 1][1]
            out += _md(a[at:start]) + "**" + _md(a[start:end]) + "**"
            at = end
    return out + _md(a[at:])


def _md(s: str) -> str:
    """Plain text as markdown that shows it as it is (the texts have stray <tags> and [brackets])."""
    return re.sub(r"([\\`*_\[\]<>#])", r"\\\1", s)


# ---- templates ----


@dataclass(frozen=True)
class Template:
    """A way of asking a pick question: templates/<name>.json."""

    name: str
    body: dict[str, Any]  # state and questions, with placeholders
    sha: str  # of the file's text, so an edited template is told apart in the labels

    @classmethod
    def load(cls, path: Path) -> Template:
        raw = path.read_text()
        body = json.loads(raw)
        template = cls(path.stem, body, hashlib.sha256(raw.encode()).hexdigest()[:12])
        template.check()
        return template

    @property
    def question(self) -> str:
        """The name of its one choice question."""
        (name,) = self.body["questions"]
        return str(name)

    @property
    def letters(self) -> list[str]:
        """The candidates: the options of the choice question."""
        return list(self.body["questions"][self.question]["criteria"])

    def check(self) -> None:
        questions = self.body.get("questions", {})
        if set(self.body) != {"state", "questions"} or len(questions) != 1:
            raise ValueError(f"template {self.name}: needs state and exactly one question")
        if next(iter(questions.values())).get("type") != "choice":
            raise ValueError(f"template {self.name}: the question must be a choice between the candidates")
        known = {"question"} | {f"candidate_{letter}" for letter in self.letters}
        used = set(PLACEHOLDER.findall(json.dumps(self.body)))
        if used - known:
            raise ValueError(
                f"template {self.name}: unknown placeholders {sorted(used - known)}; known: {sorted(known)}"
            )
        if missing := {f"candidate_{letter}" for letter in self.letters} - used:
            raise ValueError(f"template {self.name}: candidates never shown: {sorted(missing)}")

    def render(self, scenario: int, group: tuple[Person, ...]) -> dict[str, Any]:
        """system_one arguments (state, questions) for these candidates, in order."""
        if len(group) != len(self.letters):
            raise ValueError(f"template {self.name} takes {len(self.letters)} candidates, not {len(group)}")
        values = {"question": scenarios()[scenario]}
        values |= {f"candidate_{letter}": text(scenario, p) for letter, p in zip(self.letters, group, strict=True)}
        return _fill(self.body, values)

    def instructions(self, scenario: int) -> str:
        """What the model is told, with the scenario's question filled in."""
        q = self.body["questions"][self.question]["instructions"]
        return str(_fill(q, {"question": scenarios()[scenario]}))

    def label(self, scenario: int, group: tuple[Person, ...], source: str) -> dict[str, Any]:
        """The labels of a request: what it asks in the dataset's terms, for queries later."""
        return {
            "dataset": DATASET,
            "template": self.name,
            "template_sha": self.sha,
            "scenario": scenario,
            "candidates": {letter: p.label() for letter, p in zip(self.letters, group, strict=True)},
            "source": source,
        }

    def probabilities(self, answers: dict[str, Any]) -> list[float]:
        """The probability of each candidate, in order, rescaled to add up to 1."""
        probs = answers[self.question]["probabilities"]
        total = sum(probs.get(letter, 0.0) for letter in self.letters) or 1.0
        return [probs.get(letter, 0.0) / total for letter in self.letters]


@cache
def templates() -> dict[str, Template]:
    """The templates in templates/, by name."""
    return {t.name: t for t in map(Template.load, sorted(TEMPLATES.glob("*.json"), key=lambda p: p.stem))}


def template(name: str) -> Template:
    if name not in templates():
        raise LookupError(f"no template {name!r}; there are {', '.join(templates())}")
    return templates()[name]


def _fill(value: Any, values: dict[str, str]) -> Any:  # noqa: ANN401 (any JSON value)
    if isinstance(value, str):
        return PLACEHOLDER.sub(lambda m: values[m.group(1)], value)
    if isinstance(value, dict):
        return {k: _fill(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, values) for v in value]
    return value


# ---- the gateway ----

MODELS = HERE / "models.toml"


def gateway(store: str | Path | None = None, *, cache_only: bool = False, **labels: Any) -> Gateway:  # noqa: ANN401
    """The gateway over models.toml and the store (default: the gateway's own default store,
    $DECISION_GATEWAY_STORE or the user's data directory)."""
    models = config.load(MODELS)
    return Gateway(models, SQLiteStore(store) if store else SQLiteStore(), labels=labels, cache_only=cache_only)
