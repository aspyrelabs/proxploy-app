"""extract_prompts: what the Install dialog has to ask, recovered from a script.

Every line here is a real one from the upstream catalog, not an invention.
The point of the exercise is that upstream is inconsistent in ways a tidy
fixture would hide: `-rp` and `-r -p`, `<y/N>` and `[y/N]` and `(y/N)`, a
default spelled `[1]`, and a variable called `prompt` holding a JWT.
"""
from proxploy.services.classifier import classify_install_feasibility, extract_prompts


def one(line: str) -> dict:
    got = extract_prompts(line)
    assert len(got) == 1, got
    return got[0]


def test_the_label_survives_a_combined_short_flag():
    """`read -rp` is as common upstream as `read -r -p`. Matching only the
    spaced form lost the label on a quarter of all prompts and fell back to the
    variable name, which is what the operator would then have been asked."""
    spaced = one('read -r -p "${TAB3}Enter your ACME Email: " ACME_EMAIL_INPUT')
    combined = one('read -rp "${TAB3}Enter your ACME Email: " ACME_EMAIL_INPUT')
    assert spaced["label"] == combined["label"] == "Enter your ACME Email:"


def test_layout_variables_are_stripped_from_the_label():
    """Upstream indents prompts with ${TAB3}. Rendered literally in a form
    label it is noise the operator has to read past."""
    assert one('read -rp "${TAB3}Enter admin email address: " ADMIN_EMAIL')["label"] \
        == "Enter admin email address:"


def test_sensitivity_comes_from_the_prompt_text_not_the_variable_name():
    """THE case this whole approach exists for. `prompt` is the variable an
    openziti installer reads an enrollment JWT into: no name heuristic can
    catch it, and services/audit.py's does not. The sentence beside it does."""
    jwt = one('read -r -p "${TAB3}Please paste an identity enrollment token(JTW)" prompt')
    assert jwt["variable"] == "prompt"
    assert jwt["sensitive"] is True

    pwd = one('read -r -p "${TAB3}Please enter the controller admin password [x]: " ZITI_PWD')
    assert pwd["sensitive"] is True

    # An API key named `*key`, which audit.py's REDACT_SUBSTRINGS excludes on
    # purpose (see the note there about settings.update auditing key NAMES).
    assert one('read -r -p "${TAB3}Enter your TMDb API key: " TMDBKEY')["sensitive"] is True

    # And a plain one is not dragged along.
    assert one('read -rp "${TAB3}Enter PostgreSQL version: " ver')["sensitive"] is False


def test_a_yes_no_prompt_defaults_to_the_capitalised_side():
    """Upstream writes the default as the capital letter. Declining is also
    the safe reading when it is ambiguous: these gate OPTIONAL extras, so "no"
    installs strictly less than the operator asked for, never more."""
    for text in ("<y/N>", "[y/N]", "(y/N)"):
        p = one(f'read -r -p "${{TAB3}}Would you like to add Unbound? {text} " prompt')
        assert p["kind"] == "yesno", text
        assert p["default"] == "n", text
    assert one('read -r -p "Install it? <Y/n> " opt')["default"] == "y"


def test_a_yes_no_marker_is_never_mistaken_for_a_default_value():
    """`[y/N]` matches the shape of a trailing default, so an ordering bug
    here offers the operator a value literally spelled "y/N"."""
    p = one('read -r -p "${TAB3}Do you want to continue? [y/N]: " CONFIRM')
    assert p["kind"] == "yesno"
    assert p["default"] == "n"


def test_enumerated_choices_become_a_list():
    p = one('read -rp "${TAB3}Enter PostgreSQL version (15/16/17/18): " ver')
    assert p["kind"] == "choice"
    assert p["choices"] == ["15", "16", "17", "18"]


def test_a_stated_default_is_recovered():
    p = one('read -r -p "${TAB3}Select machine-learning type [1]: " ML_TYPE')
    assert p["kind"] == "text"
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
