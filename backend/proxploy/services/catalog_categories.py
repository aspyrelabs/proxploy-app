"""Category derivation, automatic (catalog expansion plan, decision 3: no
hand-maintained 584-entry map, no dependency on the website taxonomy).

Two mechanical sources, in priority order:

1. Directory placement, for the four non-ct/ types: which directory a script
   lives in already says what kind of thing it is (services/catalog.py's
   discover_tree), so vm/pve/addon/turnkey entries get a fixed category from
   their type alone, free, always in sync.
2. For ct/ entries (the only type with no further directory structure to
   read), a small keyword heuristic over the slug. This is NOT a per-slug map:
   it is a short list of (keyword, category) pairs checked by substring, so it
   generalizes to slugs it has never seen (e.g. "postgresql-15" still matches
   "postgres"). Anything it doesn't recognize honestly falls back to
   "Uncategorized" rather than a guess, exactly as the decision allows.

This is now the FALLBACK, not the primary: services/catalog_metadata.py syncs
upstream's own 26-category vocabulary onto every slug that matches an upstream
record, and discovery only calls this for a row that has no category yet
(services/catalog.py::_upsert_skeleton). What is left for this module is the
37-odd ct/ rows upstream has never heard of, mostly alpine-* variants plus
mysql, which would otherwise render with no category at all. It stays
deliberately network-free so a cold, offline install still groups sensibly.
"""

TYPE_CATEGORY = {
    "vm": "VM Scripts",
    "pve": "Host Scripts",
    "addon": "Add-ons",
    "turnkey": "Turnkey Appliances",
}

# Ordered: first match wins. Substring match against the lowercased slug, not
# an exact-slug lookup, so e.g. "alpine-redis" and "postgresql-15" still land
# a category despite never appearing here literally.
_KEYWORD_CATEGORIES: list[tuple[str, str]] = [
    ("postgres", "Databases"), ("mysql", "Databases"), ("maria", "Databases"),
    ("mongo", "Databases"), ("redis", "Databases"), ("influxdb", "Databases"),
    ("couchdb", "Databases"), ("cassandra", "Databases"), ("cockroach", "Databases"),
    ("clickhouse", "Databases"), ("sqlite", "Databases"), ("dragonfly", "Databases"),
    ("jellyfin", "Media & Streaming"), ("plex", "Media & Streaming"),
    ("emby", "Media & Streaming"), ("immich", "Media & Streaming"),
    ("photoprism", "Media & Streaming"), ("navidrome", "Media & Streaming"),
    ("audiobookshelf", "Media & Streaming"), ("tautulli", "Media & Streaming"),
    ("radarr", "Media & Streaming"), ("sonarr", "Media & Streaming"),
    ("lidarr", "Media & Streaming"), ("readarr", "Media & Streaming"),
    ("prowlarr", "Media & Streaming"), ("bazarr", "Media & Streaming"),
    ("jellyseerr", "Media & Streaming"), ("overseerr", "Media & Streaming"),
    ("home-assistant", "Home & Automation"), ("homeassistant", "Home & Automation"),
    ("homebridge", "Home & Automation"), ("zigbee2mqtt", "Home & Automation"),
    ("esphome", "Home & Automation"), ("node-red", "Home & Automation"),
    ("mqtt", "Home & Automation"), ("zwave", "Home & Automation"),
    ("grafana", "Monitoring & Analytics"), ("prometheus", "Monitoring & Analytics"),
    ("uptimekuma", "Monitoring & Analytics"), ("uptime-kuma", "Monitoring & Analytics"),
    ("netdata", "Monitoring & Analytics"), ("zabbix", "Monitoring & Analytics"),
    ("influx", "Monitoring & Analytics"), ("checkmk", "Monitoring & Analytics"),
    ("healthchecks", "Monitoring & Analytics"), ("gatus", "Monitoring & Analytics"),
    ("gitea", "Dev Tools"), ("gitlab", "Dev Tools"), ("forgejo", "Dev Tools"),
    ("n8n", "Dev Tools"), ("code-server", "Dev Tools"), ("jenkins", "Dev Tools"),
    ("drone", "Dev Tools"), ("woodpecker", "Dev Tools"), ("jupyter", "Dev Tools"),
    ("litellm", "AI / Coding & Dev-Tools"), ("ollama", "AI / Coding & Dev-Tools"),
    ("openwebui", "AI / Coding & Dev-Tools"), ("open-webui", "AI / Coding & Dev-Tools"),
    ("localai", "AI / Coding & Dev-Tools"),
    ("pihole", "Network & Firewall"), ("adguard", "Network & Firewall"),
    ("nginxproxymanager", "Network & Firewall"), ("nginx-proxy-manager", "Network & Firewall"),
    ("wireguard", "Network & Firewall"), ("traefik", "Network & Firewall"),
    ("caddy", "Network & Firewall"), ("tailscale", "Network & Firewall"),
    ("openvpn", "Network & Firewall"), ("unbound", "Network & Firewall"),
    ("technitium", "Network & Firewall"),
    ("paperless", "Files & Storage"), ("nextcloud", "Files & Storage"),
    ("owncloud", "Files & Storage"), ("syncthing", "Files & Storage"),
    ("minio", "Files & Storage"), ("filebrowser", "Files & Storage"),
    ("seafile", "Files & Storage"),
    ("proxmox-backup-server", "Backup"), ("duplicati", "Backup"),
    ("borgbackup", "Backup"), ("kopia", "Backup"),
    ("vaultwarden", "Security"), ("bitwarden", "Security"),
    ("authelia", "Security"), ("authentik", "Security"), ("keycloak", "Security"),
    ("wazuh", "Security"), ("crowdsec", "Security"),
    ("docker", "Containers"), ("portainer", "Containers"), ("dockge", "Containers"),
    ("dokploy", "Containers"), ("komodo", "Containers"), ("coolify", "Containers"),
    ("rancher", "Containers"), ("kubernetes", "Containers"), ("k3s", "Containers"),
]


def category_for(slug: str, entry_type: str = "ct") -> str:
    if entry_type != "ct":
        return TYPE_CATEGORY.get(entry_type, "Uncategorized")
    low = slug.lower()
    for keyword, category in _KEYWORD_CATEGORIES:
        if keyword in low:
            return category
    return "Uncategorized"
