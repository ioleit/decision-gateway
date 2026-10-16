"""decision-router query | export | preheat

    decision-router query "SELECT model, count(*) FROM answers GROUP BY model"
    decision-router query --source exports/run-1 "SELECT ..."
    decision-router export exports/run-1 --keys "SELECT key FROM answers WHERE model = 'uniform'"
    decision-router export exports/run-1 --push you/decision-answers
    decision-router preheat hf://you/decision-answers

The cache is $DECISION_ROUTER_CACHE, or ~/.local/share/decision-router/cache.sqlite; --cache overrides.
"""

from __future__ import annotations

import argparse
import sys

from .cache.sqlite import DEFAULT_PATH


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="decision-router", description=__doc__.split("\n\n")[0])
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
    e.add_argument("--public", action="store_true", help="create the dataset public (default: private)")

    h = sub.add_parser("preheat", help="load an export (directory or hf://owner/name) into the cache")
    h.add_argument("source")
    h.add_argument("--revision", help="Hugging Face revision (tag, branch or commit)")

    args = p.parse_args(argv)

    if args.command == "query":
        from . import query

        rel = query.connect(args.source or args.cache).sql(args.sql)
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

        n = preheat(args.source, Cache(args.cache), revision=args.revision)
        print(f"added {n[0]} answers, {n[1]} label rows to {args.cache}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
