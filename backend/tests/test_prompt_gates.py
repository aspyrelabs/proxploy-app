"""A consent gate is never answerable without the operator, at any layer.

This is asserted rather than intended. Pre-answering a gate is the same act as
defaulting it to yes with extra steps, and the thing being consented to is
running an installer the upstream repository says it does not audit.
"""
from proxploy.services.classifier import (answerable_without_asking,
                                          extract_prompts)

# pihole's, verbatim apart from the warning lines above it. The capitalised
# default is `n`, and taking it reaches `exit 10`.
PIHOLE_GATE = '\n'.join([
    'read -r -p "${TAB3}Do you want to continue? [y/N]: " CONFIRM',
    'if [[ ! "$CONFIRM" =~ ^([yY][eE][sS]|[yY])$ ]]; then',
    '  msg_error "Aborted by user. No changes have been made."',
    '  exit 10',
    'fi',
])

# Same shape, no exit: declining skips an optional extra and the install
# carries on. This one IS answerable.
OPTIONAL_EXTRA = '\n'.join([
    'read -r -p "${TAB3}Would you like to add Unbound? <y/N> " prompt',
    'if [[ "$prompt" =~ ^[Yy]$ ]]; then',
    '  install_unbound',
    'fi',
])


def test_a_gate_is_detected_by_its_exit_not_by_its_wording():
    """No phrasing rule separates "Do you want to continue?" from "Would you
    like to add Unbound?" reliably. The exit does."""
    gate = extract_prompts(PIHOLE_GATE)[0]
    extra = extract_prompts(OPTIONAL_EXTRA)[0]
    assert gate["gate"] is True
    assert extra["gate"] is False
    # Both are yes/no prompts with the same default. Only the consequence differs.
    assert gate["kind"] == extra["kind"] == "yesno"
    assert gate["default"] == extra["default"] == "n"


def test_a_gate_is_never_answerable_without_asking():
    gate = extract_prompts(PIHOLE_GATE)[0]
    assert answerable_without_asking(gate) is False
    # ...and it stays refused even though every other signal says it could be
    # defaulted. This is the assertion that stops a later "optimisation".
    assert gate["kind"] == "yesno" and gate["default"] is not None


def test_an_optional_extra_is_still_answerable():
    """The refusal has to be narrow, or it takes the 26 no-dialog apps with it."""
    assert answerable_without_asking(extract_prompts(OPTIONAL_EXTRA)[0]) is True


def test_the_gate_flag_beats_every_other_route_to_a_default():
    """Whatever shape a gate arrives in, the answer is the same. Guards the
    layer boundary: a caller must not be able to reach an auto-answer for one
    by presenting it as a choice or as a plain defaulted field."""
    for extra in ({"kind": "yesno", "default": "y"},
                  {"kind": "choice", "default": "1", "choices": ["1", "2"]},
                  {"kind": "text", "default": "anything"}):
        assert answerable_without_asking({"gate": True, "variable": "x", **extra}) is False
        assert answerable_without_asking({"gate": False, "variable": "x", **extra}) is True


def test_docker_socket_choice_is_not_a_gate_but_is_never_auto_answered():
    """The security-relevant prompt the mechanical rule deliberately does NOT
    flag: docker's `exit 150` is error handling 34 lines later, not a consent
    gate. It must still reach the operator, which it does by being a choice
    with no stated default, and its label has to carry the risk verbatim."""
    line = ('read -r -p "${TAB3}Expose Docker TCP socket (insecure) ? '
            '[n = No, l = Local only (127.0.0.1), a = All interfaces (0.0.0.0)] '
            '<n/l/a>: " socket_choice')
    p = extract_prompts(line)[0]
    assert p["gate"] is False
    assert p["kind"] == "choice" and p["choices"] == ["n", "l", "a"]
    assert answerable_without_asking(p) is False
    assert "insecure" in p["label"]


def test_a_gate_survives_the_round_trip_through_the_catalog_row(tmp_path):
    """prompts is written in the same pass as `installable`, against the same
    script text, so the verdict and the questions cannot describe different
    revisions."""
    import json

    from proxploy.services.classifier import classify_install_feasibility
    script = "build_container\n" + PIHOLE_GATE
    ok, reason = classify_install_feasibility("build_container\n", script)
    prompts = extract_prompts(script)
    # A gate is answerable, by the operator and only by the operator, so the
    # script is installable. What it is NOT is auto-answerable, which is the
    # assertion below and the one the route enforces.
    assert (ok, reason) == (True, None)
    assert answerable_without_asking(prompts[0]) is False
    # JSON is what the column holds; a flag that does not survive the encode is
    # a flag the route and the UI never see.
    assert json.loads(json.dumps(prompts))[0]["gate"] is True


def test_a_script_whose_prompts_can_all_be_answered_is_installable_now():
    """The point of the whole exercise. An unguarded prompt used to refuse the
    script outright; it now becomes a question the operator answers."""
    from proxploy.services.classifier import classify_install_feasibility
    ok, reason = classify_install_feasibility(
        "build_container\n", 'read -rp "Add Unbound? <y/N> " prompt')
    assert (ok, reason) == (True, None)


def test_a_prompt_inside_a_retry_loop_keeps_the_script_unsupported():
    """The shim answers from the environment EVERY time read is called, so a
    loop that re-prompts until the answer validates never sees a new value.
    Give it something the loop rejects and it spins forever: the install hangs
    instead of failing, which is the worst outcome available."""
    from proxploy.services.classifier import (UNSUPPORTED_RETRY_LOOP,
                                              classify_install_feasibility)
    script = '\n'.join([
        'while true; do',
        '  read -rp "Enter PostgreSQL version (15/16/17/18): " ver',
        '  case "$ver" in 15|16|17|18) break ;; *) echo invalid ;; esac',
        'done',
    ])
    ok, reason = classify_install_feasibility("build_container\n", script)
    assert ok is False and reason == UNSUPPORTED_RETRY_LOOP
    assert extract_prompts(script)[0]["in_loop"] is True


def test_a_prompt_that_names_no_variable_keeps_the_script_unsupported():
    """whiptail assigns nothing, so there is no name to key an answer on and
    nothing the dialog could show. extract_prompts drops it, and a dropped
    prompt is exactly how a script becomes installable and then blocks on a
    question nobody was ever shown, so the count is compared rather than
    trusted."""
    from proxploy.services.classifier import (UNSUPPORTED_UNNAMED_PROMPT,
                                              classify_install_feasibility)
    script = 'whiptail --title "Pick one" --menu "choose" 12 60 3 a A b B'
    assert extract_prompts(script) == []
    ok, reason = classify_install_feasibility("build_container\n", script)
    assert ok is False and reason == UNSUPPORTED_UNNAMED_PROMPT


def test_one_unanswerable_prompt_condemns_the_whole_script():
    """EVERY prompt, not most. One prompt we cannot answer blocks the install
    behind a closed stdin no matter how many others we got right."""
    from proxploy.services.classifier import classify_install_feasibility
    script = '\n'.join([
        'read -rp "Add Unbound? <y/N> " prompt',
        'read -rp "Enter your name: " NAME',
        'whiptail --menu "and this one cannot be answered" 12 60 2 a A b B',
    ])
    ok, _ = classify_install_feasibility("build_container\n", script)
    assert ok is False
    # The two answerable ones are still recovered, so a card can say WHY.
    assert [p["variable"] for p in extract_prompts(script)] == ["prompt", "name"]
