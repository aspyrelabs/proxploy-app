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


class _Access:
    def __init__(self, permissions, fail):
        self.permissions = _Leaf(permissions, fail)


class FakePVE:
    def __init__(self, version=None, permissions=None, fail=False):
        self.version = _Leaf(version or {"version": "8.4.1", "release": "8.4"}, fail)
        self.access = _Access(permissions or {}, fail)
        self.kwargs = {}


def make_fake_factory(fake: FakePVE):
    def factory(**kwargs):
        if fake.version._fail:
            raise ConnectionError("fake PVE unreachable")
        fake.kwargs = kwargs
        return fake
    return factory
