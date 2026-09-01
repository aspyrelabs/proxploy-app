from __future__ import annotations

from proxploy.executor import SSHExecutor, SSHHostKeyMismatch
from proxploy.executor.ssh import SSHUnreachable
from proxploy.models import HostCredential
from proxploy.services.audit import write_audit
from proxploy.services.hostclient import client_for_host, privilege_repair_plan
from proxploy.services.pveum import repair_commands
from proxploy.services.proxmox import ProxmoxError

_SSH_ERROR_KIND = {SSHHostKeyMismatch: "host_key_mismatch",
                   SSHUnreachable: "unreachable", LookupError: "no_key"}


class PrivilegeRepairRefused(ProxmoxError):
    def __init__(self, message: str, commands: list[str]):
        super().__init__(message, kind="no_ssh_key")
        self.commands = commands


def existing_role_privileges(app, db, host,
                             plan: dict[str, list[str] | None]) -> dict[str, set[str] | None]:
    roles = [role for role, missing in plan.items() if missing]
    if not roles:
        return {}
    client = client_for_host(app, db, host, capability="monitoring")
    return {role: client.role_privileges(role) for role in roles}


def _finish(app, db, host, actor_type, actor_id, result,
           repaired: dict[str, list[str]], commands: list[str], detail: str) -> None:
    write_audit(db, actor_type=actor_type, actor_id=actor_id,
               action="host.privileges_repaired", target_type="host",
               target_id=host.id, result=result,
               params={"repaired": repaired, "commands": commands})
    from proxploy.services.links import absolute
    from proxploy.services.notification_body import compose
    from proxploy.services.notifier import notify

    facts = [(role, ", ".join(privs)) for role, privs in repaired.items()]
    link = absolute(db, "/settings?section=hosts")
    body = compose(facts, detail, link=link)
    notify(app, "host.privileges_repaired",
          f"Proxploy: privilege repair on {host.name} ({result})", body)


async def repair_host_privileges(app, db, host, *, actor_type: str,
                                 actor_id: int | None = None) -> dict[str, list[str]]:
    plan = privilege_repair_plan(app, db, host)
    if not plan:
        return {}
    existing = existing_role_privileges(app, db, host, plan)
    commands = repair_commands(plan, existing)
    if not commands:
        return {}

    has_key = (db.query(HostCredential)
              .filter_by(host_id=host.id, kind="ssh_key").one_or_none() is not None)
    if not has_key:
        detail = (f"{host.name} has no SSH key stored, so Proxploy cannot run this "
                  f"repair itself. Run the commands below yourself, as root, on the "
                  f"node.")
        _finish(app, db, host, actor_type, actor_id, "refused", {}, commands, detail)
        raise PrivilegeRepairRefused(detail, commands)

    def on_new_fingerprint(fp: str) -> None:
        host.ssh_host_key_fingerprint = fp

    executor = SSHExecutor(connect_factory=app.state.ssh_connect_factory)
    script = " && ".join(commands)
    try:
        code = await executor.run_for_host(
            app.state.sessionmaker, app.state.secretstore, host.id, host.address,
            script, pinned_fingerprint=host.ssh_host_key_fingerprint,
            on_new_fingerprint=on_new_fingerprint, timeout_s=120.0)
    except (SSHHostKeyMismatch, SSHUnreachable, LookupError) as e:
        kind = _SSH_ERROR_KIND.get(type(e), "ssh_failed")
        _finish(app, db, host, actor_type, actor_id, "error", {}, commands, str(e))
        raise ProxmoxError(str(e), kind=kind) from e

    if code != 0:
        detail = (f"{host.name} ran the repair commands but they exited with status "
                  f"{code}. Run them yourself, as root, on the node: "
                  f"{'; '.join(commands)}")
        _finish(app, db, host, actor_type, actor_id, "error", {}, commands, detail)
        raise ProxmoxError(detail, kind="ssh_command_failed")

    repaired = {role: plan[role] for role in plan
               if plan[role] and existing.get(role) is not None}
    _finish(app, db, host, actor_type, actor_id, "ok", repaired, commands,
           f"{host.name} was widened to the privileges Proxploy needs. Nothing "
           f"granted by hand was removed.")
    return repaired
