"""Local icon mirror: the half of "instant and works offline" that was
missing. The metadata already lived in SQLite and rendered cache-first; every
card still fetched cdn.jsdelivr.net at render time, so a firewalled host
showed 556 initials tiles.

Everything here is offline: the CDN is faked at `catalog_icons._fetch`, so no
test in this file touches the network.
"""
from datetime import timedelta

import httpx

from proxploy.models import CatalogEntry, utcnow
from proxploy.services import catalog_icons as ci
from tests.support import make_db

WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 fake-bytes"
PNG = b"\x89PNG\r\n\x1a\n fake-bytes"
PLEX_URL = "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/plex.webp"


def fake_cdn(bodies=None, status=200, etag='"v1"', seen=None, boom=False):
    """Stands in for catalog_icons._fetch. Records every request so the
    steady-state cost can be asserted rather than assumed."""
    bodies = bodies if bodies is not None else {}

    def fake(url, headers=None, **kw):
        if seen is not None:
            seen.append((url, dict(headers or {})))
        if boom:
            raise httpx.ConnectError("no route to host")
        if status != 200:
            return httpx.Response(status)
        if headers and headers.get("If-None-Match") == etag:
            return httpx.Response(304)
        body = bodies.get(url, WEBP)
        return httpx.Response(200, content=body,
                              headers={"ETag": etag} if etag else {})
    return fake


def _seed(db, slug="plex", url=PLEX_URL, **kw):
    row = CatalogEntry(slug=slug, entry_type="ct", name=slug.title(),
                       icon_url=url, **kw)
    db.add(row)
    db.commit()
    return row


# --- the cache itself -------------------------------------------------------

def test_an_icon_is_downloaded_into_the_durable_data_dir(tmp_path, monkeypatch):
    """data_dir/icons, beside proxploy.db and master.key. NOT /tmp: the whole
    point is surviving a reboot, and a cache in /tmp is empty exactly when an
    offline host needs it most."""
    db = make_db(tmp_path)
    _seed(db)
    monkeypatch.setattr(ci, "_fetch", fake_cdn())

    out = ci.sync_icons(db, tmp_path)

    assert out["ok"] and out["cached"] == 1
    path = tmp_path / "icons" / "plex.webp"
    assert path.read_bytes() == WEBP
    row = db.query(CatalogEntry).filter_by(slug="plex").one()
    assert row.icon_cache_path == "plex.webp"
    assert row.icon_cache_source == PLEX_URL
    assert row.icon_cache_etag == '"v1"'
    assert row.icon_cached_at is not None
    # The column still holds UPSTREAM's URL: catalog_metadata owns it, this
    # module owns the mirror beside it.
    assert row.icon_url == PLEX_URL


def test_a_steady_state_sync_makes_no_requests_at_all(tmp_path, monkeypatch):
    """This runs every 6 hours. Re-downloading 549 files each time, or even
    revalidating all 549, would be someone else's bandwidth spent to learn
    nothing."""
    db = make_db(tmp_path)
    for slug in ("plex", "jellyfin", "redis"):
        _seed(db, slug, f"https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/{slug}.webp")
    seen: list = []
    monkeypatch.setattr(ci, "_fetch", fake_cdn(seen=seen))
    assert ci.sync_icons(db, tmp_path)["cached"] == 3
    seen.clear()

    out = ci.sync_icons(db, tmp_path)

    assert seen == []
    assert out["requests"] == 0 and out["skipped"] == 3 and out["cached"] == 0


def test_a_changed_upstream_url_refetches_rather_than_serving_a_stale_logo(
        tmp_path, monkeypatch):
    """Staleness must not be sticky. `icon_cache_source` is what makes a logo
    change detectable at all: when it stops matching icon_url, we refetch."""
    db = make_db(tmp_path)
    row = _seed(db)
    monkeypatch.setattr(ci, "_fetch", fake_cdn())
    ci.sync_icons(db, tmp_path)

    new_url = "https://cdn.jsdelivr.net/gh/selfhst/icons@main/png/plex.png"
    db.query(CatalogEntry).filter_by(slug="plex").one().icon_url = new_url
    db.commit()
    monkeypatch.setattr(ci, "_fetch", fake_cdn(bodies={new_url: PNG}))
    out = ci.sync_icons(db, tmp_path)

    assert out["cached"] == 1
    row = db.query(CatalogEntry).filter_by(slug="plex").one()
    assert row.icon_cache_path == "plex.png"
    assert (tmp_path / "icons" / "plex.png").read_bytes() == PNG


def test_a_stale_entry_revalidates_conditionally_and_304s_cost_no_bytes(
        tmp_path, monkeypatch):
    """Past the revalidate window we ask, with If-None-Match, so upstream can
    answer 304 and send no body."""
    db = make_db(tmp_path)
    _seed(db)
    monkeypatch.setattr(ci, "_fetch", fake_cdn())
    ci.sync_icons(db, tmp_path)
    row = db.query(CatalogEntry).filter_by(slug="plex").one()
    stale_stamp = utcnow() - ci.REVALIDATE_AFTER - timedelta(days=1)
    row.icon_cached_at = stale_stamp
    db.commit()
    seen: list = []
    monkeypatch.setattr(ci, "_fetch", fake_cdn(seen=seen))

    out = ci.sync_icons(db, tmp_path)

    assert out["unchanged"] == 1 and out["cached"] == 0
    assert seen and seen[0][1].get("If-None-Match") == '"v1"'
    # ...and the freshness stamp moved, so the next 30 days cost nothing.
    assert db.query(CatalogEntry).filter_by(
        slug="plex").one().icon_cached_at > stale_stamp


# --- failure never empties the cache ---------------------------------------

def test_a_failed_download_leaves_the_existing_file_and_row_intact(tmp_path,
                                                                   monkeypatch):
    """Never delete a good cached icon because a refetch failed."""
    db = make_db(tmp_path)
    _seed(db)
    monkeypatch.setattr(ci, "_fetch", fake_cdn())
    ci.sync_icons(db, tmp_path)
    before = db.query(CatalogEntry).filter_by(slug="plex").one()
    snapshot = (before.icon_cache_path, before.icon_cache_source,
                before.icon_cache_etag, before.icon_url)

    # Upstream moved the URL AND the new one is dead, so a fetch is attempted
    # and fails: the worst realistic case.
    db.query(CatalogEntry).filter_by(slug="plex").one().icon_url = \
        "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/plex-v2.webp"
    db.commit()
    monkeypatch.setattr(ci, "_fetch", fake_cdn(status=503))
    out = ci.sync_icons(db, tmp_path)

    assert out["ok"] and out["failed"] == 1 and out["cached"] == 0
    row = db.query(CatalogEntry).filter_by(slug="plex").one()
    assert row.icon_cache_path == "plex.webp"
    assert (tmp_path / "icons" / "plex.webp").read_bytes() == WEBP
    assert (row.icon_cache_path, row.icon_cache_source,
            row.icon_cache_etag) == snapshot[:3]


def test_a_total_network_outage_leaves_every_icon_exactly_as_it_was(tmp_path,
                                                                    monkeypatch):
    """The offline case this whole module exists for, applied to itself: a
    sync with no network must be a no-op, never an emptied cache."""
    db = make_db(tmp_path)
    for slug in ("plex", "jellyfin"):
        _seed(db, slug, f"https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/{slug}.webp")
    monkeypatch.setattr(ci, "_fetch", fake_cdn())
    ci.sync_icons(db, tmp_path)
    before = {r.slug: (r.icon_cache_path, r.icon_url, r.icon_cache_etag)
              for r in db.query(CatalogEntry).all()}
    files = {p.name: p.read_bytes() for p in (tmp_path / "icons").iterdir()}
    # Force both rows back into the fetch path, then take the network away.
    for r in db.query(CatalogEntry).all():
        r.icon_cache_source = "https://example.invalid/moved.webp"
    db.commit()
    monkeypatch.setattr(ci, "_fetch", fake_cdn(boom=True))

    out = ci.sync_icons(db, tmp_path)

    assert out["ok"] and out["failed"] == 2 and out["cached"] == 0
    db.expire_all()
    assert {r.slug: (r.icon_cache_path, r.icon_url, r.icon_cache_etag)
            for r in db.query(CatalogEntry).all()} == before
    assert {p.name: p.read_bytes() for p in (tmp_path / "icons").iterdir()} == files


def test_a_url_with_no_serveable_extension_is_left_to_upstream(tmp_path, monkeypatch):
    """One real icon in the corpus is
    avatars.githubusercontent.com/u/127616157?s=200&v=4, which has no
    extension at all. It keeps its upstream URL rather than becoming a
    file we cannot name or a 404 tile."""
    db = make_db(tmp_path)
    _seed(db, "espconnect", "https://avatars.githubusercontent.com/u/127616157?s=200&v=4")
    seen: list = []
    monkeypatch.setattr(ci, "_fetch", fake_cdn(seen=seen))

    out = ci.sync_icons(db, tmp_path)

    assert seen == [] and out["cached"] == 0
    row = db.query(CatalogEntry).filter_by(slug="espconnect").one()
    assert row.icon_cache_path is None
    assert row.icon_url.startswith("https://avatars.githubusercontent.com/")


def test_an_oversized_body_is_refused(tmp_path, monkeypatch):
    """A logo that arrives larger than the cap is not a logo, and one bad URL
    must not fill the data dir the DB lives in."""
    db = make_db(tmp_path)
    _seed(db)
    monkeypatch.setattr(ci, "_fetch",
                        fake_cdn(bodies={PLEX_URL: b"x" * (ci.MAX_ICON_BYTES + 1)}))

    out = ci.sync_icons(db, tmp_path)

    assert out["failed"] == 1 and out["cached"] == 0
    assert not (tmp_path / "icons" / "plex.webp").exists()


def test_no_fetch_ever_touches_api_github_com(tmp_path, monkeypatch):
    """The refresh's flat 2-call GitHub API ceiling is absolute. A CDN and
    raw.githubusercontent.com are not the GitHub API."""
    db = make_db(tmp_path)
    _seed(db)
    _seed(db, "degoog",
          "https://raw.githubusercontent.com/fccview/degoog/main/src/public/images/x.png")
    seen: list = []
    monkeypatch.setattr(ci, "_fetch", fake_cdn(seen=seen))

    ci.sync_icons(db, tmp_path)

    assert seen and not any("api.github.com" in url for url, _h in seen)


# --- filename construction is not attacker controlled -----------------------

def test_the_cached_filename_comes_from_our_slug_and_an_allowlist():
    assert ci.cache_filename("plex", PLEX_URL) == "plex.webp"
    assert ci.cache_filename("plex", "https://x/y.PNG") == "plex.png"
    # An extension we do not serve, or none at all, is declined outright.
    assert ci.cache_filename("plex", "https://x/y.exe") is None
    assert ci.cache_filename("plex", "https://x/y") is None
    # Nothing upstream puts in the URL can reach the filesystem as a path.
    assert ci.cache_filename("plex", "https://x/../../etc/passwd.png") == "plex.png"
    # ...and a slug shaped like a path is refused rather than sanitised.
    for bad in ("../evil", "a/b", "a\\b", ".hidden", ""):
        assert ci.cache_filename(bad, PLEX_URL) is None, bad


# --- attribution ------------------------------------------------------------

def test_cc_by_attribution_rides_on_the_response_that_redistributes():
    """537 of 549 icons come from selfhst/icons, which is CC BY 4.0. The
    attribution condition attaches to SHARING the material, and serving a
    cached copy from the operator's node is sharing it, so the credit belongs
    on that response and not only in a comment in this repo."""
    headers = ci.attribution_headers(PLEX_URL)

    assert 'rel="license"' in headers["Link"]
    assert "creativecommons.org/licenses/by/4.0/" in headers["Link"]
    assert "selfh.st/icons" in headers["Link"]
    # A vendor's own logo carries no CC BY grant, so it gets no CC BY credit.
    assert ci.attribution_headers("https://getgrav.org/user/pages/media/x.svg") == {}
    assert ci.attribution_headers(None) == {}
