"""The built wheel carries schema.sql and the console script, and none of the tests."""

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_wheel_contents(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path), str(ROOT)],
        check=True,
        capture_output=True,
    )
    (wheel,) = tmp_path.glob("*.whl")
    with zipfile.ZipFile(wheel) as z:
        names = z.namelist()
        entry_points = z.read(next(n for n in names if n.endswith("entry_points.txt"))).decode()
    assert "decision_gateway/cache/schema.sql" in names
    assert "decision_gateway/testing.py" in names
    assert not [n for n in names if n.endswith(("_test.py", "conftest.py"))]
    assert "decision-gateway = decision_gateway.cli:main" in entry_points
