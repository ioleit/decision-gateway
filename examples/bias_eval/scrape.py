"""Ask decision models the picks page's questions, so that the page and the report have answers.

A scrape is one or more models x templates x scenarios at one age: for each scenario every
ordered trio of the 15 people of that age (3 genders x 5 races, the same person allowed more
than once): 3,375 questions per scenario, model and template. That is what the page needs to
show a scenario without misses. Named scrapes are in scrapes.toml; options override them.

What is stored already is not asked again (the gateway answers it from the store), so a scrape
can be stopped and run again. --dry-run asks nothing: it counts what is stored and what would
be asked, and estimates the cost from what the model's stored answers cost.

    python scrape.py loan-87 --dry-run
    python scrape.py loan-87 --models uniform
    python scrape.py --models clef-flash --scenarios 87 --templates pick-one --sample 20

OpenRouter models need OPENROUTER_API_KEY in the environment.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
import tomllib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import discrim
from typesafe_sdk import TypeSafeError

from decision_gateway import CacheMissError, ConstraintViolatedError, Gateway, labels

if TYPE_CHECKING:
    from decision_gateway import SQLiteStore

SCRAPES = discrim.HERE / "scrapes.toml"

Job = tuple[dict[str, Any], dict[str, Any]]  # system_one arguments, labels


@dataclass
class Counts:
    questions: int = 0
    stored: int = 0
    asked: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def jobs(template: discrim.Template, scenarios: list[int], age: int, source: str) -> list[Job]:
    return [
        (template.render(s, group), template.label(s, group, source))
        for s in scenarios
        for group in discrim.groups(age, len(template.letters))
    ]


async def run(gateway: Gateway, model: str, todo: list[Job], workers: int, counts: Counts | None = None) -> list[Job]:
    """Ask each job once; with a cache-only gateway, only look it up. Returns the jobs that
    have no answer (with cache only: the ones not stored)."""
    counts = counts or Counts()
    missing: list[Job] = []
    gate = asyncio.Semaphore(workers)
    done, t0 = 0, time.monotonic()

    async def one(job: Job) -> None:
        nonlocal done
        arguments, label = job
        async with gate:
            try:
                with labels(**label):
                    await client.system_one(**arguments)
            except CacheMissError:
                missing.append(job)
            except (ConstraintViolatedError, TypeSafeError) as e:
                missing.append(job)
                counts.failed += 1
                counts.errors.append(f"{type(e).__name__}: {e}")
        done += 1
        if not gateway.cache_only and done % 200 == 0:
            print(f"  {done:,}/{len(todo):,} in {time.monotonic() - t0:.0f} s", file=sys.stderr, flush=True)

    async with gateway.async_client(model) as client:
        await asyncio.gather(*(one(j) for j in todo))
    return missing


def cost_per_question(store: SQLiteStore, model: str, template: str) -> float | None:
    """The mean cost of this model's stored answers to this template (OpenRouter reports
    usage.cost), or None if none has a cost."""
    (cost,) = store.con.execute(
        "SELECT avg(o.cost) FROM requests r JOIN observations o ON o.id = r.observation "
        "WHERE r.model = ? AND r.accepted AND NOT r.hit AND o.cost IS NOT NULL "
        "AND json_extract(r.labels, '$.template') = ?",
        (model, template),
    ).fetchone()
    return cost


def arguments() -> tuple[argparse.Namespace, dict[str, Any]]:
    """The command line, and the scrape it describes: the named one with the options over it."""
    named = tomllib.loads(SCRAPES.read_text())
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("name", nargs="?", choices=list(named), help="a scrape in scrapes.toml")
    ap.add_argument("--models", help="comma list (default: the scrape's)")
    ap.add_argument("--templates", help="comma list of templates/ names (default: the scrape's)")
    ap.add_argument("--scenarios", help="comma list of scenario ids (default: the scrape's)")
    ap.add_argument("--age", type=int, choices=discrim.AGES, help="the age of every candidate (default: the scrape's)")
    ap.add_argument("--sample", type=int, help="only a random N of each model's questions (seeded), for a pilot")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, help="questions in flight per model (default: the scrape's, or 16)")
    ap.add_argument("--store", help="the decision store (default: the gateway's)")
    ap.add_argument("--dry-run", action="store_true", help="count and estimate; ask nothing")
    a = ap.parse_args()

    spec: dict[str, Any] = dict(named[a.name]) if a.name else {}
    for key in ("models", "templates", "scenarios"):
        if value := getattr(a, key):
            spec[key] = value.split(",")
    spec["age"] = a.age or spec.get("age", 30)
    if missing := [k for k in ("models", "templates", "scenarios") if k not in spec]:
        ap.error(f"name a scrape or give --{', --'.join(missing)}")
    spec["scenarios"] = [int(s) for s in spec["scenarios"]]
    for s in spec["scenarios"]:
        if s not in discrim.scenarios():
            ap.error(f"no scenario {s} (blocked or unknown)")
    spec["workers"] = a.workers or spec.get("workers", 16)
    return a, spec


def main() -> None:
    a, spec = arguments()
    scenarios = spec["scenarios"]
    templates = [discrim.template(t) for t in spec["templates"]]
    workers = spec["workers"]
    source = f"scrape:{a.name}" if a.name else "scrape"

    print(
        f"{a.name or 'scrape'}: {spec.get('about', '')}\nage {spec['age']}, scenarios {scenarios}, "
        f"templates {', '.join(t.name for t in templates)}\n",
        file=sys.stderr,
    )
    lookup = discrim.gateway(a.store, cache_only=True)
    ask = discrim.gateway(a.store)
    total = 0.0
    for model in spec["models"]:
        for template in templates:
            todo = jobs(template, scenarios, spec["age"], source)
            if a.sample and a.sample < len(todo):
                todo = random.Random(a.seed).sample(todo, a.sample)  # noqa: S311 (a pilot, not a secret)
            counts = Counts(questions=len(todo))
            missing = asyncio.run(run(lookup, model, todo, workers))
            counts.stored = len(todo) - len(missing)
            cost = cost_per_question(lookup.store, model, template.name)  # type: ignore[arg-type]
            estimate = cost * len(missing) if cost is not None else None
            total += estimate or 0.0
            if not a.dry_run and missing:
                left = asyncio.run(run(ask, model, missing, workers, counts))
                counts.asked = len(missing) - len(left)
            verb = "to ask" if a.dry_run else "asked"
            n_asked = len(missing) if a.dry_run else counts.asked
            money = f"~${estimate:.2f}" if estimate is not None else "cost unknown"
            print(
                f"{model:22} {template.name:14} {counts.questions:>7,} questions {counts.stored:>7,} stored before "
                f"{n_asked:>7,} {verb} {counts.failed:>5,} failed   {money if a.dry_run else ''}"
            )
            for error in sorted(set(counts.errors))[:5]:
                print(f"    {error}", file=sys.stderr)
    if a.dry_run:
        print(f"{'estimated cost':22} ~${total:.2f} (from each model's stored answers; unknown ones not counted)")


if __name__ == "__main__":
    main()
