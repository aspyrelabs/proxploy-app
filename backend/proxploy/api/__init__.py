from fastapi import APIRouter

from proxploy.api import (alerts, apikeys, apps, audit, auth, backups, catalog,
                          cluster, consoles, entitlements, events, firewall,
                          hosts, jobs, meta, metrics, network,
                          notification_dismissals, notifications, schedules,
                          search, settings, storage, teams, vms)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(meta.router)
api_router.include_router(auth.router)
api_router.include_router(auth.users_router)
api_router.include_router(apikeys.router)
api_router.include_router(audit.router)
api_router.include_router(entitlements.router)
api_router.include_router(hosts.router)
api_router.include_router(settings.router)
api_router.include_router(events.router)
api_router.include_router(cluster.router)
api_router.include_router(storage.router)
api_router.include_router(apps.router)
api_router.include_router(catalog.router)
api_router.include_router(vms.router)
api_router.include_router(consoles.router)
api_router.include_router(jobs.router)
api_router.include_router(schedules.router)
api_router.include_router(notifications.router)
api_router.include_router(notification_dismissals.router)
api_router.include_router(alerts.router)
api_router.include_router(metrics.router)
api_router.include_router(network.router)
api_router.include_router(firewall.router)
api_router.include_router(backups.router)
api_router.include_router(teams.router)
api_router.include_router(search.router)
