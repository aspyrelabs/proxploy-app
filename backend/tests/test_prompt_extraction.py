"""extract_prompts: what the Install dialog has to ask, recovered from a script.

Every line here is a real one from the upstream catalog, not an invention.
The point of the exercise is that upstream is inconsistent in ways a tidy
fixture would hide: a default spelled `[1]`, choices spelled `(15/16/17)`,
and prompts indented with `${TAB3}`.
"""
from proxploy.services.classifier import classify_install_feasibility, extract_prompts


def one(line: str) -> dict:
    got = extract_prompts(line)
    assert len(got) == 1, got
    return got[0]


def test_layout_variables_are_stripped_from_the_label():
    """Upstream indents prompts with ${TAB3}. Rendered literally in a form
    label it is noise the operator has to read past."""
    assert one('read -r -p "${TAB3}Enter admin email address: " ADMIN_EMAIL')["label"] \
        == "Enter admin email address:"


def test_enumerated_choices_become_a_list():
    p = one('read -r -p "${TAB3}Enter PostgreSQL version (15/16/17/18): " ver')
    assert p["choices"] == ["15", "16", "17", "18"]


def test_a_stated_default_is_recovered():
    p = one('read -r -p "${TAB3}Select machine-learning type [1]: " ML_TYPE')
    assert p["default"] == "1"


def test_a_guarded_prompt_is_not_asked_about():
    """build.func already satisfies a guarded prompt from the environment, so
    there is nothing to ask. This is the same guard classify_install_feasibility
    uses, and the two must never disagree about what counts as a prompt."""
    script = '\n'.join([
        'if [[ -z "${DOMAIN:-}" ]]; then',
        '  read -r -p "Enter your domain: " DOMAIN',
        'fi',
    ])
    assert extract_prompts(script) == []
    assert classify_install_feasibility("build_container\n", script) == (True, None)


def test_a_stream_read_is_not_a_prompt():
    """`while read line` consumes a pipe, not a terminal. Asking the operator
    to fill it in would be nonsense."""
    assert extract_prompts('while read -r line; do echo "$line"; done < /tmp/x') == []
    assert extract_prompts('read -r x <<< "$s"') == []


def test_extraction_and_feasibility_agree_on_the_same_script():
    """One walk, one set of guards. A script the classifier calls unsupported
    must yield the prompts that made it unsupported, and an installable one
    must yield none."""
    blocked = 'build_container\nread -r -p "Do you want to continue? [y/N]: " CONFIRM\n'
    ok, reason = classify_install_feasibility("build_container\n", blocked)
    assert ok is False and "interactive" in reason
    assert [p["variable"] for p in extract_prompts(blocked)] == ["confirm"]

    clean = 'build_container\napt-get install -y nginx\n'
    assert classify_install_feasibility("build_container\n", clean) == (True, None)
    assert extract_prompts(clean) == []


def test_prompts_come_back_in_source_order():
    """The UI renders them as a form, and a form that reorders an installer's
    questions reads as a different set of questions."""
    script = '\n'.join([
        'read -r -p "first? [y/N] " ONE',
        'read -r -p "second? [y/N] " TWO',
        'read -r -p "third? [y/N] " THREE',
    ])
    assert [p["variable"] for p in extract_prompts(script)] == ["one", "two", "three"]
