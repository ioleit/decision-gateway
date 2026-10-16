"""The built wheel carries schema.sql and the console script."""

import subprocess
import sys
import zipfile

ROOT = __import__("pathlib").Path(__file__).parent.parent


def test_wheel_contents(tmp_path):
    subprocess.run([sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path), str(ROOT)],
                   check=True, capture_output=True)
    (wheel,) = tmp_path.glob("*.whl")
    names = zipfile.ZipFile(wheel).namelist()
    assert "decision_router/cache/schema.sql" in names
    entry = next(n for n in names if n.endswith("entry_points.txt"))
    assert "decision-router = decision_router.cli:main" in zipfile.ZipFile(wheel).read(entry).decode()
