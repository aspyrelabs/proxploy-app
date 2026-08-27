from pathlib import Path

from proxploy.services.classifier import (answerable_without_asking,
                                          classify_install_feasibility,
                                          extract_prompts)

FIXTURES = Path(__file__).parent / "fixtures" / "community_scripts"


def _load(name: str) -> tuple[str, str]:
    d = FIXTURES / name
    return (d / "ct.sh").read_text(), (d / "install.sh").read_text()


def test_fully_silent_script_is_installable():
    ct, install = _load("redis")
    installable, reason = classify_install_feasibility(ct, install)
    assert (installable, reason) == (True, None)


def test_an_unconditional_prompt_is_now_a_question_rather_than_a_refusal():
    """Was unsupported. An unguarded prompt is recovered and asked instead, so
    long as every prompt in the script can be. postgresql's version prompt
    spells its options out, so it arrives as a choice."""
    ct, install = _load("postgresql")
    assert classify_install_feasibility(ct, install) == (True, None)
    p = extract_prompts(install)[0]
    assert p["variable"] == "ver" and p["kind"] == "choice"


def test_several_unconditional_prompts_are_all_recovered():
    """docker is the most installed app in the catalog and was blocked by
    three prompts. Its TCP socket question is a choice with no default, so it
    reaches the operator rather than being answered for them."""
    ct, install = _load("docker")
    assert classify_install_feasibility(ct, install) == (True, None)
    prompts = extract_prompts(install)
    assert [p["variable"] for p in prompts] == ["prompt", "prompt_agent", "socket_choice"]
    socket = prompts[-1]
    assert socket["kind"] == "choice" and answerable_without_asking(socket) is False


def test_env_var_guarded_prompt_is_still_installable():
    ct, install = _load("jellyfin-hwaccel")
    installable, reason = classify_install_feasibility(ct, install)
    assert (installable, reason) == (True, None)


# --- I1 probes: the review found PROMPT_RE too narrow (only `read ... -p`)
# and GUARD_RE too loose (any `${X:-}` within 3 lines guarded any prompt).


def test_a_bare_read_with_no_p_flag_is_asked_under_its_variable_name():
    """Still detected as a prompt, which was the original point of this probe.
    It has no sentence to label the field with, so the variable name is all the
    operator gets. Answerable, just not well explained."""
    ct, install = _load("probe-bare-read")
    assert classify_install_feasibility(ct, install) == (True, None)
    p = extract_prompts(install)[0]
    assert p["variable"] == "answer" and p["label"] == "answer"


def test_a_silent_read_is_sensitive_by_construction():
    """`read -s` suppresses the echo, so the script author has already declared
    the value too sensitive to show on a terminal. That outranks the wording
    heuristic and is why it works here at all: this probe has no prompt text,
    so its label is the bare variable "pass", which matches no sentence rule."""
    ct, install = _load("probe-silent-read")
    assert classify_install_feasibility(ct, install) == (True, None)
    p = extract_prompts(install)[0]
    assert p["label"] == "pass"
    assert p["sensitive"] is True


def test_an_unrelated_nearby_env_default_does_not_guard_a_prompt():
    """The guard has to name the variable the read assigns into. This probe has
    an unrelated ${FOO:-} a line above, which must not count. Asserted now on
    the prompt still being RECOVERED, since an unguarded prompt no longer
    refuses the script: if the correlation broke, the prompt would be treated
    as satisfied from the environment and silently disappear from the dialog."""
    ct, install = _load("probe-unrelated-guard")
    assert classify_install_feasibility(ct, install) == (True, None)
    assert [p["variable"] for p in extract_prompts(install)] == ["admin_email"]


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


def test_an_addon_script_is_refused_at_the_call_site_not_by_this_function():
    """These apps are unsupported because of WHERE they install, not because
    they prompt.

    The prompt is real and is still recovered: "Install ${APP}? (y/N)" reads
    into `install_prompt` and is a gate, since declining exits. Now that an
    answerable prompt no longer refuses a script, this function returns
    installable for it, which makes the layering explicit rather than
    accidental. The verdict that matters is fixed in
    services/catalog.py::ensure_classified, because the addon script is not
    what an install runs: build_container curls install/<var_install>.sh,
    that URL 404s for these apps, and `bash -c ""` exits 0 having built an
    empty container. Softening THIS function was never the risk; relying on it
    to carry the addon verdict would be.
    """
    ct = DELEGATING_CT.format(slug="dockge", name="Dockge")

    assert classify_install_feasibility(ct, INTERACTIVE_ADDON) == (True, None)

    prompt = extract_prompts(INTERACTIVE_ADDON)[0]
    assert prompt["variable"] == "install_prompt"
    assert prompt["gate"] is True, "declining exits, so it is consent"
    assert answerable_without_asking(prompt) is False


def test_the_detector_is_content_driven_and_not_a_blanket_refusal():
    """A silent addon script really does pass the feasibility check: this
    function judges the text it is handed and nothing else, which is what
    makes the interactive finding above meaningful rather than tautological.

    The ROW is still not-installable in that case, because the addon script is
    not what an install runs. That separation is the whole design, and
    tests/test_catalog_ingest.py pins the row-level half of it."""
    ct = DELEGATING_CT.format(slug="dockge", name="Dockge")

    assert classify_install_feasibility(ct, SILENT_ADDON) == (True, None)
