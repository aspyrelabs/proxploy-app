from pathlib import Path

from proxploy.services.classifier import classify_install_feasibility

FIXTURES = Path(__file__).parent / "fixtures" / "community_scripts"


def _load(name: str) -> tuple[str, str]:
    d = FIXTURES / name
    return (d / "ct.sh").read_text(), (d / "install.sh").read_text()


def test_fully_silent_script_is_installable():
    ct, install = _load("redis")
    installable, reason = classify_install_feasibility(ct, install)
    assert (installable, reason) == (True, None)


def test_unconditional_prompt_with_no_default_is_unsupported():
    ct, install = _load("postgresql")
    installable, reason = classify_install_feasibility(ct, install)
    assert installable is False
    assert reason == "install script requires interactive input, no non-interactive entrypoint"


def test_multiple_unconditional_prompts_are_unsupported():
    ct, install = _load("docker")
    installable, reason = classify_install_feasibility(ct, install)
    assert installable is False
    assert reason == "install script requires interactive input, no non-interactive entrypoint"


def test_env_var_guarded_prompt_is_still_installable():
    ct, install = _load("jellyfin-hwaccel")
    installable, reason = classify_install_feasibility(ct, install)
    assert (installable, reason) == (True, None)


def test_multi_ct_pattern_is_unsupported():
    ct = "build_container\nbuild_container\n"
    installable, reason = classify_install_feasibility(ct, "")
    assert installable is False
    assert reason == "multi-CT / docker-compose pattern"


def test_missing_build_container_call_is_unsupported():
    installable, reason = classify_install_feasibility("# no build_container here", "")
    assert installable is False
    assert reason == "multi-CT / docker-compose pattern"
