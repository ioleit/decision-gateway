# Smoke example

Ten yes/no questions (`questions.json`) through the router, to show how the parts fit:

1. **Ask** questions 1–5. Each answer is cached with labels (`example`, `id`, `origin`).
2. **Query** the cache with `decision_router.query`: per question and a summary, in SQL.
3. **Preheat** questions 6–10 from `golden/<model>/`: a saved export of known answers (a
   "golden" set, in testing terms), made beforehand with `make_golden.py`.
4. **Query** again: all ten, by origin.
5. **Ask all ten again**: every answer comes from the cache; the model is not asked.

```bash
pip install -e '.[query]'
python examples/smoke/run.py                 # with uniform: no network, no key
python examples/smoke/run.py --model jev     # OpenRouter: needs OPENROUTER_API_KEY
```

`golden/<model>/` holds that model's answers to questions 6–10: `uniform` and `jev` (asked
2026-10-16, typesafe/jev-1.13-20260917 via OpenRouter). A preheated answer is only served to
the same model name with the same requirements, because both are part of the cache key. To make a golden set for
another model:

```bash
python examples/smoke/make_golden.py --model jev
```

The same queries from the command line, on a kept cache:

```bash
python examples/smoke/run.py --cache smoke.sqlite
decision-router --cache smoke.sqlite query "SELECT labels->>'origin' AS origin, count(*) FROM labels GROUP BY ALL"
```
