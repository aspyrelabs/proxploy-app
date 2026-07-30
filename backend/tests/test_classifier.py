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


# --- I1 probes: the review found PROMPT_RE too narrow (only `read ... -p`)
# and GUARD_RE too loose (any `${X:-}` within 3 lines guarded any prompt).


def test_bare_read_with_no_p_flag_is_unsupported():
    ct, install = _load("probe-bare-read")
    installable, reason = classify_install_feasibility(ct, install)
    assert installable is False
    assert reason == "install script requires interactive input, no non-interactive entrypoint"


def test_silent_read_is_unsupported():
    ct, install = _load("probe-silent-read")
    installable, reason = classify_install_feasibility(ct, install)
    assert installable is False
    assert reason == "install script requires interactive input, no non-interactive entrypoint"


def test_an_unrelated_nearby_env_default_does_not_guard_a_prompt():
    ct, install = _load("probe-unrelated-guard")
    installable, reason = classify_install_feasibility(ct, install)
    assert installable is False
    assert reason == "install script requires interactive input, no non-interactive entrypoint"


def test_a_guard_naming_the_reads_own_variable_still_counts():
    ct, install = _load("probe-real-guard")
    installable, reason = classify_install_feasibility(ct, install)
    assert (installable, reason) == (True, None)


def test_a_while_read_stream_loop_is_not_treated_as_a_prompt():
    """The probe-bare-read fixture's `while read -r pkg; do ... done < file`
    loop must not be what flags it — strip the real prompt and it's clean."""
    ct, install = _load("probe-bare-read")
    without_the_prompt = install.replace("read ANSWER", ": ")
    installable, reason = classify_install_feasibility(ct, without_the_prompt)
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
