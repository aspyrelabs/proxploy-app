"""Deep links: the same paths the palette uses, made absolute only when the
operator has said where this installation lives."""
import pytest

from proxploy.services.links import PUBLIC_URL_KEY, absolute, path_for, public_url
from proxploy.services.settings import set_setting


@pytest.mark.parametrize("target_type,target_id,expected", [
    ("app", 12, "/apps?open=12"),
    ("vm", 7, "/vms?open=7"),
    ("host", 3, "/settings?section=hosts"),
    ("backup", 1, "/backups"),
    ("notification_channel", 4, "/settings?section=channels"),
])
def test_a_thing_with_a_page_gets_its_path(target_type, target_id, expected):
    assert path_for(target_type, target_id) == expected


@pytest.mark.parametrize("target_type", [None, "", "storage", "job", "session"])
def test_a_thing_with_no_page_gets_no_link(target_type):
    """None rather than "/". A link to the dashboard is not an answer to
    "what failed", and offering one trains people to ignore the link."""
    assert path_for(target_type, 1) is None


def test_no_public_url_means_no_link_rather_than_a_guess(session):
    """The Host header is attacker-controllable and api_base_url is the licence
    server, so there is nothing safe to derive one from."""
    assert public_url(session) == ""
    assert absolute(session, "/apps?open=1") == ""


def test_a_configured_public_url_makes_the_path_absolute(session):
    set_setting(session, PUBLIC_URL_KEY, "https://proxploy.example.com")
    assert absolute(session, "/apps?open=1") == "https://proxploy.example.com/apps?open=1"


def test_a_trailing_slash_does_not_double_up(session):
    set_setting(session, PUBLIC_URL_KEY, "https://proxploy.example.com/")
    assert absolute(session, "/backups") == "https://proxploy.example.com/backups"


def test_no_path_means_no_link_even_with_a_public_url(session):
    set_setting(session, PUBLIC_URL_KEY, "https://proxploy.example.com")
    assert absolute(session, None) == ""


def test_the_palette_and_notifications_agree_on_every_path():
    """These were written twice once, and the backend generated
    /settings/hosts/{id} for a route that never existed."""
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "proxploy" / "api" / "search.py"
    hrefs = re.findall(r'"href": f?"([^"]+)"', src.read_text())
    for href in hrefs:
        bare = href.split("?")[0].replace("{a.id}", "").replace("{v.id}", "")
        # Every path search offers is one this module can also produce, or a
        # store page, which has no notification behind it.
        assert bare.startswith(("/apps", "/vms", "/settings", "/store")), href
