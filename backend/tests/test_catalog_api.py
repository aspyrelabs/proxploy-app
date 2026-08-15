import httpx

from proxploy.models import CatalogEntry, utcnow
from tests.conftest import client  # noqa: F401 fixture


def _seed_entry(db, **overrides):
    row = CatalogEntry(slug="redis", name="Redis", category="Databases",
                       installable=True, unsupported_reason=None, **overrides)
    db.add(row)
    db.commit()
    return row


def test_list_catalog_requires_auth(client):
    r = client.get("/api/v1/catalog")
    assert r.status_code == 401


def test_list_and_get_catalog_entry(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_entry(db)
    r = client.get("/api/v1/catalog")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1 and body[0]["slug"] == "redis"

    r = client.get("/api/v1/catalog/redis")
    assert r.status_code == 200 and r.json()["name"] == "Redis"

    r = client.get("/api/v1/catalog/does-not-exist")
    assert r.status_code == 404


def test_category_and_query_filters(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_entry(db)
        db.add(CatalogEntry(slug="grafana", name="Grafana", category="Monitoring", installable=True))
        db.commit()
    assert len(client.get("/api/v1/catalog?category=Monitoring").json()) == 1
    assert len(client.get("/api/v1/catalog?q=redis").json()) == 1
    assert len(client.get("/api/v1/catalog?q=nomatch").json()) == 0


def test_refresh_enqueues_a_job(client, csrf_header, bootstrap_admin, monkeypatch):
    bootstrap_admin(client)
    r = client.post("/api/v1/catalog/refresh", headers=csrf_header(client))
    assert r.status_code == 202
    job = r.json()["job"]
    assert job["kind"] == "catalog.refresh"


SHA = "d7bc6b59676456f7a8b3a20f24c3ca589d7fe2f6"
REDIS_CT = 'APP="Redis"\nbuild_container\n'
REDIS_INSTALL = 'msg_info "Setting up Redis"\n$STD apt install -y redis\n'


def _seed_unclassified_ct(db, slug="redis", sha=SHA):
    row = CatalogEntry(slug=slug, entry_type="ct", upstream_sha=sha,
                       script_path=f"ct/{slug}.sh", installable=None)
    db.add(row)
    db.commit()
    return row


def test_opening_a_card_lazily_classifies_it(client, csrf_header, bootstrap_admin, monkeypatch):
    """Decision 2: a card's script pair is fetched the moment it's opened,
    never during discovery. GET /catalog/{slug} is that moment."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_unclassified_ct(db)

    def fake_get(url, **kw):
        if url.endswith(f"/{SHA}/ct/redis.sh"):
            return httpx.Response(200, text=REDIS_CT)
        if url.endswith(f"/{SHA}/install/redis-install.sh"):
            return httpx.Response(200, text=REDIS_INSTALL)
        return httpx.Response(404)
    monkeypatch.setattr("proxploy.services.catalog._fetch", fake_get)

    r = client.get("/api/v1/catalog/redis")
    assert r.status_code == 200
    assert r.json()["installable"] is True
    assert r.json()["unsupported_reason"] is None


def test_a_403_or_timeout_fetching_the_script_leaves_the_card_readable(
        client, csrf_header, bootstrap_admin, monkeypatch):
    """Decision 1: degrade silently. A fetch failure while opening a card
    must not 500 it; the card renders with whatever it already had."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_unclassified_ct(db)

    def raises(url, **kw):
        raise TimeoutError("upstream timed out")
    monkeypatch.setattr("proxploy.services.catalog._fetch", raises)

    r = client.get("/api/v1/catalog/redis")
    assert r.status_code == 200
    assert r.json()["installable"] is None  # honestly "not yet known", not broken

    # ...and the store list is still fully usable
    r = client.get("/api/v1/catalog")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_a_403_fetching_the_script_reports_400_not_500_via_ct_status(
        client, csrf_header, bootstrap_admin, monkeypatch):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_unclassified_ct(db)

    def not_found(url, **kw):
        return httpx.Response(403)
    monkeypatch.setattr("proxploy.services.catalog._fetch", not_found)

    r = client.get("/api/v1/catalog/redis")
    assert r.status_code == 200
    body = r.json()
    assert body["installable"] is False
    assert "fetch" in body["unsupported_reason"]


def test_entry_type_is_returned_and_filterable(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_entry(db)
        db.add(CatalogEntry(slug="haos", entry_type="vm", name="HAOS", installable=False,
                            unsupported_reason="VM script"))
        db.commit()

    r = client.get("/api/v1/catalog")
    types = {row["slug"]: row["type"] for row in r.json()}
    assert types == {"redis": "ct", "haos": "vm"}

    r = client.get("/api/v1/catalog?entry_type=ct")
    assert [row["slug"] for row in r.json()] == ["redis"]


# --- sorting: "what's popular" and "what's new" -----------------------------
#
# The whole point of these is the NULL placement. SQLite orders NULL first
# ascending, so the naive spelling of any of these sorts puts the rows we know
# nothing about at the TOP of "most popular" and "newest", which is the exact
# opposite of what either word means.

def _seed_sortable(db):
    from datetime import datetime

    db.add(CatalogEntry(slug="alpha", name="Alpha", entry_type="ct",
                        popularity=10,
                        script_created=datetime(2024, 1, 1),
                        script_updated=datetime(2026, 1, 1)))
    db.add(CatalogEntry(slug="bravo", name="Bravo", entry_type="ct",
                        popularity=9000,
                        script_created=datetime(2026, 8, 1),
                        script_updated=datetime(2024, 6, 1)))
    db.add(CatalogEntry(slug="charlie", name="Charlie", entry_type="ct",
                        popularity=500,
                        script_created=datetime(2025, 5, 5),
                        script_updated=datetime(2026, 7, 1)))
    # The row we know nothing about: an `unlisted` slug with no upstream
    # record, so no popularity and no dates. It must sort LAST in all three.
    db.add(CatalogEntry(slug="unknown", name="Unknown", entry_type="ct",
                        upstream_state="unlisted"))
    db.commit()


def test_default_sort_is_by_name(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_sortable(db)

    assert [r["slug"] for r in client.get("/api/v1/catalog").json()] == [
        "alpha", "bravo", "charlie", "unknown"]


def test_sort_by_popularity_puts_the_most_installed_first(client, csrf_header,
                                                          bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_sortable(db)

    slugs = [r["slug"] for r in
             client.get("/api/v1/catalog?sort=popularity").json()]

    assert slugs == ["bravo", "charlie", "alpha", "unknown"]


def test_a_row_with_no_popularity_never_ranks_above_one_with_a_real_count(
        client, csrf_header, bootstrap_admin):
    """The trap this sort exists to avoid. "No measurement" is not "the most
    popular app in the catalog", and on the real DB there are 84 rows with no
    number at all."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_sortable(db)

    rows = client.get("/api/v1/catalog?sort=popularity").json()

    assert rows[-1]["slug"] == "unknown" and rows[-1]["popularity"] is None
    ranked = [r["slug"] for r in rows]
    for slug in ("alpha", "bravo", "charlie"):
        assert ranked.index(slug) < ranked.index("unknown"), slug


def test_sort_by_newest_uses_script_created(client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_sortable(db)

    slugs = [r["slug"] for r in client.get("/api/v1/catalog?sort=newest").json()]

    assert slugs == ["bravo", "charlie", "alpha", "unknown"]


def test_sort_by_updated_uses_script_updated_not_script_created(
        client, csrf_header, bootstrap_admin):
    """The two dates disagree on purpose in the fixture: bravo is the newest
    script and the least recently updated one. A sort that confused them would
    pass the "newest" test and still be wrong here."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_sortable(db)

    slugs = [r["slug"] for r in client.get("/api/v1/catalog?sort=updated").json()]

    assert slugs == ["charlie", "alpha", "bravo", "unknown"]


def test_an_unknown_or_hostile_sort_value_falls_back_to_the_default(
        client, csrf_header, bootstrap_admin):
    """A sort key is caller controlled, so the only safe shape is one that
    never reaches SQL as a string. The Store rendering in the wrong order
    beats the Store not rendering, so an unknown key is the default rather
    than a 500 or a 422."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_sortable(db)
    by_name = [r["slug"] for r in client.get("/api/v1/catalog").json()]

    # The last four are dict/object attribute names. A JS `key in obj` check
    # walks the prototype chain and would accept "toString", which the
    # frontend hit for real; `dict.get` in Python does not, and these pin it.
    for hostile in ("popularity; DROP TABLE catalog_entries",
                    "name) --", "../../etc/passwd", "", "POPULARITY",
                    "raw", "unsupported_reason",
                    "get", "keys", "items", "__class__"):
        r = client.get("/api/v1/catalog", params={"sort": hostile})
        assert r.status_code == 200, hostile
        assert [row["slug"] for row in r.json()] == by_name, hostile

    # ...and the table is still there, which the previous assertion needs.
    with client.app.state.sessionmaker() as db:
        assert db.query(CatalogEntry).count() == 4


def test_sorting_composes_with_the_store_grid_filter(client, csrf_header,
                                                     bootstrap_admin):
    """Sorting must not reintroduce the alpine variants the grid hides."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_sortable(db)
        db.add(CatalogEntry(slug="alpine-alpha", name="Alpine Alpha",
                            entry_type="ct", upstream_state="variant",
                            popularity=999999))
        db.commit()

    slugs = [r["slug"] for r in
             client.get("/api/v1/catalog?entry_type=ct&sort=popularity").json()]

    assert "alpine-alpha" not in slugs
    assert slugs == ["bravo", "charlie", "alpha", "unknown"]


# --- the card tags: null is unknown, never "no" -----------------------------

def test_the_tag_fields_are_serialized_with_their_real_types(client, csrf_header,
                                                             bootstrap_admin):
    from datetime import datetime

    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        db.add(CatalogEntry(slug="plex", name="Plex Media Server", entry_type="ct",
                            script_created=datetime(2024, 5, 2),
                            script_updated=datetime(2026, 6, 11),
                            has_arm=True, architectures=["amd64", "arm64"],
                            updateable=True, privileged=False, port=32400))
        db.commit()

    row = client.get("/api/v1/catalog").json()[0]

    # Naive-UTC columns serialize with an explicit "Z" (proxploy.models.to_iso)
    # so a browser's `new Date(...)` reads them as UTC, not local time.
    assert row["script_created"] == "2024-05-02T00:00:00Z"
    assert row["script_updated"] == "2026-06-11T00:00:00Z"
    assert row["has_arm"] is True and row["updateable"] is True
    assert row["privileged"] is False            # a real, known negative
    assert row["architectures"] == ["amd64", "arm64"]
    assert row["port"] == 32400


def test_a_row_with_no_upstream_record_serializes_null_not_false(
        client, csrf_header, bootstrap_admin):
    """The 9 `unlisted` rows have no upstream record at all, so we do not know
    whether they are ARM-capable, updateable or privileged. Rendering null as
    a negative chip would assert something nothing supports; null must stay
    distinguishable from False all the way to the UI."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        db.add(CatalogEntry(slug="readarr", name="Readarr", entry_type="ct",
                            upstream_state="unlisted"))
        db.commit()

    row = client.get("/api/v1/catalog").json()[0]

    for field in ("has_arm", "updateable", "privileged"):
        assert row[field] is None, field
        assert row[field] is not False, field
    assert row["architectures"] is None and row["port"] is None
    assert row["script_created"] is None and row["script_updated"] is None


# --- the local icon mirror: served from disk, upstream as the fallback ------

UPSTREAM_ICON = "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/redis.webp"
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 fake-bytes"


def _cache_icon(client, slug="redis", filename="redis.webp", body=WEBP,
                source=UPSTREAM_ICON):
    from proxploy.services.catalog_icons import icon_dir
    directory = icon_dir(client.app.state.settings.data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_bytes(body)
    with client.app.state.sessionmaker() as db:
        row = db.query(CatalogEntry).filter_by(slug=slug).one()
        row.icon_cache_path = filename
        row.icon_cache_source = source
        db.commit()
    return directory


def test_a_cached_icon_is_served_from_disk_and_icon_url_points_at_us(
        client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_entry(db, icon_url=UPSTREAM_ICON)
    _cache_icon(client)

    row = client.get("/api/v1/catalog").json()[0]
    assert row["icon_url"] == "/api/v1/catalog/redis/icon"

    r = client.get("/api/v1/catalog/redis/icon")
    assert r.status_code == 200
    assert r.content == WEBP
    assert r.headers["content-type"] == "image/webp"
    # CC BY 4.0 attribution, on the response that redistributes the file.
    assert 'rel="license"' in r.headers["link"]
    assert "creativecommons.org/licenses/by/4.0/" in r.headers["link"]


def test_an_uncached_slug_falls_back_to_the_upstream_url_not_a_404_tile(
        client, csrf_header, bootstrap_admin):
    """The fallback IS the pre-existing behaviour, so a cold cache renders
    exactly as the Store did before the mirror existed."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_entry(db, icon_url=UPSTREAM_ICON)

    row = client.get("/api/v1/catalog").json()[0]

    assert row["icon_url"] == UPSTREAM_ICON
    # ...and asking for the local one is an honest 404, never a 500.
    assert client.get("/api/v1/catalog/redis/icon").status_code == 404


def test_a_cached_row_whose_file_vanished_404s_rather_than_500ing(
        client, csrf_header, bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_entry(db, icon_url=UPSTREAM_ICON)
    directory = _cache_icon(client)
    (directory / "redis.webp").unlink()

    assert client.get("/api/v1/catalog/redis/icon").status_code == 404


def test_path_traversal_on_the_icon_route_is_rejected(client, csrf_header,
                                                      bootstrap_admin):
    """The slug arrives from the URL, so this route reads files off disk on
    behalf of an HTTP caller. Closed twice: the slug is an exact-match DB
    lookup rather than a path component, and the resolved path must sit inside
    the cache dir before it is opened."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_entry(db, icon_url=UPSTREAM_ICON)
    _cache_icon(client)
    secret = client.app.state.settings.data_dir / "master.key"

    for hostile in ("../../etc/passwd", "..%2F..%2Fetc%2Fpasswd",
                    "%2e%2e%2f%2e%2e%2fmaster.key", "/etc/passwd",
                    "....//....//master.key"):
        r = client.get(f"/api/v1/catalog/{hostile}/icon")
        assert r.status_code in (404, 307), hostile
        assert secret.read_bytes() not in r.content, hostile

    # ...and even a corrupted column cannot escape the cache dir, which is the
    # second lock rather than a restatement of the first.
    with client.app.state.sessionmaker() as db:
        db.query(CatalogEntry).filter_by(slug="redis").one().icon_cache_path = \
            "../master.key"
        db.commit()

    r = client.get("/api/v1/catalog/redis/icon")
    assert r.status_code == 404
    assert secret.read_bytes() not in r.content


def test_the_full_catalog_and_by_slug_routes_agree_about_the_icon(
        client, csrf_header, bootstrap_admin):
    """_serialize is shared, so a card opened from the grid and a card opened
    by slug must not disagree about where the icon lives."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_entry(db, icon_url=UPSTREAM_ICON)
    _cache_icon(client)

    listed = client.get("/api/v1/catalog").json()[0]
    single = client.get("/api/v1/catalog/redis").json()

    assert listed["icon_url"] == single["icon_url"] == "/api/v1/catalog/redis/icon"


# --- the script identity: exactly which file, at exactly which commit -------

SHA40 = "a222d32a318e3463bcde935bf52fdf5f883fa804"


def test_the_script_path_and_pinned_sha_are_served(client, csrf_header,
                                                   bootstrap_admin):
    """Together these are the verifiable answer to "what will Proxploy run?":
    services/appstore.py executes raw_url(upstream_sha, script_path) and
    nothing else."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_entry(db, script_path="ct/redis.sh", upstream_sha=SHA40)

    listed = client.get("/api/v1/catalog").json()[0]
    single = client.get("/api/v1/catalog/redis").json()

    assert listed["script_path"] == "ct/redis.sh"
    assert listed["upstream_sha"] == SHA40
    # The by-slug route shares _serialize, so the two cannot disagree about
    # which file runs.
    assert (single["script_path"], single["upstream_sha"]) == ("ct/redis.sh", SHA40)


def test_the_script_path_is_served_not_derived_from_the_slug(client, csrf_header,
                                                             bootstrap_admin):
    """A `ct/<slug>.sh` guess is right for every ct row and wrong for all 84
    non-ct ones, so a test written only against the grid would pass on a
    derivation. These two are the shapes that actually break it: `turnkey`
    shares none of its slug's shape, and `coolify-addon` is a slug discovery
    INVENTED (dual-variant collision detection appends `-addon` so it cannot
    shadow the ct row), so its slug is not its filename at all."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_entry(db, script_path="ct/redis.sh", upstream_sha=SHA40)
        db.add(CatalogEntry(slug="turnkey", name="Turnkey", entry_type="turnkey",
                            script_path="turnkey/turnkey.sh", upstream_sha=SHA40))
        db.add(CatalogEntry(slug="coolify-addon", name="Coolify addon",
                            entry_type="addon",
                            script_path="tools/addon/coolify.sh",
                            upstream_sha=SHA40))
        db.commit()

    paths = {r["slug"]: r["script_path"] for r in client.get("/api/v1/catalog").json()}

    assert paths["turnkey"] == "turnkey/turnkey.sh"
    assert paths["coolify-addon"] == "tools/addon/coolify.sh"


def test_an_unpinned_row_serves_null_rather_than_a_wrong_link(client, csrf_header,
                                                              bootstrap_admin):
    """A row discovery has not pinned yet has no honest link to offer, and a
    default would be a link to the wrong file rather than no link."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_entry(db, script_path=None, upstream_sha=None)

    row = client.get("/api/v1/catalog").json()[0]

    assert row["script_path"] is None and row["upstream_sha"] is None


# --- /catalog/status counts what the operator can actually see --------------

def test_the_status_count_matches_what_the_grid_returns(client, csrf_header,
                                                        bootstrap_admin):
    """It used to count every ct row and report 585 against a grid showing
    556. Same class as the search bug: one rule, two places, one of them not
    updated. Both now go through store_visible()."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        _seed_entry(db)
        db.add(CatalogEntry(slug="syncthing", name="Syncthing", entry_type="ct",
                            upstream_state="listed"))
        db.add(CatalogEntry(slug="alpine-syncthing", name="Alpine Syncthing",
                            entry_type="ct", upstream_state="variant"))
        db.add(CatalogEntry(slug="netvisor", name="Scanopy", entry_type="ct",
                            upstream_state="superseded"))
        db.add(CatalogEntry(slug="haos", name="HAOS", entry_type="vm",
                            upstream_state="listed"))
        db.commit()

    grid = client.get("/api/v1/catalog?entry_type=ct").json()
    status = client.get("/api/v1/catalog/status").json()

    assert status["entries"] == len(grid) == 2
    assert {r["slug"] for r in grid} == {"redis", "syncthing"}


def test_hidden_rows_are_excluded_from_the_status_count(client, csrf_header,
                                                        bootstrap_admin):
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        for state in ("variant", "superseded"):
            db.add(CatalogEntry(slug=f"hidden-{state}", name=state,
                                entry_type="ct", upstream_state=state))
        db.commit()

    assert client.get("/api/v1/catalog/status").json()["entries"] == 0


def test_the_status_count_is_right_on_a_never_synced_install(client, csrf_header,
                                                             bootstrap_admin):
    """The IS NULL arm. Discovery runs before the first metadata sync, so
    every row's upstream_state is NULL, and a bare `!= 'variant'` would count
    zero and report an empty Store on a fresh install."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        for slug in ("redis", "grafana", "plex"):
            db.add(CatalogEntry(slug=slug, name=slug.title(), entry_type="ct",
                                upstream_state=None))
        db.commit()

    status = client.get("/api/v1/catalog/status").json()

    assert status["entries"] == 3
    assert status["entries"] == len(client.get("/api/v1/catalog?entry_type=ct").json())


def test_freshness_is_still_measured_across_every_ct_row(client, csrf_header,
                                                         bootstrap_admin):
    """`synced_at` deliberately is NOT narrowed to visible rows. It answers
    "is the refresh schedule alive", and discovery stamps hidden rows in the
    same pass, so an install whose ct rows were all hidden must not report
    "never refreshed" seconds after a successful refresh."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        db.add(CatalogEntry(slug="alpine-syncthing", name="Alpine Syncthing",
                            entry_type="ct", upstream_state="variant",
                            synced_at=utcnow()))
        db.commit()

    status = client.get("/api/v1/catalog/status").json()

    assert status["entries"] == 0            # nothing visible to show
    assert status["synced_at"] is not None   # ...but the catalog IS fresh
    assert status["stale"] is False


def test_install_defaults_come_from_the_script_not_metadata(client, csrf_header,
                                                             bootstrap_admin):
    """dockge is the row where the two sources disagree: the ct script says
    2/2048/18 and the cached metadata's install_methods[0].resources says
    0/0/0. The script is what actually runs, and metadata is
    presentation-only (catalog_metadata.apply_writable_fields), so the script
    wins. Prefilling an install form from the metadata zeros would be a
    visible bug."""
    bootstrap_admin(client)
    with client.app.state.sessionmaker() as db:
        db.add(CatalogEntry(
            slug="dockge", name="Dockge", category="Containers & Docker",
            entry_type="ct", installable=True, unsupported_reason=None,
            default_cpu=2, default_ram_mb=2048, default_disk_gb=18,
            default_os="debian", default_os_version="13",
            raw={"metadata": {"install_methods": [
                {"type": "default", "resources": {
                    "cpu": 0, "ram": 0, "hdd": 0,
                    "os": "Debian", "version": "13",
                }},
            ]}},
        ))
        db.commit()

    body = client.get("/api/v1/catalog/dockge").json()

    assert body["default_cpu"] == 2
    assert body["default_ram_mb"] == 2048
    assert body["default_disk_gb"] == 18
    assert body["default_os"] == "debian"
    assert body["default_os_version"] == "13"
