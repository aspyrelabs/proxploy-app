"""The guided half of adding a notification channel (Settings -> Notifications).

Apprise reaches 142 services and `Apprise().details()` describes every field of
all of them, but that description is exhaustive rather than guided: ntfy alone
exposes eight fields (host, port, user, password, token, topic, targets,
schema) and nothing in it says which combination a first-time user actually
needs, which is one topic. A form rendered straight from `details()` is harder
to fill in than the raw URL box it would replace.

So this table is the happy path for each kind we name, hand-written and then
checked against Apprise's own parser by tests/test_notification_catalog.py.
Every template here came from the `templates` list Apprise publishes for that
plugin, not from memory.

The raw-URL box in the UI is not replaced by this, it stays as the escape
hatch for the 122 services this table does not cover and for anyone who
already knows the syntax. `url` on the create endpoint is untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    required: bool = True
    secret: bool = False
    placeholder: str = ""
    default: str = ""
    help: str = ""
    # Characters this field is allowed to carry through unencoded, because
    # the plugin parses them as structure rather than as content: "/" for a
    # webhook path or a list of recipients, "@" for an address that Apprise
    # reads whole. Everything not named here is percent-encoded, which is what
    # keeps a password containing "@" or "/" from silently rewriting the URL
    # into a different host. Default: encode everything.
    safe: str = ""


@dataclass(frozen=True)
class Service:
    kind: str
    scheme: str
    label: str
    template: str
    fields: tuple[Field, ...]
    setup_url: str


CATALOG: tuple[Service, ...] = (
    Service(
        kind="ntfy", scheme="ntfy", label="ntfy",
        template="ntfy://{host}/{topic}",
        setup_url="https://appriseit.com/services/ntfy/",
        fields=(
            Field("host", "Server", default="ntfy.sh",
                  help="Leave as ntfy.sh unless you run your own."),
            Field("topic", "Topic", placeholder="proxploy-alerts"),
        ),
    ),
    Service(
        kind="gotify", scheme="gotify", label="Gotify",
        template="gotify://{host}/{token}",
        setup_url="https://appriseit.com/services/gotify/",
        fields=(
            Field("host", "Server", placeholder="gotify.example.com"),
            Field("token", "App token", secret=True,
                  help="Gotify calls this the application token."),
        ),
    ),
    Service(
        kind="email", scheme="mailto", label="Email",
        template="mailto://{user}:{password}@{host}/{to}",
        setup_url="https://appriseit.com/services/email/",
        fields=(
            Field("host", "SMTP server", placeholder="smtp.example.com"),
            Field("user", "Username", placeholder="you@example.com"),
            Field("password", "Password", secret=True),
            Field("to", "Send to", placeholder="you@example.com", safe="/@",
                  help="Separate several addresses with a slash."),
        ),
    ),
    Service(
        kind="telegram", scheme="tgram", label="Telegram",
        template="tgram://{bot_token}/{chat_id}",
        setup_url="https://appriseit.com/services/telegram/",
        fields=(
            Field("bot_token", "Bot token", secret=True,
                  help="What BotFather gave you when you created the bot."),
            Field("chat_id", "Chat ID", placeholder="123456789",
                  help="Message the bot once first, or it cannot reply to you."),
        ),
    ),
    Service(
        kind="slack", scheme="slack", label="Slack",
        template="slack://{token_a}/{token_b}/{token_c}/{channel}",
        setup_url="https://appriseit.com/services/slack/",
        fields=(
            Field("token_a", "Token A", secret=True, placeholder="T0000000000",
                  help="The three parts of your hooks.slack.com/services/ URL."),
            Field("token_b", "Token B", secret=True, placeholder="B0000000000"),
            Field("token_c", "Token C", secret=True),
            Field("channel", "Channel", required=False, placeholder="#alerts"),
        ),
    ),
    Service(
        kind="discord", scheme="discord", label="Discord",
        template="discord://{webhook_id}/{webhook_token}",
        setup_url="https://appriseit.com/services/discord/",
        fields=(
            Field("webhook_id", "Webhook ID",
                  help="From Channel Settings, Integrations, Webhooks: the two "
                       "parts after /api/webhooks/ in the URL."),
            Field("webhook_token", "Webhook token", secret=True),
        ),
    ),
    Service(
        kind="webhook", scheme="json", label="Webhook (JSON)",
        template="json://{host}",
        setup_url="https://appriseit.com/services/json/",
        fields=(
            Field("host", "Address", safe="/@", placeholder="example.com/hooks/proxploy",
                  help="Host and path, no https:// prefix. Use Secure for TLS."),
        ),
    ),
    Service(
        kind="matrix", scheme="matrix", label="Matrix",
        template="matrix://{user}:{password}@{host}/{room}",
        setup_url="https://appriseit.com/services/matrix/",
        fields=(
            Field("host", "Homeserver", placeholder="matrix.org"),
            Field("user", "Username"),
            Field("password", "Password", secret=True),
            Field("room", "Room", placeholder="#proxploy:matrix.org", safe="/@"),
        ),
    ),
    Service(
        kind="mattermost", scheme="mmost", label="Mattermost",
        template="mmost://{host}/{token}",
        setup_url="https://appriseit.com/services/mattermost/",
        fields=(
            Field("host", "Server", placeholder="mattermost.example.com"),
            Field("token", "Webhook token", secret=True),
        ),
    ),
    Service(
        kind="rocketchat", scheme="rocket", label="Rocket.Chat",
        template="rocket://{user}:{password}@{host}/{channel}",
        setup_url="https://appriseit.com/services/rocketchat/",
        fields=(
            Field("host", "Server", placeholder="rocketchat.example.com"),
            Field("user", "Username"),
            Field("password", "Password", secret=True),
            Field("channel", "Channel", placeholder="#alerts", safe="/@"),
        ),
    ),
    Service(
        kind="pushover", scheme="pover", label="Pushover",
        template="pover://{user_key}@{token}",
        setup_url="https://appriseit.com/services/pushover/",
        fields=(
            Field("user_key", "User key", secret=True,
                  help="Shown on your Pushover dashboard."),
            Field("token", "Application token", secret=True),
        ),
    ),
    Service(
        kind="pushbullet", scheme="pbul", label="Pushbullet",
        template="pbul://{accesstoken}",
        setup_url="https://appriseit.com/services/pushbullet/",
        fields=(
            Field("accesstoken", "Access token", secret=True),
        ),
    ),
    Service(
        kind="signal", scheme="signal", label="Signal",
        template="signal://{host}/{from_phone}/{to}",
        setup_url="https://appriseit.com/services/signal/",
        fields=(
            Field("host", "Signal API server", placeholder="signal.example.com",
                  help="Proxploy talks to signal-cli-rest-api, not to Signal directly."),
            Field("from_phone", "From number", placeholder="+15551234567"),
            Field("to", "Send to", required=False, placeholder="+15559876543", safe="/"),
        ),
    ),
    Service(
        kind="msteams", scheme="workflow", label="Microsoft Teams",
        template="workflow://{host}/{workflow}/{signature}",
        setup_url="https://appriseit.com/services/workflows/",
        fields=(
            Field("host", "Host", placeholder="prod-00.westus.logic.azure.com",
                  help="The three parts of the Power Automate workflow URL."),
            Field("workflow", "Workflow ID"),
            Field("signature", "Signature", secret=True),
        ),
    ),
    Service(
        kind="twilio", scheme="twilio", label="Twilio SMS",
        template="twilio://{account_sid}:{auth_token}@{from_phone}/{to}",
        setup_url="https://appriseit.com/services/twilio/",
        fields=(
            Field("account_sid", "Account SID", placeholder="AC00000000000000000000000000000000"),
            Field("auth_token", "Auth token", secret=True),
            Field("from_phone", "From number", placeholder="+15551234567"),
            Field("to", "Send to", placeholder="+15559876543", safe="/"),
        ),
    ),
    Service(
        kind="whatsapp", scheme="whatsapp", label="WhatsApp",
        template="whatsapp://{token}@{from_phone_id}/{to}",
        setup_url="https://appriseit.com/services/whatsapp/",
        fields=(
            Field("token", "Access token", secret=True),
            Field("from_phone_id", "From phone number ID",
                  help="The numeric ID from the Meta app dashboard, not the number."),
            Field("to", "Send to", placeholder="+15559876543", safe="/"),
        ),
    ),
    Service(
        kind="zulip", scheme="zulip", label="Zulip",
        template="zulip://{botname}@{organization}/{token}",
        setup_url="https://appriseit.com/services/zulip/",
        fields=(
            Field("botname", "Bot name", placeholder="proxploy-bot"),
            Field("organization", "Organization", placeholder="your-org"),
            Field("token", "Bot token", secret=True),
        ),
    ),
    Service(
        kind="apprise", scheme="apprise", label="Apprise API",
        template="apprise://{host}/{token}",
        setup_url="https://appriseit.com/services/apprise_api/",
        fields=(
            Field("host", "Server", placeholder="apprise.example.com"),
            Field("token", "Config ID", secret=True),
        ),
    ),
    Service(
        kind="ses", scheme="ses", label="Amazon SES",
        template="ses://{from_email}/{access_key_id}/{secret_access_key}/{region}/{to}",
        setup_url="https://appriseit.com/services/ses/",
        fields=(
            Field("from_email", "From address", safe="@",
                  placeholder="alerts@example.com"),
            Field("access_key_id", "Access key ID", secret=True),
            Field("secret_access_key", "Secret access key", secret=True),
            Field("region", "Region", placeholder="us-east-1"),
            Field("to", "Send to", placeholder="you@example.com", safe="/@"),
        ),
    ),
    Service(
        kind="sendgrid", scheme="sendgrid", label="SendGrid",
        template="sendgrid://{apikey}:{from_email}/{to}",
        setup_url="https://appriseit.com/services/sendgrid/",
        fields=(
            Field("apikey", "API key", secret=True),
            Field("from_email", "From address", safe="@",
                  placeholder="alerts@example.com",
                  help="Must be a verified sender in SendGrid."),
            Field("to", "Send to", placeholder="you@example.com", safe="/@"),
        ),
    ),
)

BY_KIND = {s.kind: s for s in CATALOG}


def public_catalog() -> list[dict]:
    """What GET /notifications/kinds returns. Deliberately omits `template`:
    the client needs the questions, not the string they get assembled into,
    and keeping assembly server-side is what makes the percent-encoding in
    build_url() the only encoding that ever happens."""
    return [
        {"kind": s.kind, "label": s.label, "setup_url": s.setup_url,
         "fields": [{"key": f.key, "label": f.label, "required": f.required,
                     "secret": f.secret, "placeholder": f.placeholder,
                     "default": f.default, "help": f.help}
                    for f in s.fields]}
        for s in CATALOG
    ]


def build_url(kind: str, values: dict) -> str:
    """Assemble one Apprise URL from a kind and its filled-in fields.

    Raises ValueError for an unknown kind or a missing required field. Does
    NOT check that the result is a URL Apprise accepts, that is
    notifier.parses()'s job and the caller does both.
    """
    service = BY_KIND.get(kind)
    if service is None:
        raise ValueError(f"unknown channel kind: {kind!r}")

    parts = {}
    for f in service.fields:
        raw = str(values.get(f.key) or "").strip() or f.default
        if not raw and f.required:
            raise ValueError(f"{f.label} is required for {service.label}.")
        # safe="" everywhere else is the point: a password of "p@ss/word"
        # interpolated verbatim into "{user}:{password}@{host}" moves the
        # host and silently builds a URL for somewhere else entirely.
        parts[f.key] = quote(raw, safe=f.safe)

    # Optional fields are all trailing segments, so an empty one leaves a
    # dangling separator rather than a hole in the middle.
    return service.template.format(**parts).rstrip("/")
