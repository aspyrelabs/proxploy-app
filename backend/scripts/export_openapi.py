#!/usr/bin/env python3
"""Write the OpenAPI schema to a file for the docs site's API reference.

Builds the app in-process (the same way tests/test_openapi_surface.py does
via tests.support.make_app) rather than hitting a running server, so
regenerating the reference needs nothing but a checkout and a venv.

The app construction below is a deliberate inline copy of
tests/support.py::make_app rather than an import of it: packaging/
build_release.sh excludes tests/ from the release tarball but does not
exclude scripts/, so an installed copy of this script would ImportError on
`from tests.support import make_app` the moment it runs outside a checkout.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _build_app(tmp_path: Path):
    from proxploy.config import Settings
    from proxploy.main import create_app

    settings = Settings(db_url=f"sqlite:///{tmp_path}/t.db", data_dir=tmp_path,
                         master_key_file=tmp_path / "master.key", poll_enabled=False)
    return create_app(settings)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        schema = _build_app(Path(tmp)).openapi()
    text = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text)
        print(f"wrote {sys.argv[1]}: {len(schema['paths'])} paths")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
