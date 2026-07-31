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


class _AttrLeaf:
    """A .get() that reads a FakePVE attribute lazily, so a test can assign the
    attribute after construction (unlike _Leaf, which captures its value)."""

    def __init__(self, owner, attr, cast=None):
        self._owner, self._attr, self._cast = owner, attr, cast

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        value = getattr(self._owner, self._attr)
        return self._cast(value) if self._cast else value


class _StorageStatusLeaf:
    def __init__(self, owner, node, storage):
        self._owner, self._node, self._storage = owner, node, storage

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.last_storage_status_call = (self._node, self._storage)
        return self._owner.storage_status_response


class _StorageContentLeaf:
    def __init__(self, owner, node, storage):
        self._owner, self._node, self._storage = owner, node, storage

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.last_content_call = (self._node, self._storage,
                                         kwargs.get("content"))
        return self._owner.content_by_storage.get(self._storage, [])


class _StorageNS:
    """nodes(n).storage(name) — the per-datastore subtree."""

    def __init__(self, owner, node, storage):
        self.status = _StorageStatusLeaf(owner, node, storage)
        self.content = _StorageContentLeaf(owner, node, storage)


class _NodeStorageNS:
    """nodes(n).storage is BOTH gettable and callable, exactly like proxmoxer:
    `.storage.get()` lists every datastore on the node, `.storage(name)`
    descends into one. ProxmoxClient.storages and .storage_status use one shape
    each, so a leaf that only did .get() would break the second."""

    def __init__(self, owner, node):
        self._owner, self._node = owner, node

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        return self._owner.storages_by_node.get(self._node, [])

    def __call__(self, storage):
        return _StorageNS(self._owner, self._node, storage)


class _NetIfaceNS:
    """nodes(n).network(iface) — the staging subtree Task 7 hangs put/delete
    off. Present now only so `.network` has proxmoxer's full dual shape."""

    def __init__(self, owner, node, iface):
        self._owner, self._node, self._iface = owner, node, iface


class _NodeNetworkNS:
    """Same dual shape as _NodeStorageNS: `.get()` lists, `(iface)` descends."""

    def __init__(self, owner, node):
        self._owner, self._node = owner, node

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        rows = self._owner.networks_by_node.get(self._node, [])
        want = kwargs.get("type")  # read out of kwargs, never a `type=` param
        return [r for r in rows if r.get("type") == want] if want else rows

    def __call__(self, iface):
        return _NetIfaceNS(self._owner, self._node, iface)


class _GuestConfigLeaf:
    def __init__(self, owner, kind, vmid):
        self._owner, self._kind, self._vmid = owner, kind, vmid

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        return self._owner.guest_configs.get((self._kind, self._vmid), {})


class _SnapshotLeaf:
    def __init__(self, owner, kind, vmid):
        self._owner, self._kind, self._vmid = owner, kind, vmid

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        return self._owner.snapshots_by_guest.get((self._kind, self._vmid), [])


class _ClusterNS:
    def __init__(self, owner, resources, fail):
        self.resources = _KwLeaf(resources, fail)
        self.nextid = _AttrLeaf(owner, "nextid", str)  # PVE returns a string


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


class _TermproxyLeaf:
    def __init__(self, owner, kind, node, vmid):
        self._owner, self._kind, self._node, self._vmid = owner, kind, node, vmid

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        if self._vmid is None:
            self._owner.last_node_termproxy_call = self._node
        else:
            self._owner.last_termproxy_call = (self._kind, self._node, self._vmid)
        return self._owner.termproxy_response


class _VncproxyLeaf:
    def __init__(self, owner, node, vmid):
        self._owner, self._node, self._vmid = owner, node, vmid

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.last_vncproxy_call = (self._node, self._vmid)
        return self._owner.vncproxy_response


class _GuestNS:
    def __init__(self, owner, kind, node, vmid):
        self.status = _GuestStatusNS(owner, kind, vmid)
        self.termproxy = _TermproxyLeaf(owner, kind, node, vmid)
        self.config = _GuestConfigLeaf(owner, kind, vmid)
        self.snapshot = _SnapshotLeaf(owner, kind, vmid)
        if kind == "qemu":
            self.vncproxy = _VncproxyLeaf(owner, node, vmid)


class _GuestFactory:
    """nodes(n).lxc / nodes(n).qemu — callable with a vmid."""

    def __init__(self, owner, kind, node):
        self._owner, self._kind, self._node = owner, kind, node

    def __call__(self, vmid):
        return _GuestNS(self._owner, self._kind, self._node, int(vmid))


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
        self.rrddata = _KwLeaf(owner.rrd_by_node.get(name, []),
                                owner.fail or owner.rrd_fail)
        self.tasks = _TaskFactory(owner)
        self.lxc = _GuestFactory(owner, "lxc", name)
        self.qemu = _GuestFactory(owner, "qemu", name)
        self.termproxy = _TermproxyLeaf(owner, None, name, None)
        self.storage = _NodeStorageNS(owner, name)
        self.network = _NodeNetworkNS(owner, name)


class _NodesNS:
    def __init__(self, owner):
        self._owner = owner

    def __call__(self, name):
        return _NodeNS(self._owner, name)


class FakePVE:
    def __init__(self, version=None, permissions=None, fail=False,
                 resources=None, rrddata=None, task_exit="OK", running_ticks=0,
                 rrd_fail=False):
        self.fail = fail
        self.rrd_fail = rrd_fail  # independent of `fail`: lets tests fail the
        # rrddata leaf alone, since `fail` also gates _connect() itself.
        self.rrd_by_node = rrddata or {}
        self.version = _Leaf(version or {"version": "8.4.1", "release": "8.4"}, fail)
        self.access = _Access(permissions or {}, fail)
        # infra reads (Phase 6) — set before the namespaces below, which read
        # them lazily so a test can reassign any of these post-construction
        self.storages_by_node: dict[str, list[dict]] = {}
        self.storage_status_response: dict = {}
        self.content_by_storage: dict[str, list[dict]] = {}
        self.cluster_storage_rows: list[dict] = []
        self.networks_by_node: dict[str, list[dict]] = {}
        self.guest_configs: dict[tuple[str, int], dict] = {}
        self.snapshots_by_guest: dict[tuple[str, int], list[dict]] = {}
        self.nextid = "100"
        self.last_storage_status_call = None
        self.last_content_call = None
        self.storage = _AttrLeaf(self, "cluster_storage_rows")  # root /storage
        self.cluster = _ClusterNS(self, resources or [], fail)
        self.nodes = _NodesNS(self)
        self.kwargs = {}
        # lifecycle recording (Phase 3)
        self.actions: list[tuple[str, int, str]] = []
        self.task_exit = task_exit
        self.running_ticks = running_ticks
        self.task_lines: dict[str, list[str]] = {}
        self._polls: dict[str, int] = {}
        self._upid_n = 0
        # console calls (Phase 5)
        self.termproxy_response: dict = {}
        self.vncproxy_response: dict = {}
        self.last_termproxy_call = None
        self.last_node_termproxy_call = None
        self.last_vncproxy_call = None

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
