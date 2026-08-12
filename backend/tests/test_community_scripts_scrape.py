"""Best-effort community-scripts.org enrichment (catalog expansion plan,
decision 1). Every test here proves the SAME thing from a different angle:
nothing about this module may ever be allowed to break the catalog. A
synthetic fixture stands in for the real site's undocumented RSC flight
payload, no live network (Respect the GitHub-adjacent rate-limit discipline:
this scrapes a different host entirely, but hammering someone else's
production site to test a parser is still not something to do)."""
import json

import httpx

from proxploy.models import CatalogEntry
from proxploy.services.community_scripts_scrape import apply_enrichment, fetch_enrichment
from tests.support import make_db


def _flight_html(records: list[dict]) -> str:
    """Builds the same `self.__next_f.push([1, "<escaped>"])` shape the real
    site's Next.js RSC hydration payload uses (investigation §4): a stream
    chunk prefixed with an index (`1c:`), then a JSON array literal, the
    whole thing double-escaped as a JS string literal inside a <script> tag."""
    chunk = f"1c:{json.dumps(records)}\n"
    escaped = json.dumps(chunk)
    return f'<html><body><script>self.__next_f.push([1,{escaped}])</script></body></html>'


REDIS_RECORD = {
    "slug": "redis", "name": "Redis", "type": "lxc", "is_dev": False,
    "description": "Redis is an open-source in-memory data store.",
    "logo": "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/redis.webp",
    "expand": {"categories": [{"name": "Databases"}]},
}
DEV_RECORD = {"slug": "wip-app", "name": "WIP", "type": "lxc", "is_dev": True,
             "description": "not production yet"}


def test_fetch_enrichment_parses_a_realistic_flight_payload(monkeypatch):
    html = _flight_html([REDIS_RECORD])
    monkeypatch.setattr("proxploy.services.community_scripts_scrape._get",
                        lambda timeout: httpx.Response(200, text=html))

    mapping = fetch_enrichment()

    assert mapping == {"redis": {
        "name": "Redis", "description": "Redis is an open-source in-memory data store.",
        "logo": "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/redis.webp",
        "category": "Databases",
    }}


def test_fetch_enrichment_excludes_dev_records(monkeypatch):
    html = _flight_html([REDIS_RECORD, DEV_RECORD])
    monkeypatch.setattr("proxploy.services.community_scripts_scrape._get",
                        lambda timeout: httpx.Response(200, text=html))

    mapping = fetch_enrichment()

    assert "wip-app" not in mapping
    assert "redis" in mapping


def test_fetch_enrichment_returns_none_on_a_403(monkeypatch):
    """The real site 403s a bot-shaped User-Agent (investigation §4). This
    must degrade to "no enrichment", never raise."""
    monkeypatch.setattr("proxploy.services.community_scripts_scrape._get",
                        lambda timeout: httpx.Response(403))

    assert fetch_enrichment() is None


def test_fetch_enrichment_returns_none_on_a_timeout(monkeypatch):
    def raises(timeout):
        raise httpx.TimeoutException("timed out")
    monkeypatch.setattr("proxploy.services.community_scripts_scrape._get", raises)

    assert fetch_enrichment() is None


def test_fetch_enrichment_returns_none_on_a_connection_error(monkeypatch):
    def raises(timeout):
        raise httpx.ConnectError("connection refused")
    monkeypatch.setattr("proxploy.services.community_scripts_scrape._get", raises)

    assert fetch_enrichment() is None


def test_fetch_enrichment_degrades_on_a_shape_change(monkeypatch):
    """An undocumented internal can change shape on any deploy with no
    warning (investigation §4). Garbage HTML with no recognizable flight
    chunks must yield an empty mapping, not an exception."""
    monkeypatch.setattr("proxploy.services.community_scripts_scrape._get",
                        lambda timeout: httpx.Response(200, text="<html>totally different now</html>"))

    mapping = fetch_enrichment()

    assert mapping == {}


def test_fetch_enrichment_tolerates_one_malformed_record_among_good_ones(monkeypatch):
    malformed = {"slug": 123, "type": "lxc"}  # slug is not even a string
    html = _flight_html([REDIS_RECORD, malformed])
    monkeypatch.setattr("proxploy.services.community_scripts_scrape._get",
                        lambda timeout: httpx.Response(200, text=html))

    mapping = fetch_enrichment()

    assert "redis" in mapping
    assert len(mapping) == 1


# --- apply_enrichment: decoration only, never touches installability -------

def test_apply_enrichment_updates_description_logo_and_category(tmp_path):
    db = make_db(tmp_path)
    db.add(CatalogEntry(slug="redis", entry_type="ct", name="Redis",
                        category="Uncategorized", installable=True))
    db.commit()

    n = apply_enrichment(db, {"redis": {
        "name": "Redis", "description": "desc", "logo": "https://x/redis.webp",
        "category": "Databases",
    }})

    assert n == 1
    row = db.query(CatalogEntry).filter_by(slug="redis").one()
    assert row.description == "desc"
    assert row.icon_url == "https://x/redis.webp"
    assert row.category == "Databases"
    assert row.scraped_at is not None
    assert row.installable is True  # decoration only; never touched


def test_apply_enrichment_ignores_a_slug_it_does_not_have(tmp_path):
    db = make_db(tmp_path)
    db.add(CatalogEntry(slug="redis", entry_type="ct", installable=True))
    db.commit()

    n = apply_enrichment(db, {"unknown-slug": {"description": "x"}})

    assert n == 0


def test_apply_enrichment_never_touches_a_non_ct_row(tmp_path):
    """The scrape's own `type` field can disagree with ours on the 4
    dual-variant slugs (investigation §2); directory placement wins, so
    enrichment must never cross into an addon/vm/pve/turnkey row."""
    db = make_db(tmp_path)
    db.add(CatalogEntry(slug="dockge-addon", entry_type="addon", installable=False))
    db.commit()

    n = apply_enrichment(db, {"dockge-addon": {"description": "should not land"}})

    assert n == 0
    row = db.query(CatalogEntry).filter_by(slug="dockge-addon").one()
    assert row.description is None


def test_apply_enrichment_with_none_mapping_is_a_no_op(tmp_path):
    db = make_db(tmp_path)
    db.add(CatalogEntry(slug="redis", entry_type="ct", installable=True))
    db.commit()

    assert apply_enrichment(db, None) == 0
