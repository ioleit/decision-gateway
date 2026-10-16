"""The built wheel carries schema.sql and the console script, and none of the tests."""

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = __import__("pathlib").Path(__file__).parent.parent


def test_wheel_contents(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path), str(ROOT)],
        check=True,
        capture_output=True,
    )
    (wheel,) = tmp_path.glob("*.whl")
    names = zipfile.ZipFile(wheel).namelist()
    assert "decision_router/cache/schema.sql" in names
    assert "decision_router/testing.py" in names
    assert not [n for n in names if n.endswith(("_test.py", "conftest.py"))]
    entry = next(n for n in names if n.endswith("entry_points.txt"))
    assert "decision-router = decision_router.cli:main" in zipfile.ZipFile(wheel).read(entry).decode()
