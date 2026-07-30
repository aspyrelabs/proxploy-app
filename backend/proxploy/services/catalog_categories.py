"""Hand-maintained slug -> category map (doc 06 store category chips).
Known v1 gap (docs/notes/phase-4-spike.md / this plan's header note):
community-scripts has no public bulk metadata API to source this from
automatically. Unmapped slugs fall back to "Uncategorized" rather than a
guess. Extend this map as real gaps are noticed in the store UI."""
CATEGORY_MAP = {
    "postgresql": "Databases", "mysql": "Databases", "mariadb": "Databases",
    "mongodb": "Databases", "redis": "Databases",
    "jellyfin": "Media", "plex": "Media", "immich": "Media",
    "homeassistant": "Home & Auto", "homebridge": "Home & Auto", "zigbee2mqtt": "Home & Auto",
    "grafana": "Monitoring", "prometheus": "Monitoring", "uptimekuma": "Monitoring",
    "gitea": "Dev", "n8n": "Dev",
    "pihole": "Network", "adguard": "Network", "nginxproxymanager": "Network", "wireguard": "Network",
    "paperless-ngx": "Files", "vaultwarden": "Security",
    "docker": "Docker", "proxmox-backup-server": "Files",
}


def category_for(slug: str) -> str:
    return CATEGORY_MAP.get(slug, "Uncategorized")
