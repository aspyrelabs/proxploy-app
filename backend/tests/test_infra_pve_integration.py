"""Phase 6 against a real, disposable PVE (doc 11 §7 matrix).

Skipped without the PROXPLOY_TEST_PVE_* env triple, like every other
live-PVE test in this repo. What only a real host can prove, and what the
fakes in tests/fakes/pve.py deliberately do not:

- that `/nodes/{node}/storage/{storage}/upload` accepts proxmoxer's
  multipart shape for a real multi-hundred-MB ISO rather than just the
  few-byte payload the fake accepts, and that the UPID it returns
  actually completes;
- that a vzdump of a real CT to a real PBS datastore, and a restore of
  that archive as a NEW ctid, both succeed; the one DoD clause with the
  most moving upstream parts;
- that `/nodes/{node}/network` PUT (apply) behaves as documented on both
  PVE 8.x and 9.x, the single most dangerous call in the phase;
- that prunebackups' dry-run GET really deletes nothing.
"""
import os

import pytest

pytestmark = pytest.mark.pve_integration

_ENV = ("PROXPLOY_TEST_PVE_URL", "PROXPLOY_TEST_PVE_TOKEN_ID",
        "PROXPLOY_TEST_PVE_TOKEN_SECRET")


@pytest.mark.skipif(not all(os.environ.get(k) for k in _ENV),
                    reason="needs a disposable live PVE (PROXPLOY_TEST_PVE_*)")
def test_phase6_against_live_pve():
    pytest.skip("fill in against the disposable PVE fixture once one is "
                "available (doc 11 §7), no live PVE on this box, the "
                "standing limitation every phase has stated")
