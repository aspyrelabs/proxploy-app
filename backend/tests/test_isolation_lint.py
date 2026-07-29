import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_executor_isolation.py"


def test_clean_tree_passes():
    r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_violation_is_caught(tmp_path):
    pkg = tmp_path / "proxploy"
    (pkg / "services").mkdir(parents=True)
    (pkg / "services" / "evil.py").write_text("import asyncssh\n")
    (pkg / "executor").mkdir()
    (pkg / "executor" / "ok.py").write_text("import asyncssh\n")  # allowed here
    r = subprocess.run([sys.executable, str(SCRIPT), "--root", str(pkg)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "services/evil.py" in r.stdout
    assert "executor/ok.py" not in r.stdout
