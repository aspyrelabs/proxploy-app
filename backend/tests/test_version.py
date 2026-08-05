"""The version is stated once. A release tag, a signed manifest and
/meta/version that disagree are a supply-chain bug, not a cosmetic one."""
import re
import tomllib
from pathlib import Path

import proxploy


def test_version_is_semver_and_at_least_1_0_0():
    assert re.fullmatch(r"\d+\.\d+\.\d+", proxploy.__version__)
    major = int(proxploy.__version__.split(".")[0])
    assert major >= 1, "9a ships 1.0.0; 0.x is pre-release"


def test_pyproject_does_not_hardcode_a_second_version():
    raw = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    project = raw["project"]
    assert "version" not in project, (
        "pyproject must declare version dynamic and read it from the package")
    assert "version" in project.get("dynamic", [])


def test_installed_metadata_matches_the_package():
    from importlib.metadata import version as dist_version
    assert dist_version("proxploy") == proxploy.__version__
