"""Canonical entitlement flag registry. All flags ON while dormant.

Keys never change once shipped; a feature without a key does not merge."""

FLAG_KEYS: tuple[str, ...] = (
    "hosts.onboard", "hosts.ssh_executor", "hosts.single", "hosts.multi", "hosts.manage",
    "cluster.overview", "cluster.node_detail", "cluster.activity_feed", "ui.global_search",
    "apps.list", "apps.detail", "apps.lifecycle", "apps.open_ui", "apps.logs",
    "apps.console", "apps.script_edit", "apps.graphs", "apps.adopt", "apps.reconfigure",
    "apps.uninstall",
    "store.catalog", "store.search", "store.refresh", "store.install", "store.install_log",
    "store.updates", "store.update", "store.update_all", "store.auto_update",
    "vms.list", "vms.lifecycle", "vms.console", "vms.snapshots", "vms.create",
    "vms.clone", "vms.graphs",
    # The Options tab (boot order, guest agent, SMBIOS, and so on). Its own
    # key rather than a second job for vms.create, which is already doing
    # double duty gating Destroy: editing a machine's settings is not the same
    # decision as being allowed to make or unmake one.
    "vms.options",
    "storage.view", "storage.content", "storage.manage",
    "network.view", "network.guest_config", "network.host_config",
    "firewall.view", "firewall.rules", "firewall.options", "firewall.objects",
    "firewall.log",
    "backups.pbs", "backups.run", "backups.schedule", "backups.restore",
    "backups.notify", "backups.retention",
    "migrate.cross_host", "migrate.preflight",
    "metrics.collect", "metrics.history",
    "alerts.rules", "alerts.manage",
    "notify.channels", "notify.routing", "notify.inapp",
    "jobs.engine", "jobs.stream", "jobs.history", "sched.windows",
    "terminal.ct", "terminal.node",
    "auth.local", "auth.totp", "auth.oidc", "rbac.roles", "teams.rbac", "api.tokens",
    "secrets.store", "audit.log", "audit.retention",
    "ent.client", "ent.manage",
    "platform.onboarding", "platform.self_update", "platform.install", "api.rest",
    "ui.theme", "platform.settings", "platform.error_report",
)
# platform.error_report is a NAME ONLY: never wire it as a gate. Crash
# reporting is controlled solely by PROXPLOY_SENTRY_DSN (main.py); gating on
# an entitlement would let an expired licence silently change what leaves the
# operator's network.

# The keys Homelab does NOT get. Everything else in FLAG_KEYS is on for
# everyone, licensed or not, which is what makes Homelab a complete
# single-node product rather than a crippled demo. The split is scale and
# organisation (more than one host, unattended automation, many users, API
# automation), never capability on the host you already own.
#
# This list is the app-side copy of proxploy-api's `homelab` tier map. Two
# copies because the two repos ship separately and the app must know its own
# floor with no network; the copies are pinned together by
# test_free_baseline_matches_tiers_yaml (here) and
# test_free_features_match_the_homelab_tier (proxploy-api), which fail loudly
# on drift rather than letting one side quietly diverge.
FREE_OFF: frozenset[str] = frozenset({
    "hosts.multi",
    "store.auto_update",
    "migrate.cross_host", "migrate.preflight",
    "auth.oidc", "teams.rbac", "api.tokens",
})

# The shipped no-licence state. There is no "unlicensed tier": an install with
# no licence IS a Homelab install, and this is that tier's map. Before
# 2026-08-28 this was every flag true, which meant activating a Homelab licence
# REMOVED features (apply_claims replaces the map wholesale, it does not merge),
# so a paying customer was worse off than someone who never activated.
FREE_FEATURES: dict[str, bool] = {k: k not in FREE_OFF for k in FLAG_KEYS}

# Development only. Never the shipped baseline and never a fallback: pass it
# explicitly to Entitlements(baseline=...) when you want every gate open
# locally. If this ever becomes a default again, every denied branch in the
# app stops being exercised and the tier split silently stops meaning anything.
DEV_FEATURES: dict[str, bool] = {k: True for k in FLAG_KEYS}


# The keys Pro does not get either: everything above the multi-host story is an
# organisation feature (many identities, many roles, machine access). Same
# pinning as FREE_OFF, against proxploy-api's `pro` tier map.
PRO_OFF: frozenset[str] = frozenset({
    "auth.oidc", "teams.rbac", "api.tokens",
})

TIER_LABEL = {"homelab": "Homelab", "pro": "Pro", "team": "Team"}


def required_tier(key: str) -> str:
    """The lowest tier that grants `key`.

    Only used to say so out loud in a 403: a denial that names the feature but
    not the plan tells an operator nothing they can act on. Enforcement never
    reads this, it reads the resolved feature map, so a wrong answer here is a
    bad error message and never a wrong access decision.
    """
    if key not in FREE_OFF:
        return "homelab"
    return "team" if key in PRO_OFF else "pro"
