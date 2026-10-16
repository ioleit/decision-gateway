"""The built wheel carries the package and none of the tests."""

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
    assert "decision_gateway/transports/gateway_transport.py" in names
    assert "decision_gateway/store/sqlite.py" in names
    assert "decision_gateway/testing.py" in names
    assert not [n for n in names if n.endswith(("_test.py", "conftest.py"))]
