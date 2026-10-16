"""decision-gateway query | export | preheat

    decision-gateway query "SELECT model, count(*) FROM answers GROUP BY model"
    decision-gateway query --source exports/run-1 "SELECT ..."
    decision-gateway export exports/run-1 --keys "SELECT key FROM answers WHERE model = 'uniform'"
    decision-gateway export exports/run-1 --push you/decision-answers
    decision-gateway preheat hf://you/decision-answers

The cache is $DECISION_GATEWAY_CACHE, or ~/.local/share/decision-gateway/cache.sqlite; --cache overrides.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from .cache.sqlite import DEFAULT_PATH

if TYPE_CHECKING:
    from duckdb import DuckDBPyRelation


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="decision-gateway", description=__doc__.split("\n\n")[0])
    p.add_argument("--cache", default=str(DEFAULT_PATH), help="the cache file (default: %(default)s)")
    sub = p.add_subparsers(dest="command", required=True)

    q = sub.add_parser("query", help="SQL over the cache or an export (views: answers, labels)")
    q.add_argument("sql")
    q.add_argument("--source", help="an export directory instead of the cache")
    q.add_argument("--csv", action="store_true", help="print CSV instead of a table")

    e = sub.add_parser("export", help="answers chosen by a query to parquet, optionally to Hugging Face")
    e.add_argument("out", help="directory for answers.parquet and labels.parquet")
    e.add_argument("--keys", help="SQL returning the keys to export (default: all)")
    e.add_argument("--push", metavar="REPO_ID", help="then upload to this Hugging Face dataset")
    e.add_argument(
        "--public",
        action="store_true",
        help="allow a public dataset: create it public, or push to an existing public one (default: reject)",
    )

    h = sub.add_parser("preheat", help="load an export (directory or hf://owner/name) into the cache")
    h.add_argument("source")
    h.add_argument("--revision", help="Hugging Face revision (tag, branch or commit)")

    args = p.parse_args(argv)

    if args.command == "query":
        from . import query

        # None for statements that return no rows; DuckDB's stubs don't say so.
        rel: DuckDBPyRelation | None = query.connect(args.source or args.cache).sql(args.sql)
        if rel is None:
            return 0
        if args.csv:
            import csv

            w = csv.writer(sys.stdout)
            w.writerow(rel.columns)
            w.writerows(rel.fetchall())
        else:
            rel.show(max_rows=1000)
    elif args.command == "export":
        from .cache.export import export, push

        n = export(args.cache, args.out, args.keys)
        print(f"exported {n[0]} answers, {n[1]} label rows to {args.out}")
        if args.push:
            print(push(args.out, args.push, private=not args.public))
    elif args.command == "preheat":
        from .cache import Cache
        from .cache.preheat import preheat

        with Cache(args.cache) as cache:
            n = preheat(args.source, cache, revision=args.revision)
        print(f"added {n[0]} answers, {n[1]} label rows to {args.cache}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
