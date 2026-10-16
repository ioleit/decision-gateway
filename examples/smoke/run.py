"""The smoke test as a walk-through: ask 5 yes/no questions, look at them with the query tool,
load 5 more from a golden export, look again, and check that nothing is asked twice.

    python examples/smoke/run.py                  # uniform, no network
    python examples/smoke/run.py --model jev      # OpenRouter; needs OPENROUTER_API_KEY
    python examples/smoke/run.py --cache my.sqlite  # keep the cache (default: a temporary one)
"""

import argparse
import tempfile
from pathlib import Path

from common import HERE, LIVE, QUESTIONS, labels, request, router
from decision_router import query
from decision_router.cache.preheat import preheat

PER_QUESTION = """
    SELECT CAST(l.labels->>'id' AS INT)           AS id,
           l.labels->>'origin'                    AS origin,
           a.model,
           round(CAST(a.response->'answers'->'q'->>'noul' AS DOUBLE), 3) AS p_yes,
           a.response->'answers'->'q'->>'failed'  AS failed,
           a.cost,
           a.asked_at
    FROM answers a JOIN labels l USING (key)
    WHERE (l.labels->>'example') = 'smoke'
    ORDER BY id"""

SUMMARY = """
    SELECT l.labels->>'origin'   AS origin,
           a.model,
           count(*)              AS answers,
           round(avg(CAST(a.response->'answers'->'q'->>'noul' AS DOUBLE)), 3) AS mean_p_yes,
           count(*) FILTER (WHERE CAST(a.response->'answers'->'q'->>'noul' AS DOUBLE) > 0.5) AS yes,
           round(sum(a.cost), 6) AS cost
    FROM answers a JOIN labels l USING (key)
    WHERE (l.labels->>'example') = 'smoke'
    GROUP BY ALL ORDER BY origin"""


def show(cache_path, title):
    print(f"\n== {title}")
    con = query.connect(cache_path)  # a fresh read-only view of the cache, no model is asked
    con.sql(PER_QUESTION).show()
    con.sql(SUMMARY).show()
    con.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="uniform")
    p.add_argument("--cache", help="cache file (default: a new temporary one)")
    args = p.parse_args()
    tmp = None if args.cache else tempfile.TemporaryDirectory()
    cache_path = Path(args.cache or Path(tmp.name) / "cache.sqlite")
    r = router(cache_path)

    # 1. Ask questions 1-5. Each is asked once; a second run against the same cache asks nothing.
    before = r.cache.counts()[0]
    for q in LIVE:
        r.ask(args.model, request(q), labels=labels(q, "live"))
    print(f"1. asked {args.model} {r.cache.counts()[0] - before} new question(s) of {len(LIVE)}")
    show(cache_path, "after asking questions 1-5")

    # 2. Load questions 6-10 from the golden export: answered elsewhere, served from here on.
    golden = HERE / "golden" / args.model
    if not golden.is_dir():
        raise SystemExit(f"no golden/{args.model}/: make it with make_golden.py --model {args.model}")
    added, label_rows = preheat(golden, r.cache)
    print(f"\n2. preheated {added} answer(s) and {label_rows} label row(s) from golden/{args.model}/")
    show(cache_path, "after preheating questions 6-10")

    # 3. All 10 again: every one is a cache hit, so the model is not asked at all.
    before = r.cache.counts()[0]
    missing = [q["id"] for q in QUESTIONS if r.cached(args.model, request(q)) is None]
    for q in QUESTIONS:
        r.ask(args.model, request(q))
    asked = r.cache.counts()[0] - before
    print(f"\n3. all {len(QUESTIONS)} again: {asked} new question(s) asked; not in the cache before: {missing or 'none'}")
    if tmp:
        r.cache.close()
        tmp.cleanup()
    return 1 if asked else 0


if __name__ == "__main__":
    raise SystemExit(main())
