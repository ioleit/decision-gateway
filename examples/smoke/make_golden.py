"""Answer questions 6-10 with a model and export them to golden/<model>/ (answers.parquet, labels.parquet).

    python examples/smoke/make_golden.py               # uniform
    python examples/smoke/make_golden.py --model jev   # needs OPENROUTER_API_KEY

run.py --model <model> preheats from golden/<model>/.
"""

import argparse
import shutil
import tempfile
from pathlib import Path

from common import GOLDEN, HERE, labels, request, router
from decision_router.cache.export import export

p = argparse.ArgumentParser()
p.add_argument("--model", default="uniform")
args = p.parse_args()

with tempfile.TemporaryDirectory() as tmp:
    r = router(Path(tmp) / "cache.sqlite")
    for q in GOLDEN:
        r.ask(args.model, request(q), labels=labels(q, "golden"))
    out = HERE / "golden" / args.model
    shutil.rmtree(out, ignore_errors=True)
    n = export(r.cache.path, out)
    print(f"golden/{args.model}/: {n[0]} answers from {args.model}, {n[1]} label rows")
