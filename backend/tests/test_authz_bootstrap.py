"""Phase 8 amendment A1: authorization is fail-closed, and the first-run
bootstrap owner is the stated exception.

Both directions are guarantees now, not incidental behavior. Before Phase 8,
`api/deps.py::user_role()` fell back to "viewer" for a user in no team, so a
membership-less account could read everything and a mistake in the bootstrap
path would have been invisible. `services/authz.py::enforce` has no such
fallback, which makes the bootstrap owner's membership load-bearing; hence
these two tests, driven through the real `POST /users` first-run route rather
than a hand-seeded row, so they fail if that route ever stops writing it.
"""
from proxploy.models import TeamMember, User
from proxploy.services.authz import build_enforcer, enforce
from tests.support import make_db


def test_a_user_in_no_team_is_denied_everything_including_reads(tmp_path):
    db = make_db(tmp_path)
    orphan = User(email="orphan@x.io")
    db.add(orphan)
    db.commit()
    e = build_enforcer(db)

    assert db.query(TeamMember).filter_by(user_id=orphan.id).count() == 0
    # Reads too: this is the behavior change A1 records. The old
    # user_role() default would have granted every one of these.
    for resource, action in (("host", "read"), ("app", "read"), ("vm", "read"),
                             ("metric", "read"), ("job", "read")):
        assert enforce(e, db, orphan, resource, action) is False
    assert enforce(e, db, orphan, "app", "lifecycle") is False


def test_the_first_run_bootstrap_owner_is_not_denied(client, csrf_header):
    """A fresh install must not be locked out of itself. `POST /users` on an
    empty users table forces role="owner" (doc 08 §8) and writes the matching
    TeamMember; that row is what the enforcer runs on."""
    r = client.post("/api/v1/users",
                    json={"email": "first@x.io", "display_name": "First",
                          "password": "Correct-Horse-Battery-9"},
                    headers=csrf_header(client))
    assert r.status_code == 201, r.text

    db = client.app.state.sessionmaker()
    owner = db.query(User).filter_by(email="first@x.io").one()
    membership = db.query(TeamMember).filter_by(user_id=owner.id).one()
    assert membership.role == "owner"

    e = build_enforcer(db)
    # Real owner permissions on a fresh database, not a fallback.
    assert enforce(e, db, owner, "host", "read") is True
    assert enforce(e, db, owner, "host", "manage") is True
    assert enforce(e, db, owner, "host", "remove") is True      # owner-only
    assert enforce(e, db, owner, "entitlement", "manage") is True  # owner-only
    # Fail-closed still holds for the bootstrap owner: an unknown pair denies.
    assert enforce(e, db, owner, "host", "not-an-action") is False
