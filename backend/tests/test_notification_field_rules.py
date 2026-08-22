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
