"""Export the answers a query selects."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import huggingface_hub
import pytest
from huggingface_hub.errors import RepositoryNotFoundError

from decision_router import Cache, Router, query
from decision_router.cache.export import PublicDatasetError, export, push
from decision_router.testing import choice

if TYPE_CHECKING:
    from pathlib import Path

QUESTIONS = [choice(*"ABCD"[:n], state={"case": c}) for n in (2, 3, 4) for c in range(5)]


def test_export_a_query_result(tmp_path: Path, router: Router, cache: Cache) -> None:
    for q in QUESTIONS:
        router.ask("fake", **q)
        router.ask("uniform", **q, labels={"keep": True})
    n = export(cache.path, tmp_path / "exp", keys="SELECT key FROM answers WHERE model = 'uniform'")
    assert n == (15, 15)
    con = query.connect(tmp_path / "exp")
    assert con.sql("SELECT DISTINCT model FROM answers").fetchall() == [("uniform",)]
    assert con.sql("SELECT count(*) FROM labels WHERE (labels->>'keep') = 'true'").fetchall() == [(15,)]


def not_found() -> RepositoryNotFoundError:
    """The hub's "no such repo" error, without the HTTP response its constructor wants."""
    error = RepositoryNotFoundError.__new__(RepositoryNotFoundError)
    Exception.__init__(error, "missing")
    return error


class FakeHub:
    """Stands in for huggingface_hub.HfApi: one dataset that is private, public, or missing."""

    def __init__(self, existing: str) -> None:  # "private", "public" or "missing"
        self.existing = existing
        self.created: list[bool] = []
        self.uploaded = 0

    def __call__(self) -> FakeHub:
        return self

    def repo_info(self, *_: object, **__: object) -> SimpleNamespace:
        if self.existing == "missing":
            raise not_found()
        return SimpleNamespace(private=self.existing == "private")

    def create_repo(self, *_: object, private: bool, **__: object) -> None:
        self.created.append(private)

    def upload_folder(self, *_: object, **__: object) -> str:
        self.uploaded += 1
        return "commit"


@pytest.mark.parametrize(
    "case",
    [
        ("missing", True, [True]),  # created private
        ("missing", False, [False]),  # --public: created public
        ("private", True, []),
        ("public", False, []),  # --public: may publish
        ("private", False, []),  # --public on a private dataset: stays private
    ],
)
def test_push_visibility(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: tuple[str, bool, list[bool]]) -> None:
    existing, private, created = case
    hub = FakeHub(existing)
    monkeypatch.setattr(huggingface_hub, "HfApi", hub)
    push(tmp_path, "someone/answers", private=private)
    assert hub.created == created
    assert hub.uploaded == 1


def test_push_refuses_an_existing_public_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hub = FakeHub("public")
    monkeypatch.setattr(huggingface_hub, "HfApi", hub)
    with pytest.raises(PublicDatasetError, match="public dataset"):
        push(tmp_path, "someone/answers")
    assert hub.uploaded == 0
