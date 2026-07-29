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


class _NodeNS:
    def __init__(self, rrddata, fail):
        self.rrddata = _KwLeaf(rrddata, fail)


class _NodesNS:
    def __init__(self, rrd_by_node, fail):
        self._rrd, self._fail = rrd_by_node, fail

    def __call__(self, name):
        return _NodeNS(self._rrd.get(name, []), self._fail)


class FakePVE:
    def __init__(self, version=None, permissions=None, fail=False,
                 resources=None, rrddata=None):
        self.version = _Leaf(version or {"version": "8.4.1", "release": "8.4"}, fail)
        self.access = _Access(permissions or {}, fail)
        self.cluster = _ClusterNS(resources or [], fail)
        self.nodes = _NodesNS(rrddata or {}, fail)
        self.kwargs = {}


def make_fake_factory(fake: FakePVE):
    def factory(**kwargs):
        if fake.version._fail:
            raise ConnectionError("fake PVE unreachable")
        fake.kwargs = kwargs
        return fake
    return factory
