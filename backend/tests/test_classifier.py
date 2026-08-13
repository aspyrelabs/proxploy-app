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
    loop must not be what flags it, strip the real prompt and it's clean."""
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


# --- ct scripts that delegate to tools/addon/<slug>.sh -----------------------
#
# Five popular apps (coolify, dockge, dokploy, komodo, runtipi) ship a complete
# standard LXC builder but no install/<slug>-install.sh. Where a normal app
# sources its install script, they delegate to tools/addon/<slug>.sh, and the
# addon script is the payload. Shapes below are taken from the real scripts at
# pinned SHA a222d32a318e3463bcde935bf52fdf5f883fa804.

from proxploy.services.classifier import addon_delegation_slug  # noqa: E402

DELEGATING_CT = '''#!/usr/bin/env bash
source <(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/misc/build.func)
APP="{name}"
var_cpu="${{var_cpu:-2}}"
var_ram="${{var_ram:-2048}}"
var_disk="${{var_disk:-18}}"
var_os="${{var_os:-debian}}"
var_version="${{var_version:-13}}"

ADDON_SCRIPT="https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/addon/{slug}.sh"

function update_script() {{
  msg_warn "{name} has been migrated to an addon script."
  echo -e "${{TAB}}${{GN}}bash <(curl -fsSL ${{ADDON_SCRIPT}})${{CL}}"
  cat <<'MIGRATION_EOF' >"$TMP_UPDATE"
bash -c "$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/addon/{slug}.sh)"
MIGRATION_EOF
  msg_info "Running addon update"
  type=update bash <(curl -fsSL "${{ADDON_SCRIPT}}")
  exit
}}

start
build_container
description
'''

# The real addon scripts' fresh-install path, verbatim in shape: an
# unconditional y/N prompt with a bare `read -r`, and the only non-interactive
# entrypoint is type=update, which does not install.
INTERACTIVE_ADDON = '''#!/usr/bin/env bash
if [[ "${type:-}" == "update" ]]; then
  update
  exit 0
fi

msg_warn "${APP} is not installed."
echo -n "${TAB}Install ${APP}? (y/N): "
read -r install_prompt
if [[ "${install_prompt,,}" =~ ^(y|yes)$ ]]; then
  install
else
  msg_warn "Installation cancelled. Exiting."
  exit 0
fi
'''

SILENT_ADDON = '''#!/usr/bin/env bash
msg_info "Installing"
$STD apt install -y docker-compose
msg_ok "Installed"
'''

# The normal shape, for contrast: build_container and zero addon delegation.
PLEX_SHAPED_CT = '''#!/usr/bin/env bash
APP="Plex Media Server"
var_cpu="${var_cpu:-2}"

start
build_container
description
'''

FIVE = ["coolify", "dockge", "dokploy", "komodo", "runtipi"]


def test_each_of_the_five_is_recognised_from_script_content_alone():
    """Detected from structure, never from a list of these five slugs. The
    dual-variant collision logic in services/catalog.py documents why: a fixed
    allowlist silently missed `runtipi` once already."""
    for slug in FIVE:
        ct = DELEGATING_CT.format(slug=slug, name=slug.title())
        assert addon_delegation_slug(ct) == slug, slug


def test_a_normal_app_is_not_mistaken_for_a_delegating_one():
    """plex shape: build_container, no tools/addon reference anywhere."""
    assert addon_delegation_slug(PLEX_SHAPED_CT) is None
    ct, _install = _load("redis")
    assert addon_delegation_slug(ct) is None


def test_the_word_addon_in_prose_does_not_count_as_delegation():
    """These scripts print "has been migrated to an addon script" in a
    msg_warn, so the match is anchored on the tools/addon/<slug>.sh path and
    not on the word appearing somewhere."""
    prose = PLEX_SHAPED_CT.replace(
        'APP="Plex Media Server"',
        'APP="Plex"\nmsg_warn "This app has been migrated to an addon script."')

    assert addon_delegation_slug(prose) is None


def test_an_ambiguous_or_multi_container_script_is_declined():
    """Two different addon scripts named, or two build_containers, and we
    cannot say which is the payload. Guessing is exactly what this module
    refuses to do."""
    two_addons = DELEGATING_CT.format(slug="dockge", name="Dockge").replace(
        "start\nbuild_container",
        "bash <(curl -fsSL .../tools/addon/portainer.sh)\nstart\nbuild_container")
    assert addon_delegation_slug(two_addons) is None

    two_builds = DELEGATING_CT.format(slug="dockge", name="Dockge").replace(
        "build_container\ndescription", "build_container\nbuild_container\ndescription")
    assert addon_delegation_slug(two_builds) is None

    # ...and the same slug named four times, as the real scripts do, is fine.
    assert addon_delegation_slug(
        DELEGATING_CT.format(slug="dockge", name="Dockge")) == "dockge"


def test_the_capture_cannot_walk_out_of_tools_addon():
    """The captured slug is fetched, so it must not be able to name a path."""
    escaping = DELEGATING_CT.format(slug="dockge", name="Dockge").replace(
        "tools/addon/dockge.sh", "tools/addon/../../../etc/passwd.sh")

    assert addon_delegation_slug(escaping) is None


def test_the_detector_still_reports_interactive_input_for_these_scripts():
    """The interactive-input finding is TRUE and stays exactly as it was. The
    real addon scripts prompt `Install ${APP}? (y/N)` with a bare `read -r` on
    the fresh-install path, and their only non-interactive entrypoint is
    type=update, which updates rather than installs.

    It is simply not what makes these apps unsupported. The verdict is fixed
    at the call site (services/catalog.py::ensure_classified) because the
    addon script is not what an install runs; softening THIS function to make
    them installable would be the wrong fix twice over."""
    ct = DELEGATING_CT.format(slug="dockge", name="Dockge")

    installable, reason = classify_install_feasibility(ct, INTERACTIVE_ADDON)

    assert installable is False
    assert reason == ("install script requires interactive input, "
                      "no non-interactive entrypoint")


def test_the_detector_is_content_driven_and_not_a_blanket_refusal():
    """A silent addon script really does pass the feasibility check: this
    function judges the text it is handed and nothing else, which is what
    makes the interactive finding above meaningful rather than tautological.

    The ROW is still not-installable in that case, because the addon script is
    not what an install runs. That separation is the whole design, and
    tests/test_catalog_ingest.py pins the row-level half of it."""
    ct = DELEGATING_CT.format(slug="dockge", name="Dockge")

    assert classify_install_feasibility(ct, SILENT_ADDON) == (True, None)
