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

import re
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
    # A realistic value, shown in the (i) beside the label. Defaults to the
    # placeholder, because for a plain text field the placeholder already IS
    # the example; spelled out separately only where there is no placeholder
    # to borrow, which is every secret field, since a password box shows none.
    example: str = ""
    # A rule the value must match, in a syntax both Python's re and the
    # browser's RegExp accept, so the server gate and the form's live feedback
    # are literally the same string. Empty means no rule: a password is a
    # password, and rules belong on fields with a known shape rather than on
    # everything for the sake of symmetry.
    #
    # Sourced from Apprise's own published `tokens` metadata wherever it has
    # one, and hand-written where it does not. Never copied blindly: one of
    # Apprise's (zulip's organization, `^[A-Z0-9_-]{1,32})$`) has an
    # unbalanced paren and does not compile.
    pattern: str = ""
    # What a person is told when the rule refuses them. Printing the regex
    # instead is how a form ends up unusable by anyone who did not write it.
    hint: str = ""
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


# Shared shapes. Deliberately permissive: a rule that rejects something which
# actually works is worse than the rubbish it was meant to stop, because the
# operator has no way around it.
_HOST = r"^[A-Za-z0-9][A-Za-z0-9.\-]*(:\d{1,5})?$"
_HOST_HINT = "A hostname or address, optionally with :port. No scheme, no path."
_HOST_PATH = r"^[A-Za-z0-9][A-Za-z0-9.\-]*(:\d{1,5})?(/[^\s]*)?$"
_EMAIL = r"^[^@\s,/]+@[^@\s,/]+\.[^@\s,/]+$"
_EMAIL_HINT = "An email address, like you@example.com."
# A comma is what people expect between addresses, and Apprise unquotes the
# path before splitting it, so an encoded comma reaches the plugin as a comma
# and resolves to the same targets a slash would. The slash came from Apprise's
# published URL templates and was never a requirement; it stays accepted so
# anyone who read the older hint is not punished for it.
_SEP = r"\s*[,/]\s*"
_ONE_EMAIL = r"[^@\s,/]+@[^@\s,/]+\.[^@\s,/]+"
_EMAILS = rf"^{_ONE_EMAIL}({_SEP}{_ONE_EMAIL})*$"
_EMAILS_HINT = "One email address, or several separated by a comma."
_ONE_PHONE = r"\+?[0-9][0-9 ()\-]{5,}"
_PHONE = rf"^{_ONE_PHONE}$"
_PHONE_HINT = "A phone number in international form, like +15551234567."
_PHONES = rf"^{_ONE_PHONE}({_SEP}{_ONE_PHONE})*$"
_PHONES_HINT = "One number in international form, or several separated by a comma."

# No field in the guided form takes a whole URL: every one of them is a single
# component that build_url assembles into one. So a value carrying a scheme is
# always the wrong thing, and it is the specific mistake worth catching by
# name, because a Slack webhook pasted into WhatsApp's token satisfies that
# field's own rule ("at least 20 characters, no spaces") perfectly well. The
# channel then saves, shows a correct badge, and delivers nothing.
#
# Checked before the field's own pattern so the message is about what actually
# went wrong rather than a true but useless remark about character counts.
_URLISH = r"[A-Za-z][A-Za-z0-9+.\-]*://"


CATALOG: tuple[Service, ...] = (
    Service(
        kind="ntfy", scheme="ntfy", label="ntfy",
        template="ntfy://{host}/{topic}",
        setup_url="https://appriseit.com/services/ntfy/",
        fields=(
            Field("host", "Server", default="ntfy.sh", safe=":", example="ntfy.sh",
                  pattern=_HOST, hint=_HOST_HINT,
                  help="Leave as ntfy.sh unless you run your own."),
            Field("topic", "Topic", placeholder="proxploy-alerts",
                  pattern=r"^[A-Za-z0-9_-]{1,64}$",
                  hint="Letters, numbers, dashes and underscores, up to 64 characters."),
        ),
    ),
    Service(
        kind="gotify", scheme="gotify", label="Gotify",
        template="gotify://{host}/{token}",
        setup_url="https://appriseit.com/services/gotify/",
        fields=(
            Field("host", "Server", placeholder="gotify.example.com", safe=":",
                  pattern=_HOST, hint=_HOST_HINT),
            Field("token", "App token", example="AwQ1nT9zLPmExampleKey", secret=True,
                  pattern=r"^[A-Za-z0-9._-]{8,}$",
                  hint="At least 8 characters, no spaces.",
                  help="Gotify calls this the application token."),
        ),
    ),
    Service(
        kind="email", scheme="mailto", label="Email",
        template="mailto://{user}:{password}@{host}/{to}",
        setup_url="https://appriseit.com/services/email/",
        fields=(
            Field("host", "SMTP server", placeholder="smtp.example.com", safe=":",
                  pattern=_HOST, hint=_HOST_HINT),
            Field("user", "Username", placeholder="you@example.com",
                  pattern=r"^\S+$", hint="No spaces."),
            Field("password", "Password", example="an app password, not your login", secret=True),
            Field("to", "Send to", placeholder="you@example.com", safe="/@",
                  pattern=_EMAILS, hint=_EMAILS_HINT,
                  help="Separate several addresses with a comma."),
        ),
    ),
    Service(
        kind="telegram", scheme="tgram", label="Telegram",
        template="tgram://{bot_token}/{chat_id}",
        setup_url="https://appriseit.com/services/telegram/",
        fields=(
            Field("bot_token", "Bot token", example="123456789:AAHrLHtM3vJqPpAaBbCcDdEeFfGgHhIiJjK", secret=True,
                  pattern=r"^[0-9]+:[A-Za-z0-9_-]+$",
                  hint="Digits, a colon, then the key, exactly as BotFather sent it.",
                  help="What BotFather gave you when you created the bot."),
            Field("chat_id", "Chat ID", placeholder="123456789",
                  pattern=r"^(-?[0-9]+|@[A-Za-z0-9_]+)$",
                  hint="A numeric id, or @channelname.",
                  help="Message the bot once first, or it cannot reply to you."),
        ),
    ),
    Service(
        kind="slack", scheme="slack", label="Slack",
        template="slack://{token_a}/{token_b}/{token_c}/{channel}",
        setup_url="https://appriseit.com/services/slack/",
        fields=(
            Field("token_a", "Token A", example="T0000000000", secret=True, placeholder="T0000000000",
                  pattern=r"^[A-Za-z0-9]+$", hint="Letters and numbers only.",
                  help="The three parts of your hooks.slack.com/services/ URL."),
            Field("token_b", "Token B", example="B0000000000", secret=True, placeholder="B0000000000",
                  pattern=r"^[A-Za-z0-9]+$", hint="Letters and numbers only."),
            Field("token_c", "Token C", example="AbCdEfGhIjKlMnOpQrStUvWx", secret=True,
                  pattern=r"^[A-Za-z0-9]+$", hint="Letters and numbers only."),
            Field("channel", "Channel", required=False, placeholder="#alerts",
                  pattern=r"^#?[A-Za-z0-9_-]+$",
                  hint="A channel name, with or without the leading hash."),
        ),
    ),
    Service(
        kind="discord", scheme="discord", label="Discord",
        template="discord://{webhook_id}/{webhook_token}",
        setup_url="https://appriseit.com/services/discord/",
        fields=(
            Field("webhook_id", "Webhook ID", example="1234567890123456789",
                  pattern=r"^[0-9]{15,25}$",
                  hint="The long number from the webhook URL, digits only.",
                  help="From Channel Settings, Integrations, Webhooks: the two "
                       "parts after /api/webhooks/ in the URL."),
            Field("webhook_token", "Webhook token", example="AbCdEfGhIjKlMnOpQrStUvWxYz0123456789", secret=True,
                  pattern=r"^[A-Za-z0-9_-]{20,}$",
                  hint="The long part after the last slash of the webhook URL."),
        ),
    ),
    Service(
        kind="webhook", scheme="json", label="Webhook (JSON)",
        template="json://{host}",
        setup_url="https://appriseit.com/services/json/",
        fields=(
            Field("host", "Address", safe="/:@", placeholder="example.com/hooks/proxploy",
                  pattern=_HOST_PATH,
                  hint="Host and path with no scheme, like example.com/hooks/proxploy.",
                  help="Host and path, no https:// prefix. Use Secure for TLS."),
        ),
    ),
    Service(
        kind="matrix", scheme="matrix", label="Matrix",
        template="matrix://{user}:{password}@{host}/{room}",
        setup_url="https://appriseit.com/services/matrix/",
        fields=(
            Field("host", "Homeserver", placeholder="matrix.org", safe=":",
                  pattern=_HOST, hint=_HOST_HINT),
            Field("user", "Username", example="proxploy"),
            Field("password", "Password", example="the bot account password", secret=True),
            Field("room", "Room", placeholder="#proxploy:matrix.org", safe="/@",
                  pattern=r"^[#!][^\s]+$",
                  hint="A room alias starting with # or a room id starting with !."),
        ),
    ),
    Service(
        kind="mattermost", scheme="mmost", label="Mattermost",
        template="mmost://{host}/{token}",
        setup_url="https://appriseit.com/services/mattermost/",
        fields=(
            Field("host", "Server", placeholder="mattermost.example.com", safe=":",
                  pattern=_HOST, hint=_HOST_HINT),
            Field("token", "Webhook token", example="abcdefghijklmnopqrstuvwxyz", secret=True,
                  pattern=r"^[A-Za-z0-9]{20,}$",
                  hint="Letters and numbers, at least 20 characters."),
        ),
    ),
    Service(
        kind="rocketchat", scheme="rocket", label="Rocket.Chat",
        template="rocket://{user}:{password}@{host}/{channel}",
        setup_url="https://appriseit.com/services/rocketchat/",
        fields=(
            Field("host", "Server", placeholder="rocketchat.example.com", safe=":",
                  pattern=_HOST, hint=_HOST_HINT),
            Field("user", "Username", example="proxploy-bot"),
            Field("password", "Password", example="the bot account password", secret=True),
            Field("channel", "Channel", placeholder="#alerts", safe="/@",
                  pattern=r"^#?[A-Za-z0-9_-]+$",
                  hint="A channel name, with or without the leading hash."),
        ),
    ),
    Service(
        kind="pushover", scheme="pover", label="Pushover",
        template="pover://{user_key}@{token}",
        setup_url="https://appriseit.com/services/pushover/",
        fields=(
            Field("user_key", "User key", example="uQiRzpo4DXghDmr9QzzfQu27cmVRsG", secret=True,
                  pattern=r"^[A-Za-z0-9]{30}$",
                  hint="Exactly 30 letters and numbers.",
                  help="Shown on your Pushover dashboard."),
            Field("token", "Application token", example="aTokenThatIsThirtyCharsLong123", secret=True,
                  pattern=r"^[A-Za-z0-9]{30}$",
                  hint="Exactly 30 letters and numbers."),
        ),
    ),
    Service(
        kind="pushbullet", scheme="pbul", label="Pushbullet",
        template="pbul://{accesstoken}",
        setup_url="https://appriseit.com/services/pushbullet/",
        fields=(
            Field("accesstoken", "Access token", example="o.AbCdEfGhIjKlMnOpQrStUvWxYz0123", secret=True,
                  pattern=r"^[A-Za-z0-9._-]{20,}$",
                  hint="At least 20 characters, no spaces."),
        ),
    ),
    Service(
        kind="signal", scheme="signal", label="Signal",
        template="signal://{host}/{from_phone}/{to}",
        setup_url="https://appriseit.com/services/signal/",
        fields=(
            Field("host", "Signal API server", safe=":",
                  placeholder="signal.example.com",
                  pattern=_HOST, hint=_HOST_HINT,
                  help="Proxploy talks to signal-cli-rest-api, not to Signal directly."),
            Field("from_phone", "From number", placeholder="+15551234567",
                  pattern=_PHONE, hint=_PHONE_HINT),
            Field("to", "Send to", required=False, placeholder="+15559876543",
                  safe="/,", pattern=_PHONES, hint=_PHONES_HINT),
        ),
    ),
    Service(
        kind="msteams", scheme="workflow", label="Microsoft Teams",
        template="workflow://{host}/{workflow}/{signature}",
        setup_url="https://appriseit.com/services/workflows/",
        fields=(
            Field("host", "Host", safe=":",
                  placeholder="prod-00.westus.logic.azure.com",
                  pattern=_HOST, hint=_HOST_HINT,
                  help="The three parts of the Power Automate workflow URL."),
            Field("workflow", "Workflow ID", example="abcdef1234567890", pattern=r"^[A-Za-z0-9_-]+$",
                  hint="Letters, numbers, dashes and underscores only."),
            Field("signature", "Signature", example="AbCdEf1234567890", secret=True,
                  pattern=r"^[A-Za-z0-9_-]+$",
                  hint="Letters, numbers, dashes and underscores only."),
        ),
    ),
    Service(
        kind="twilio", scheme="twilio", label="Twilio SMS",
        template="twilio://{account_sid}:{auth_token}@{from_phone}/{to}",
        setup_url="https://appriseit.com/services/twilio/",
        fields=(
            Field("account_sid", "Account SID",
                  placeholder="AC00000000000000000000000000000000",
                  pattern=r"^AC[a-fA-F0-9]{32}$",
                  hint="Starts with AC, then 32 hex characters."),
            Field("auth_token", "Auth token", example="32 letters and numbers from the console", secret=True,
                  pattern=r"^[a-zA-Z0-9]{32}$",
                  hint="32 letters and numbers."),
            Field("from_phone", "From number", placeholder="+15551234567",
                  pattern=_PHONE, hint=_PHONE_HINT),
            Field("to", "Send to", placeholder="+15559876543", safe="/,",
                  pattern=_PHONES, hint=_PHONES_HINT),
        ),
    ),
    Service(
        kind="whatsapp", scheme="whatsapp", label="WhatsApp",
        template="whatsapp://{token}@{from_phone_id}/{to}",
        setup_url="https://appriseit.com/services/whatsapp/",
        fields=(
            Field("token", "Access token", example="EAABxxxxxxxxxxxxxxxxxxxxxxxxxxxx", secret=True,
                  pattern=r"^\S{20,}$", hint="At least 20 characters, no spaces."),
            Field("from_phone_id", "From phone number ID", example="123456789012345",
                  pattern=r"^[0-9]+$", hint="Digits only.",
                  help="The numeric ID from the Meta app dashboard, not the number."),
            Field("to", "Send to", placeholder="+15559876543", safe="/,",
                  pattern=_PHONES, hint=_PHONES_HINT),
        ),
    ),
    Service(
        kind="zulip", scheme="zulip", label="Zulip",
        template="zulip://{botname}@{organization}/{token}",
        setup_url="https://appriseit.com/services/zulip/",
        fields=(
            Field("botname", "Bot name", placeholder="proxploy-bot",
                  pattern=r"^[A-Za-z0-9_-]{1,32}$",
                  hint="Letters, numbers, dashes and underscores, up to 32 characters."),
            Field("organization", "Organization", placeholder="your-org",
                  pattern=r"^[A-Za-z0-9_-]{1,32}$",
                  hint="Letters, numbers, dashes and underscores, up to 32 characters."),
            Field("token", "Bot token", example="AbCdEfGhIjKlMnOpQrStUvWxYz012345", secret=True,
                  pattern=r"^[A-Za-z0-9]{32}$", hint="32 letters and numbers."),
        ),
    ),
    Service(
        kind="apprise", scheme="apprise", label="Apprise API",
        template="apprise://{host}/{token}",
        setup_url="https://appriseit.com/services/apprise_api/",
        fields=(
            Field("host", "Server", placeholder="apprise.example.com", safe=":",
                  pattern=_HOST, hint=_HOST_HINT),
            Field("token", "Config ID", example="proxploy", secret=True,
                  pattern=r"^[A-Za-z0-9_-]{1,128}$",
                  hint="Letters, numbers, dashes and underscores."),
        ),
    ),
    Service(
        kind="ses", scheme="ses", label="Amazon SES",
        template="ses://{from_email}/{access_key_id}/{secret_access_key}/{region}/{to}",
        setup_url="https://appriseit.com/services/ses/",
        fields=(
            Field("from_email", "From address", safe="@",
                  placeholder="alerts@example.com",
                  pattern=_EMAIL, hint=_EMAIL_HINT),
            Field("access_key_id", "Access key ID", example="AKIAIOSFODNN7EXAMPLE", secret=True,
                  pattern=r"^[A-Z0-9]{16,128}$",
                  hint="Upper case letters and numbers, at least 16 characters."),
            Field("secret_access_key", "Secret access key", example="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", secret=True,
                  pattern=r"^\S{20,}$", hint="At least 20 characters, no spaces."),
            Field("region", "Region", placeholder="us-east-1",
                  pattern=r"^[a-z]{2}-[a-z]+-[0-9]$",
                  hint="An AWS region, like us-east-1."),
            Field("to", "Send to", placeholder="you@example.com", safe="/@",
                  pattern=_EMAILS, hint=_EMAILS_HINT),
        ),
    ),
    Service(
        kind="sendgrid", scheme="sendgrid", label="SendGrid",
        template="sendgrid://{apikey}:{from_email}/{to}",
        setup_url="https://appriseit.com/services/sendgrid/",
        fields=(
            Field("apikey", "API key", example="SG.AbCdEfGhIjKlMnOpQrStUv", secret=True,
                  pattern=r"^SG\.\S+$",
                  hint="A SendGrid key, which starts with SG. and has no spaces."),
            Field("from_email", "From address", safe="@",
                  placeholder="alerts@example.com",
                  pattern=_EMAIL, hint=_EMAIL_HINT,
                  help="Must be a verified sender in SendGrid."),
            Field("to", "Send to", placeholder="you@example.com", safe="/@",
                  pattern=_EMAILS, hint=_EMAILS_HINT),
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
                     "default": f.default, "help": f.help,
                     "example": f.example or f.placeholder,
                     # The client gets the same rule string the server gates
                     # on, so the two can never drift into disagreeing about
                     # what is acceptable.
                     "pattern": f.pattern, "hint": f.hint}
                    for f in s.fields]}
        for s in CATALOG
    ]


def secret_keys(kind: str) -> set[str]:
    """Which of a kind's fields must never travel back to a browser."""
    service = BY_KIND.get(kind)
    return {f.key for f in service.fields if f.secret} if service else set()


def build_url(kind: str, values: dict) -> str:
    """Assemble one Apprise URL from a kind and its filled-in fields.

    Raises ValueError for an unknown kind, a missing required field, or a
    value that fails its field's rule. Does NOT check that the result is a URL
    Apprise accepts, that is notifier.parses()'s job and the caller does both.

    Both gates matter, and neither replaces the other. Apprise's parser is
    strict for some plugins and indifferent to others: it rejects a malformed
    Twilio SID and happily accepts "not-an-email-at-all" as a mail recipient.
    """
    service = BY_KIND.get(kind)
    if service is None:
        raise ValueError(f"unknown channel kind: {kind!r}")

    parts = {}
    for f in service.fields:
        raw = str(values.get(f.key) or "").strip() or f.default
        if not raw and f.required:
            raise ValueError(f"{f.label} is required for {service.label}.")
        if raw and re.search(_URLISH, raw):
            raise ValueError(
                f"{f.label} takes a single value, not a whole URL. If that is "
                f"a URL for another service, add that service instead.")
        if raw and f.pattern and not re.match(f.pattern, raw):
            # Name the field and say what it wants. Printing the pattern here
            # is how a form becomes unusable by anyone who did not write it.
            raise ValueError(f"{f.label} is not right. {f.hint}")
        # safe="" everywhere else is the point: a password of "p@ss/word"
        # interpolated verbatim into "{user}:{password}@{host}" moves the
        # host and silently builds a URL for somewhere else entirely.
        parts[f.key] = quote(raw, safe=f.safe)

    # Optional fields are all trailing segments, so an empty one leaves a
    # dangling separator rather than a hole in the middle.
    return service.template.format(**parts).rstrip("/")
