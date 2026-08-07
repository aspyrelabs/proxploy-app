"""The docs site's API reference is generated from this artifact, so the
export has to be a pure function of the app, no server, no network."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_openapi.py"


def test_export_writes_a_schema_with_the_product_version(tmp_path):
    import proxploy

    out = tmp_path / "openapi.json"
    subprocess.run([sys.executable, str(SCRIPT), str(out)], check=True)
    schema = json.loads(out.read_text())
    assert schema["info"]["version"] == proxploy.__version__
    assert schema["info"]["title"] == "Proxploy"


def test_export_covers_every_registered_route(tmp_path):
    """Guards the failure mode where the export silently drops routers."""
    from tests.support import make_app

    out = tmp_path / "openapi.json"
    subprocess.run([sys.executable, str(SCRIPT), str(out)], check=True)
    exported = set(json.loads(out.read_text())["paths"])
    live = set(make_app(tmp_path / "live").openapi()["paths"])
    assert exported == live
