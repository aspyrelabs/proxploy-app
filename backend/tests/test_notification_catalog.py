"""Every guided channel kind must assemble into a URL Apprise actually accepts.

This is the check that makes hand-writing 20 templates safe: a typo, a renamed
Apprise token or a plugin that tightened its validation shows up here rather
than as a channel that saves cleanly and never delivers.
"""
import pytest

from proxploy.models import KIND_FROM_SCHEME
from proxploy.services import notifier
from proxploy.services.notification_catalog import BY_KIND, CATALOG, build_url

# One realistic value per field. Several plugins validate shape (Twilio wants a
# 34-character SID, the phone fields must parse as numbers), so these are not
# placeholder gibberish. Hosts carry an explicit ":port" on purpose: encoding
# that colon folds the port into the hostname and Apprise rejects the URL
# outright, which is what shipped until the end-to-end test caught it.
SAMPLES: dict[str, dict] = {
    "ntfy": {"host": "ntfy.sh", "topic": "proxploy-alerts"},
    "gotify": {"host": "gotify.example.com:8080", "token": "AbCdEfGhIjKlMnO"},
    "email": {"host": "smtp.example.com", "user": "alerts@example.com",
              "password": "s3cr3t", "to": "ops@example.com"},
    "telegram": {"bot_token": "123456789:AAHrLHtM3vJqPpAaBbCcDdEeFfGgHhIiJjK",
                 "chat_id": "123456789"},
    "slack": {"token_a": "T1234567890", "token_b": "B1234567890",
              "token_c": "AbCdEfGhIjKlMnOpQrStUvWx", "channel": "#alerts"},
    "discord": {"webhook_id": "1234567890123456789",
                "webhook_token": "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"},
    "webhook": {"host": "127.0.0.1:8123/hooks/proxploy"},
    "matrix": {"host": "matrix.example.com:8448", "user": "proxploy",
               "password": "s3cr3t", "room": "#alerts:matrix.example.com"},
    "mattermost": {"host": "mattermost.example.com:8065", "token": "abcdefghijklmnopqrstuvwxyz"},
    "rocketchat": {"host": "rocketchat.example.com", "user": "proxploy",
                   "password": "s3cr3t", "channel": "alerts"},
    "pushover": {"user_key": "uQiRzpo4DXghDmr9QzzfQu27cmVRsG",
                 "token": "aTokenThatIsThirtyCharsLong123"},
    "pushbullet": {"accesstoken": "o.AbCdEfGhIjKlMnOpQrStUvWxYz01234"},
    "signal": {"host": "signal.example.com:8080", "from_phone": "+15551234567",
               "to": "+15559876543"},
    "msteams": {"host": "prod-00.westus.logic.azure.com",
                "workflow": "abcdef1234567890", "signature": "AbCdEf1234567890"},
    "twilio": {"account_sid": "AC" + "0" * 32, "auth_token": "b" * 32,
               "from_phone": "+15551234567", "to": "+15559876543"},
    "whatsapp": {"token": "EAAB" + "c" * 30, "from_phone_id": "1234567890",
                 "to": "+15559876543"},
    "zulip": {"botname": "proxploy-bot", "organization": "example",
              "token": "AbCdEfGhIjKlMnOpQrStUvWxYz012345"},
    "apprise": {"host": "apprise.example.com", "token": "proxploy"},
    "ses": {"from_email": "alerts@example.com", "access_key_id": "AKIA" + "A" * 16,
            "secret_access_key": "s" * 40, "region": "us-east-1",
            "to": "ops@example.com"},
    "sendgrid": {"apikey": "SG." + "a" * 22, "from_email": "alerts@example.com",
                 "to": "ops@example.com"},
}


def test_every_catalog_kind_has_a_sample():
    assert set(SAMPLES) == set(BY_KIND), "add a SAMPLES row when you add a kind"


@pytest.mark.parametrize("service", CATALOG, ids=lambda s: s.kind)
def test_built_url_is_one_apprise_accepts(service):
    url = build_url(service.kind, SAMPLES[service.kind])
    assert notifier.parses(url), f"Apprise rejected {service.kind}: {url}"


@pytest.mark.parametrize("service", CATALOG, ids=lambda s: s.kind)
def test_kind_survives_the_round_trip_through_kind_for(service):
    """The badge the channel list shows must match the kind the picker offered,
    or a Telegram channel saves and then displays as "webhook"."""
    url = build_url(service.kind, SAMPLES[service.kind])
    assert notifier.kind_for(url) == service.kind
    assert service.scheme in KIND_FROM_SCHEME


def test_missing_required_field_is_refused():
    with pytest.raises(ValueError, match="Topic is required"):
        build_url("ntfy", {"host": "ntfy.sh"})


def test_unknown_kind_is_refused():
    with pytest.raises(ValueError, match="unknown channel kind"):
        build_url("carrier-pigeon", {})


def test_separators_in_a_secret_cannot_rewrite_the_url():
    """A password of "p@ss/word" interpolated verbatim into
    mailto://{user}:{password}@{host} would move the host and build a URL for
    somewhere else entirely. Percent-encoding is the whole defence."""
    url = build_url("email", {**SAMPLES["email"], "password": "p@ss/word"})
    assert "p%40ss%2Fword" in url
    assert url.count("@") == 2  # the user's address, then the userinfo boundary
    assert notifier.parses(url)
