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


class _PermissionsLeaf:
    """`/access/permissions`, which a real PVE may refuse to a token even while
    /version succeeds. `_missing_privileges` and `_capability_gaps` both treat
    that as "could not tell" rather than "nothing missing", so it needs to be
    reachable in a test without failing the whole fake."""

    def __init__(self, owner, permissions, fail):
        self._owner, self._value, self._fail = owner, permissions, fail

    def get(self, **kwargs):
        if self._fail or getattr(self._owner, "permissions_fail", False):
            raise ConnectionError("fake PVE refused /access/permissions")
        return self._value


class _Access:
    def __init__(self, owner, permissions, fail):
        self.permissions = _PermissionsLeaf(owner, permissions, fail)


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


class _VolumeLeaf:
    """nodes(n).storage(s).content(volid).delete() records and mints a UPID."""

    def __init__(self, owner, node, storage, volid):
        self._owner, self._node = owner, node
        self._storage, self._volid = storage, volid

    def delete(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.deleted_volumes.append((self._node, self._storage, self._volid))
        return self._owner._record_action("storage", 0, "delvolume")


class _StorageContentNS:
    """.get() lists volumes; calling it drills into one volid."""

    def __init__(self, owner, node, storage):
        self._owner, self._node, self._storage = owner, node, storage

    def get(self, **kwargs):
        if self._owner.fail or self._storage in self._owner.content_fail_storages:
            raise ConnectionError("fake PVE unreachable")
        self._owner.last_content_call = (self._node, self._storage,
                                         kwargs.get("content"))
        rows = self._owner.content_by_storage.get(self._storage, [])
        want = kwargs.get("content")
        return [r for r in rows if not want or r.get("content") == want]

    def __call__(self, volid):
        return _VolumeLeaf(self._owner, self._node, self._storage, volid)


class _UploadLeaf:
    def __init__(self, owner, node, storage):
        self._owner, self._node, self._storage = owner, node, storage

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        fh = kwargs.get("filename")
        self._owner.uploads.append({
            "node": self._node, "storage": self._storage,
            "content": kwargs.get("content"),
            "filename": getattr(fh, "name", ""),
            "bytes": fh.read() if hasattr(fh, "read") else b""})
        return self._owner._record_action("storage", 0, "upload")


class _PruneLeaf:
    """nodes(n).storage(s).prunebackups.get() previews.delete() deletes.
    Recorded separately so a test can prove the preview never deletes."""

    def __init__(self, owner, node, storage):
        self._owner, self._node, self._storage = owner, node, storage

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.prune_gets.append((self._node, self._storage, kwargs))
        return self._owner.prune_preview_rows

    def delete(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.prune_deletes.append((self._node, self._storage, kwargs))
        return self._owner._record_action("prune", 0, "prune")


class _NodeStorageNS:
    """nodes(n).storage(name), the per-datastore subtree."""

    def __init__(self, owner, node, storage):
        self.status = _StorageStatusLeaf(owner, node, storage)
        self.content = _StorageContentNS(owner, node, storage)
        self.upload = _UploadLeaf(owner, node, storage)
        self.prunebackups = _PruneLeaf(owner, node, storage)


class _NodeStorageFactory:
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
        return _NodeStorageNS(self._owner, self._node, storage)


class _NetworkNS:
    """nodes(n).network.get() lists.post/.put/.delete stage.put() with no
    iface applies (returns a UPID), .delete() with no iface reverts. Callable
    for nodes(n).network(iface)."""

    def __init__(self, owner, node, iface=None):
        self._owner, self._node, self._iface = owner, node, iface

    def __call__(self, iface):
        return _NetworkNS(self._owner, self._node, str(iface))

    def _check(self):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")

    def get(self, **kwargs):
        self._check()
        # Only the READ is refusable per-section: the host page's hardware tab
        # reads this list, the staging calls below are a different privilege.
        if "network" in self._owner.hardware_fail_sections:
            raise ConnectionError("fake PVE refuses network")
        rows = self._owner.networks_by_node.get(self._node, [])
        want = kwargs.get("type")
        return [r for r in rows if want is None or r.get("type") == want]

    def post(self, **cfg):
        self._check()
        self._owner.network_calls.append(("create", self._node, None, dict(cfg)))

    def put(self, **cfg):
        self._check()
        if self._iface is None:
            self._owner.network_calls.append(("apply", self._node, None, dict(cfg)))
            return self._owner._record_action("network", 0, "apply")
        self._owner.network_calls.append(("update", self._node, self._iface, dict(cfg)))

    def delete(self, **kwargs):
        self._check()
        op = "revert" if self._iface is None else "delete"
        self._owner.network_calls.append((op, self._node, self._iface, dict(kwargs)))


class _GuestConfigLeaf:
    """nodes(n).lxc(vmid).config / .qemu(vmid).config.get() reads.put() records."""

    def __init__(self, owner, kind, vmid):
        self._owner, self._kind, self._vmid = owner, kind, vmid

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        return dict(self._owner.guest_configs.get((self._kind, self._vmid), {}))

    def put(self, **cfg):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.config_updates.append((self._kind, self._vmid, dict(cfg)))
        self._owner.guest_configs.setdefault((self._kind, self._vmid), {}).update(cfg)
        return self._owner.config_update_upid


class _RollbackLeaf:
    def __init__(self, owner, kind, node, vmid, name):
        self._owner, self._kind = owner, kind
        self._node, self._vmid, self._name = node, vmid, name

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.snapshot_rollbacks.append(
            (self._kind, self._node, self._vmid, self._name))
        return self._owner._record_action(self._kind, self._vmid, "rollback")


class _SnapshotItemNS:
    """nodes(n).<kind>(vmid).snapshot(name).rollback.post() and .delete()."""

    def __init__(self, owner, kind, node, vmid, name):
        self._owner, self._kind = owner, kind
        self._node, self._vmid, self._name = node, vmid, name
        self.rollback = _RollbackLeaf(owner, kind, node, vmid, name)

    def delete(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.snapshot_deletes.append(
            (self._kind, self._node, self._vmid, self._name))
        return self._owner._record_action(self._kind, self._vmid, "snapdelete")


class _SnapshotNS:
    """nodes(n).<kind>(vmid).snapshot.get() lists.post() creates, and the
    object itself is callable with a snapshot name (proxmoxer's own shape)."""

    def __init__(self, owner, kind, node, vmid):
        self._owner, self._kind, self._node, self._vmid = owner, kind, node, vmid

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        return self._owner.snapshots_by_guest.get((self._kind, self._vmid), [])

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.snapshot_creates.append(
            (self._kind, self._node, self._vmid, kwargs))
        return self._owner._record_action(self._kind, self._vmid, "snapshot")

    def __call__(self, name):
        return _SnapshotItemNS(self._owner, self._kind, self._node, self._vmid,
                               name)


class _NextidLeaf:
    """cluster.nextid, increments nextid_calls so a test can prove a
    caller-supplied vmid never asked PVE for one (Phase 6 Task 11)."""

    def __init__(self, owner):
        self._owner = owner

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.nextid_calls += 1
        return str(self._owner.nextid)


class _ClusterConfigNS:
    """cluster.config.join.get(), which carries pve_addr and pve_fp per node.

    Separate from cluster.status on purpose: PVE reports the corosync address
    there and the API address here, and peer discovery prefers the latter.
    """

    def __init__(self, owner):
        self.join = _AttrLeaf(owner, "cluster_join_info")


class _ClusterNS:
    def __init__(self, owner, resources, fail):
        self.resources = _KwLeaf(resources, fail)
        self.nextid = _NextidLeaf(owner)  # PVE returns a string
        # Phase 8 Task 14: lazy attr leaf (like storages_by_node) so a test can
        # assign fake.cluster_status_rows after construction.
        self.status = _AttrLeaf(owner, "cluster_status_rows")
        self.config = _ClusterConfigNS(owner)


class _ActionLeaf:
    """nodes(n).lxc(vmid).status.<action>.post() records and mints a UPID."""

    def __init__(self, owner, kind, vmid, action):
        self._owner, self._kind, self._vmid, self._action = owner, kind, vmid, action

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        # `action_error` makes the guest action itself fail the way PVE does
        # (a 500 with a sentence), as opposed to `task_exit`, which fails the
        # task AFTER it was accepted. Stop-on-a-stopped-guest is the first case
        # that needed the distinction.
        if self._owner.action_error:
            raise RuntimeError(f"500 Internal Server Error: {self._owner.action_error}")
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
        if self._owner.proxy_error is not None:
            raise self._owner.proxy_error
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
        if self._owner.proxy_error is not None:
            raise self._owner.proxy_error
        self._owner.last_vncproxy_call = (self._node, self._vmid)
        return self._owner.vncproxy_response


class _CloneLeaf:
    def __init__(self, owner, node, vmid):
        self._owner, self._node, self._vmid = owner, node, vmid

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        # recorded BEFORE the injected failure so a test can prove exactly one
        # attempt was made and nothing retried
        self._owner.clones.append((self._node, self._vmid, kwargs))
        if self._owner.clone_error:
            raise RuntimeError(self._owner.clone_error)
        return self._owner._record_action("qemu", int(kwargs.get("newid", 0)),
                                          "clone")


class _MigrateLeaf:
    """nodes(n).<kind>(vmid).migrate.post() records (kind, node, vmid,
    params) into fake.migrations and mints a UPID via _record_action
    (Phase 8 Task 14/15)."""

    def __init__(self, owner, kind, node, vmid):
        self._owner, self._kind, self._node, self._vmid = owner, kind, node, vmid

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.migrations.append((self._kind, self._node, self._vmid, dict(kwargs)))
        return self._owner._record_action(self._kind, self._vmid, "migrate")


class _GuestNS:
    def __init__(self, owner, kind, node, vmid):
        self._owner, self._kind, self._node, self._vmid = owner, kind, node, vmid
        self.status = _GuestStatusNS(owner, kind, vmid)
        self.termproxy = _TermproxyLeaf(owner, kind, node, vmid)
        self.config = _GuestConfigLeaf(owner, kind, vmid)
        self.snapshot = _SnapshotNS(owner, kind, node, vmid)
        self.migrate = _MigrateLeaf(owner, kind, node, vmid)
        if kind == "qemu":
            self.vncproxy = _VncproxyLeaf(owner, node, vmid)
            self.clone = _CloneLeaf(owner, node, vmid)

    def delete(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.guest_deletes.append((self._kind, self._node, self._vmid))
        return self._owner._record_action(self._kind, self._vmid, "destroy")


class _GuestFactory:
    """nodes(n).lxc / nodes(n).qemu, callable with a vmid, and postable for
    the guest create/restore endpoint (Phase 6 Task 9; Task 11's vm_create
    reuses this same .post())."""

    def __init__(self, owner, kind, node):
        self._owner, self._kind, self._node = owner, kind, node

    def __call__(self, vmid):
        return _GuestNS(self._owner, self._kind, self._node, int(vmid))

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.creates.append((self._kind, self._node, kwargs))
        if self._owner.create_error:
            raise RuntimeError(self._owner.create_error)
        return self._owner._record_action(self._kind, int(kwargs.get("vmid", 0)),
                                          "create")


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

    def get(self, **kwargs):
        """nodes(n).tasks.get() lists the node's recent tasks.

        Records the call so a test can prove the limit was passed through
        rather than the whole history being pulled.
        """
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.task_list_calls.append(kwargs)
        return self._owner.node_task_rows


class _ClusterStorageLeaf:
    """root .storage(name), the cluster-level storage definition."""

    def __init__(self, owner, name):
        self._owner, self._name = owner, name

    def put(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.storage_updates.append((self._name, kwargs))
        return None

    def delete(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.storage_removes.append(self._name)
        return None


class _ClusterStorageFactory:
    """root .storage.get() lists definitions.post() creates one,
    calling it drills into a named definition. All three are synchronous in
    Proxmox and return no UPID, so none of them mints one here either."""

    def __init__(self, owner):
        self._owner = owner

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        return self._owner.cluster_storage_rows

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.storage_creates.append(kwargs)
        self._owner.cluster_storage_rows.append(dict(kwargs))
        return None

    def __call__(self, name):
        return _ClusterStorageLeaf(self._owner, name)


class _VzdumpLeaf:
    def __init__(self, owner, node):
        self._owner, self._node = owner, node

    def post(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        self._owner.vzdumps.append((self._node, kwargs))
        # ponytail deviation from the brief's literal snippet: `vmid` here may
        # be a comma-joined multi-guest string ("150,201") or absent entirely
        # (the `all=1` selection), and `int()` on either raises: this only
        # needs a *number* for the synthetic UPID, not the real selection.
        raw = kwargs.get("vmid", 0) or 0
        try:
            vmid = int(raw)
        except (TypeError, ValueError):
            vmid = 0
        return self._owner._record_action("vzdump", vmid, "vzdump")


class _SectionLeaf:
    """One host-page section read, refusable on its own.

    A real node refuses these individually: a token without Sys.Audit answers
    /subscription and rejects /hardware/pci, and a PVE too old simply has no
    such path. `fail` is all-or-nothing across the fake, which cannot express
    that, so `hardware_fail_sections` names the sections that raise while
    their siblings still answer.
    """

    def __init__(self, owner, section, mapping_attr, node, default):
        self._owner, self._section = owner, section
        self._attr, self._node, self._default = mapping_attr, node, default

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        if self._section in self._owner.hardware_fail_sections:
            raise ConnectionError(f"fake PVE refuses {self._section}")
        return getattr(self._owner, self._attr).get(self._node, self._default)


class _DisksNS:
    """/nodes/{node}/disks/list -- a namespace, not a leaf, because `list` is a
    path segment here rather than a method."""

    def __init__(self, owner, name):
        self.list = _SectionLeaf(owner, "disks", "disks_by_node", name, [])


class _HardwareNS:
    """/nodes/{node}/hardware/pci -- `hardware` is a path segment, not a leaf."""

    def __init__(self, owner, name):
        self.pci = _SectionLeaf(owner, "pci", "pci_by_node", name, [])


class _NodeStatusLeaf:
    """nodes(n).status: GET reads /nodes/{n}/status (cpuinfo etc, host page);
    POST is the DIFFERENT verb /nodes/{n}/status?command=reboot|shutdown, the
    node power action (host actions menu). Same path, proxmoxer disambiguates
    by HTTP method, so this fake does too."""

    def __init__(self, owner, node):
        self._owner, self._node = owner, node

    def get(self, **kwargs):
        if self._owner.fail:
            raise ConnectionError("fake PVE unreachable")
        if self._node in self._owner.status_forbidden_nodes:
            # Same realistic shape as power_forbidden_nodes below, for a GET
            # rather than the node-power POST: proves the generic 403 ->
            # kind="permission" classification (services/proxmox.py::_classify)
            # is not special-cased to node_power alone.
            raise RuntimeError(f"403 Forbidden: Permission check failed "
                               f"(/nodes/{self._node}, Sys.Audit)")
        return self._owner.node_status_by_node.get(self._node, {})

    def post(self, **kwargs):
        if self._owner.fail or self._node in self._owner.power_fail_nodes:
            raise ConnectionError("fake PVE unreachable")
        if self._node in self._owner.power_forbidden_nodes:
            # The exact shape real Proxmox returns for a token missing
            # Sys.PowerMgmt, so ProxmoxClient.node_power's own detection of a
            # 403 is exercised against realistic text, not an invented one.
            raise RuntimeError(f"403 Forbidden: Permission check failed "
                               f"(/nodes/{self._node}, Sys.PowerMgmt)")
        self._owner.node_power_calls.append((self._node, kwargs.get("command")))
        return self._owner._record_action("node", 0, kwargs.get("command") or "power")


class _NodeNS:
    def __init__(self, owner, name):
        self.rrddata = _KwLeaf(owner.rrd_by_node.get(name, []),
                                owner.fail or owner.rrd_fail)
        self.tasks = _TaskFactory(owner)
        self.lxc = _GuestFactory(owner, "lxc", name)
        self.qemu = _GuestFactory(owner, "qemu", name)
        self.termproxy = _TermproxyLeaf(owner, None, name, None)
        self.storage = _NodeStorageFactory(owner, name)
        self.network = _NetworkNS(owner, name)
        self.vzdump = _VzdumpLeaf(owner, name)
        # The host page's own on-demand reads (doc: host-page spec). Read
        # lazily from the owner so a test can assign after construction.
        self.status = _NodeStatusLeaf(owner, name)
        self.disks = _DisksNS(owner, name)
        self.hardware = _HardwareNS(owner, name)
        self.services = _SectionLeaf(owner, "services", "services_by_node", name, [])
        self.subscription = _SectionLeaf(
            owner, "subscription", "subscription_by_node", name, {})
        self.dns = _SectionLeaf(owner, "dns", "dns_by_node", name, {})
        self.time = _SectionLeaf(owner, "time", "time_by_node", name, {})


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
        self.node_status_by_node: dict[str, dict] = {}
        # nodes(n).status.post(command=...): the host actions menu's
        # reboot/power off. Recorded as (node, command) tuples so a test can
        # assert exactly what was sent, same idiom as self.migrations etc.
        self.node_power_calls: list[tuple[str, str]] = []
        self.power_fail_nodes: set[str] = set()
        # Nodes where the token is reachable but lacks Sys.PowerMgmt: a
        # 403, distinct from power_fail_nodes' unreachable-node simulation.
        self.power_forbidden_nodes: set[str] = set()
        # Nodes where GET /nodes/{n}/status 403s (e.g. Sys.Audit missing),
        # distinct from `fail`'s all-or-nothing unreachable simulation.
        self.status_forbidden_nodes: set[str] = set()
        self.disks_by_node: dict[str, list[dict]] = {}
        # the rest of the host page's hardware tab, same lazy pattern
        self.pci_by_node: dict[str, list[dict]] = {}
        self.services_by_node: dict[str, list[dict]] = {}
        self.subscription_by_node: dict[str, dict] = {}
        self.dns_by_node: dict[str, dict] = {}
        self.time_by_node: dict[str, dict] = {}
        # section names ("disks", "network", "pci", "services", "subscription",
        # "dns", "time") that raise while their siblings answer, which `fail`
        # cannot express.
        self.hardware_fail_sections: set[str] = set()
        self.version = _Leaf(version or {"version": "8.4.1", "release": "8.4"}, fail)
        self.permissions_fail = False
        self.access = _Access(self, permissions or {}, fail)
        # infra reads (Phase 6): set before the namespaces below, which read
        # them lazily so a test can reassign any of these post-construction
        # Set to a PVE error sentence to make a guest ACTION (start/stop/...)
        # fail at the POST, as distinct from task_exit, which fails the task
        # after PVE accepted it.
        self.action_error: str | None = None
        self.storages_by_node: dict[str, list[dict]] = {}
        self.storage_status_response: dict = {}
        self.content_by_storage: dict[str, list[dict]] = {}
        # per-storage failure injection (Phase 6 Task 8 review): a storage
        # name in here raises on .content.get() while its siblings succeed, 
        # unlike `fail`, which is all-or-nothing across the whole fake.
        self.content_fail_storages: set[str] = set()
        self.cluster_storage_rows: list[dict] = []
        # cluster membership (Phase 8 Task 14): [] means "standalone node",
        # matching real PVE's /cluster/status shape for a non-clustered host.
        self.cluster_status_rows: list[dict] = []
        self.networks_by_node: dict[str, list[dict]] = {}
        # host network staging (Phase 6 Task 7): (op, node, iface|None, config)
        self.network_calls: list[tuple[str, str, str | None, dict]] = []
        self.guest_configs: dict[tuple[str, int], dict] = {}
        # guest config writes (Phase 6 Task 6)
        self.config_updates: list[tuple[str, int, dict]] = []
        self.config_update_upid: str | None = None
        self.snapshots_by_guest: dict[tuple[str, int], list[dict]] = {}
        self.nextid = "100"
        self.nextid_calls = 0
        self.last_storage_status_call = None
        self.last_content_call = None
        self.storage = _ClusterStorageFactory(self)
        # storage definition management (Phase 6)
        self.storage_creates: list[dict] = []
        self.storage_updates: list[tuple] = []
        self.storage_removes: list[str] = []
        # `list(resources)` copies whatever a test passed via `resources=`, 
        # a test never gets a handle on this list itself, only on the copy.
        # Stored as an attribute (not just captured inside _ClusterNS) so
        # add_ct() below can append to it after construction and have
        # cluster.resources.get() see the same list by reference from then on.
        self.resources: list[dict] = list(resources) if resources else []
        self.cluster = _ClusterNS(self, self.resources, fail)
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
        # An exception for termproxy/node_termproxy/vncproxy to raise, so a
        # token too narrow for the console (no Sys.Console) can be modelled.
        # `fail` already covers "node unreachable"; this covers "node answered,
        # and said no".
        self.proxy_error: Exception | None = None
        # GET /cluster/config/join. Empty by default, which is what makes every
        # test written before peer discovery read pve_addr behave exactly as it
        # did: no nodelist means no API addresses, so callers fall back to the
        # address in cluster_status.
        self.cluster_join_info: dict = {}
        self.last_termproxy_call = None
        self.last_node_termproxy_call = None
        self.last_vncproxy_call = None
        # storage content mutations (Phase 6)
        self.uploads: list[dict] = []
        self.deleted_volumes: list[tuple] = []
        # backup / restore / prune recording (Phase 6 Task 9)
        self.vzdumps: list[tuple[str, dict]] = []
        self.creates: list[tuple[str, str, dict]] = []
        self.prune_gets: list[tuple[str, str, dict]] = []
        self.prune_deletes: list[tuple[str, str, dict]] = []
        self.prune_preview_rows: list[dict] = []
        # snapshot recording (Phase 6, Task 10)
        self.snapshot_creates: list[tuple[str, str, int, dict]] = []
        self.snapshot_rollbacks: list[tuple[str, str, int, str]] = []
        self.snapshot_deletes: list[tuple[str, str, int, str]] = []
        # guest create/clone/destroy (Phase 6, Task 11): `creates` and `nextid`
        # already exist from Tasks 9 and 1
        self.clones: list[tuple[str, int, dict]] = []
        self.guest_deletes: list[tuple[str, str, int]] = []
        self.create_error: str | None = None
        self.clone_error: str | None = None
        # migration (Phase 8 Task 14/15): (kind, node, vmid, params)
        self.migrations: list[tuple[str, str, int, dict]] = []
        # node task-log passthrough (PXP-17): what nodes(n).tasks.get() returns,
        # and the kwargs each call passed so a test can prove `limit` travels.
        self.node_task_rows: list[dict] = []
        self.task_list_calls: list[dict] = []

    def add_ct(self, vmid: int, *, node: str = "pve1", name: str = "ct",
              status: str = "running", **extra) -> dict:
        """Append an LXC row to /cluster/resources (Phase 7 Task 5: the
        app.update before/after CT-existence guards read this live, never the
        poller's cached snapshot)."""
        row = {"type": "lxc", "vmid": vmid, "node": node, "name": name,
              "status": status, **extra}
        self.resources.append(row)
        return row

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


def make_addressed_factory(fakes: dict[str, "FakePVE"]):
    """Two-host tests (Phase 8 Task 14): one FakePVE per host, keyed by the
    hostname the client's factory is called with (ProxmoxClient passes
    host=<hostname parsed from Host.address>, see ProxmoxClient._connect)."""
    def factory(**kwargs):
        fake = fakes[kwargs["host"]]
        if fake.fail:
            raise ConnectionError("fake PVE unreachable")
        fake.kwargs = kwargs
        return fake
    return factory
