"""Canonical entitlement flag registry (doc 01 §17). 82 keys, all ON while dormant.
A feature without a key does not merge (doc 07 §3); keys never change once shipped."""

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
# platform.error_report is a NAME ONLY: do not wire it as a gate. Doc 01's
# feature table lists it and says "never on the entitlement path" in the same
# row, which reads like a contradiction until you see why. Crash reporting is
# controlled by PROXPLOY_SENTRY_DSN in the operator's env file and by nothing
# else (main.py). Gating it on an entitlement would mean an expired licence
# silently changes what leaves the operator's network, which is not a decision
# a billing state gets to make.

DEFAULT_FEATURES: dict[str, bool] = {k: True for k in FLAG_KEYS}
