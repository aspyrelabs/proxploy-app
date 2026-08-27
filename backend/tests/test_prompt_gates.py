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
    assert ok is False and "interactive" in reason
    # JSON is what the column holds; a flag that does not survive the encode is
    # a flag the route and the UI never see.
    assert json.loads(json.dumps(prompts))[0]["gate"] is True
