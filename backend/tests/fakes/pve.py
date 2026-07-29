"""Fake PVE responder (doc 10 Phase 1 test infra (a)): mimics the exact proxmoxer
attribute surface Proxploy uses, fed by recorded fixtures under tests/fixtures/pve/.
Re-record on a live node with: pvesh get /version --output-format json
                               pvesh get /access/permissions --output-format json"""


class _Leaf:
    def __init__(self, value, fail):
        self._value, self._fail = value, fail

    def get(self):
        if self._fail:
            raise ConnectionError("fake PVE unreachable")
        return self._value


class _KwLeaf:
    """Like _Leaf but tolerates .get(**kwargs) (rrddata takes timeframe=...)."""

    def __init__(self, value, fail=False):
        self._value, self._fail = value, fail

    def get(self, **kwargs):
        if self._fail:
            raise ConnectionError("fake PVE unreachable")
        return self._value


class _Access:
    def __init__(self, permissions, fail):
        self.permissions = _Leaf(permissions, fail)


class _ClusterNS:
    def __init__(self, resources, fail):
        self.resources = _KwLeaf(resources, fail)


class _ActionLeaf:
    """nodes(n).lxc(vmid).status.<action> — .post() records and mints a UPID."""

    def __init__(self, owner, kind, vmid, action):
        self._owner, self._kind, self._vmid, self._action = owner, kind, vmid, action

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        return self._owner._record_action(self._kind, self._vmid, self._action)


class _GuestStatusNS:
    def __init__(self, owner, kind, vmid):
        self._owner, self._kind, self._vmid = owner, kind, vmid

    def __getattr__(self, action):
        return _ActionLeaf(self._owner, self._kind, self._vmid, action)


class _GuestNS:
    def __init__(self, owner, kind, vmid):
        self.status = _GuestStatusNS(owner, kind, vmid)


class _GuestFactory:
    """nodes(n).lxc / nodes(n).qemu — callable with a vmid."""

    def __init__(self, owner, kind):
        self._owner, self._kind = owner, kind

    def __call__(self, vmid):
        return _GuestNS(self._owner, self._kind, int(vmid))


class _TaskStatusLeaf:
    def __init__(self, owner, upid):
        self._owner, self._upid = owner, upid

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        return self._owner._task_status(self._upid)


class _TaskLogLeaf:
    def __init__(self, owner, upid):
        self._owner, self._upid = owner, upid

    def get(self, start=0, limit=500, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        lines = self._owner.task_lines.get(self._upid, [])
        return [{"n": i + 1, "t": t}
                for i, t in enumerate(lines)][int(start):int(start) + int(limit)]


class _TaskNS:
    def __init__(self, owner, upid):
        self.status = _TaskStatusLeaf(owner, upid)
        self.log = _TaskLogLeaf(owner, upid)


class _TaskFactory:
    def __init__(self, owner):
        self._owner = owner

    def __call__(self, upid):
        return _TaskNS(self._owner, upid)


class _NodeNS:
    def __init__(self, owner, name):
        self.rrddata = _KwLeaf(owner.rrd_by_node.get(name, []), owner.fail)
        self.tasks = _TaskFactory(owner)
        self.lxc = _GuestFactory(owner, "lxc")
        self.qemu = _GuestFactory(owner, "qemu")


class _NodesNS:
    def __init__(self, owner):
        self._owner = owner

    def __call__(self, name):
        return _NodeNS(self._owner, name)


class FakePVE:
    def __init__(self, version=None, permissions=None, fail=False,
                 resources=None, rrddata=None, task_exit="OK", running_ticks=0):
        self.fail = fail
        self.rrd_by_node = rrddata or {}
        self.version = _Leaf(version or {"version": "8.4.1", "release": "8.4"}, fail)
        self.access = _Access(permissions or {}, fail)
        self.cluster = _ClusterNS(resources or [], fail)
        self.nodes = _NodesNS(self)
        self.kwargs = {}
        # lifecycle recording (Phase 3)
        self.actions: list[tuple[str, int, str]] = []
        self.task_exit = task_exit
        self.running_ticks = running_ticks
        self.task_lines: dict[str, list[str]] = {}
        self._polls: dict[str, int] = {}
        self._upid_n = 0

    def _record_action(self, kind: str, vmid: int, action: str) -> str:
        self.actions.append((kind, vmid, action))
        self._upid_n += 1
        upid = f"UPID:pve1:{self._upid_n:08X}:00000000:00000000:{action}:{vmid}:proxploy@pve:"
        self.task_lines.setdefault(upid, [f"{action} {kind} {vmid}"])
        return upid

    def _task_status(self, upid: str) -> dict:
        n = self._polls.get(upid, 0)
        self._polls[upid] = n + 1
        if n < self.running_ticks:
            return {"upid": upid, "status": "running", "exitstatus": None}
        return {"upid": upid, "status": "stopped", "exitstatus": self.task_exit}


def make_fake_factory(fake: FakePVE):
    def factory(**kwargs):
        if fake.fail:
            raise ConnectionError("fake PVE unreachable")
        fake.kwargs = kwargs
        return fake
    return factory
