"""Field rules, the half the form was missing.

The picker shipped as a renderer with no rules: it collected whatever was
typed and the only gate was Apprise's parser, which is strict for some
plugins and indifferent for others. Half of this file's REJECTED table used
to save cleanly, show a correct badge, and fail only when something real
needed sending.
"""
import re

import pytest

from proxploy.services.notification_catalog import BY_KIND, CATALOG, build_url
from proxploy.services.notifier import parses
from tests.test_notification_catalog import SAMPLES

# What used to sail through. Each is (kind, field, value) that must now be
# refused with a message naming the field.
REJECTED = [
    ("email", "to", "not-an-email-at-all"),
    ("email", "host", "smtp.example.com/../etc"),
    ("ntfy", "topic", "THIS HAS SPACES AND CAPS!!"),
    ("gotify", "token", "x"),
    ("discord", "webhook_id", "abc"),
    ("telegram", "bot_token", "just-a-string"),
    ("telegram", "chat_id", "not a chat"),
    ("twilio", "account_sid", "nope"),
    ("signal", "from_phone", "banana"),
    ("sendgrid", "from_email", "garbage"),
    ("ses", "region", "not-a-region"),
    ("pushover", "user_key", "short"),
    ("zulip", "botname", "a name with spaces"),
    ("slack", "token_a", "has spaces"),
]


@pytest.mark.parametrize("kind,field,value", REJECTED,
                         ids=[f"{k}.{f}" for k, f, _ in REJECTED])
def test_rubbish_in_a_field_is_refused_by_name(kind, field, value):
    label = next(f.label for f in BY_KIND[kind].fields if f.key == field)
    with pytest.raises(ValueError) as e:
        build_url(kind, {**SAMPLES[kind], field: value})
    assert label in str(e.value), f"the message must name the field: {e.value}"


@pytest.mark.parametrize("service", CATALOG, ids=lambda s: s.kind)
def test_the_known_good_samples_all_still_pass(service):
    """The rules must not be so tight they reject what actually works. Every
    sample here is a URL Apprise itself accepts."""
    url = build_url(service.kind, SAMPLES[service.kind])
    assert parses(url)


@pytest.mark.parametrize("service", CATALOG, ids=lambda s: s.kind)
def test_every_pattern_compiles_in_python(service):
    """Apprise ships at least one that does not: zulip's organization token is
    `^[A-Z0-9_-]{1,32})$`, with an unbalanced paren. Copying one blindly would
    take the module down at import."""
    for f in service.fields:
        if f.pattern:
            re.compile(f.pattern)


@pytest.mark.parametrize("service", CATALOG, ids=lambda s: s.kind)
def test_every_pattern_is_portable_to_javascript(service):
    """The same string is handed to the browser for live feedback, so it must
    not use Python-only syntax the RegExp constructor would throw on."""
    for f in service.fields:
        if not f.pattern:
            continue
        assert "(?P<" not in f.pattern, f"{f.key}: named group is Python-only"
        assert "(?i)" not in f.pattern, f"{f.key}: inline flag is Python-only"
        assert "\\Z" not in f.pattern and "\\A" not in f.pattern


@pytest.mark.parametrize("service", CATALOG, ids=lambda s: s.kind)
def test_a_rule_always_comes_with_a_plain_language_hint(service):
    """"Value does not match ^[A-Za-z0-9_-]{1,64}$" is not a message for a
    person. Every rule has to explain itself."""
    for f in service.fields:
        if f.pattern:
            assert f.hint, f"{service.kind}.{f.key} has a rule and no hint"
            assert "^" not in f.hint and "$" not in f.hint


def test_the_hint_is_what_the_caller_sees():
    # Capitals are fine (Apprise's own topic regex carries the "i" flag and
    # ntfy topics are case-sensitive), so the rejection here is the "!".
    with pytest.raises(ValueError, match="dashes and underscores"):
        build_url("ntfy", {"host": "ntfy.sh", "topic": "NOPE!"})


def test_a_field_with_no_rule_still_accepts_anything():
    """A password is a password. Rules go on the fields with a known shape,
    not on everything for the sake of symmetry."""
    url = build_url("email", {**SAMPLES["email"], "password": "]}#@/weird p@ss"})
    assert parses(url)


def test_the_catalog_endpoint_hands_the_rules_to_the_client():
    from proxploy.services.notification_catalog import public_catalog

    ntfy = next(k for k in public_catalog() if k["kind"] == "ntfy")
    topic = next(f for f in ntfy["fields"] if f["key"] == "topic")
    assert topic["pattern"]
    assert topic["hint"]


# --- Credentials for the wrong service -------------------------------------

# No field in the guided form takes a whole URL, so a value carrying "://" is
# wrong whatever the service. These all used to be someone's afternoon: the
# channel saves, the badge looks right, and nothing is delivered.
WRONG_SERVICE = [
    ("whatsapp", "token", "https://hooks.slack.com/services/T0/B0/abcdefghijkl"),
    ("whatsapp", "token", "slack://TokenA/TokenB/TokenCabcdefgh"),
    ("email", "host", "slack://TokenA/TokenB/TokenC"),
    ("email", "to", "mailto://user:pass@gmail.com"),
    ("webhook", "host", "https://example.com/hook"),
    ("gotify", "token", "mailto://user:pass@gmail.com"),
    ("slack", "token_a", "https://hooks.slack.com/services/T0/B0/xyz"),
    ("ntfy", "topic", "ntfy://ntfy.sh/proxploy"),
    ("pushover", "token", "tgram://123456789:key/42"),
]


@pytest.mark.parametrize("kind,field,value", WRONG_SERVICE,
                         ids=[f"{k}.{f}" for k, f, _ in WRONG_SERVICE])
def test_a_whole_url_in_a_field_is_refused_whatever_the_service(kind, field, value):
    label = next(f.label for f in BY_KIND[kind].fields if f.key == field)
    with pytest.raises(ValueError) as e:
        build_url(kind, {**SAMPLES[kind], field: value})
    assert label in str(e.value)


def test_the_message_says_it_is_a_url_rather_than_reciting_the_pattern():
    """"Access token is not right. At least 20 characters, no spaces." is a
    true statement about a pasted Slack URL and a useless one."""
    with pytest.raises(ValueError, match="not a whole URL"):
        build_url("whatsapp", {**SAMPLES["whatsapp"],
                               "token": "https://hooks.slack.com/services/T0/B0/x"})


def test_the_paste_a_url_path_is_untouched_by_this():
    """The guard belongs to the guided fields. A whole URL is exactly what the
    escape hatch is for, and it does not go through build_url at all."""
    from proxploy.api.notifications import _require_url

    assert _require_url("slack://a/b/c") == "slack://a/b/c"


# --- Several recipients -----------------------------------------------------

@pytest.mark.parametrize("value", [
    "a@x.com,b@y.com",
    "a@x.com, b@y.com",
    "a@x.com , b@y.com",
    "a@x.com/b@y.com",        # the older spelling, still accepted
], ids=["comma", "comma-space", "spaced", "slash"])
def test_several_addresses_reach_apprise_as_several_targets(value):
    """A comma is what people expect, and Apprise unquotes the path before
    splitting, so an encoded comma resolves exactly as a slash does. The slash
    came from Apprise's own URL templates and was never a requirement."""
    import apprise

    url = build_url("email", {**SAMPLES["email"], "to": value})
    ap = apprise.Apprise()
    assert ap.add(url)
    assert [t[1] for t in ap[0].targets] == ["a@x.com", "b@y.com"]


@pytest.mark.parametrize("value", ["a@x.com;b@y.com", "a@x.com b@y.com",
                                   "a@x.com,not-an-address"])
def test_a_separator_we_do_not_take_is_refused_rather_than_silently_one_target(value):
    """The failure worth catching: a separator Apprise does not split on makes
    the whole string one malformed address, and mail to nobody looks identical
    to mail nobody read."""
    with pytest.raises(ValueError, match="Send to"):
        build_url("email", {**SAMPLES["email"], "to": value})


def test_several_phone_numbers_do_the_same():
    import apprise

    url = build_url("twilio", {**SAMPLES["twilio"],
                               "to": "+15559876543, +15550001111"})
    ap = apprise.Apprise()
    assert ap.add(url)
    assert [t[1] for t in ap[0].targets] == ["+15559876543", "+15550001111"]


def test_every_field_you_type_into_carries_an_example():
    """A password box shows no placeholder, so a secret field has nothing to
    borrow and needs one spelled out. Those are exactly the fields where
    "what am I even meant to paste here" bites hardest.

    Toggles are exempt, and it is not a loophole: an example is a realistic
    VALUE to type, and there is nothing to type into a switch. The (i) beside
    "Use TLS" reading "on" would tell an operator strictly less than the
    switch already does. Every toggle in the catalog is the one shared
    TLS_FIELD (notification_catalog.py), which carries help text instead.
    """
    from proxploy.services.notification_catalog import public_catalog

    typed = 0
    for svc in public_catalog():
        for f in svc["fields"]:
            if f.get("type") == "toggle":
                assert f["help"], f"{svc['kind']}.{f['key']} is a toggle with no help"
                continue
            typed += 1
            assert f["example"], f"{svc['kind']}.{f['key']} has no example"
    # A rule that exempts its way down to nothing has stopped being a rule.
    assert typed > 20, f"only {typed} typed fields checked; the walk is broken"


def test_no_example_is_a_real_credential_shape_we_would_regret():
    """Examples are shown in the UI. None of them may look like something an
    operator could mistake for a working value they should keep."""
    from proxploy.services.notification_catalog import public_catalog

    for svc in public_catalog():
        for f in svc["fields"]:
            assert "proxploy.io" not in f["example"]
            assert "@aspyrelabs" not in f["example"]
