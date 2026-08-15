"""Teams CRUD + membership (doc 05 Teams row, Task 6). ROUTE TEMPLATE:
authorize -> require_entitlement -> work -> audit (hosts.py idiom).

Both `_read` and `_manage` are deliberately GLOBAL (no scope_of): unlike
host/app/vm, which are scoped to the team that owns them, "team" itself is
the multi-tenancy admin plane, same status as ("user", "manage"). An owner
with membership in only the default team still needs to administer a
brand-new team that has zero members yet -- scoping team,manage to the
team_id in the path would lock its own creator out of populating it, since
enforce()'s domain-scoped branch requires a g-line IN that exact domain.
Every membership write calls sync_user() after commit: the enforcer is
in-memory (services/authz.py docstring), so skipping this leaves the change
invisible until the process restarts.
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from proxploy.api.deps import ROLE_ORDER, authorize, get_db, require_entitlement
from proxploy.models import Host, Team, TeamMember, User
from proxploy.services.audit import write_audit
from proxploy.services.authz import build_enforcer, sync_user

router = APIRouter(prefix="/teams", tags=["teams"])

_read = authorize("team", "read")
_manage = authorize("team", "manage")
_ENT = require_entitlement("teams.rbac")


class TeamIn(BaseModel):
    name: str
    slug: str | None = None
    description: str | None = None


class TeamPatchIn(BaseModel):
    name: str | None = None
    description: str | None = None


class MemberIn(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def _known_role(cls, v: str) -> str:
        if v not in ROLE_ORDER:
            raise ValueError("unknown role")
        return v


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "team"


def _team_out(db, t: Team) -> dict:
    member_count = db.query(TeamMember).filter_by(team_id=t.id).count()
    if t.slug == "default":
        # A NULL hosts.team_id means "the default team" everywhere else in
        # the product (api/deps.py::_team_of_host) -- count those hosts too.
        host_count = (db.query(Host)
                      .filter((Host.team_id == t.id) | (Host.team_id.is_(None)))
                      .count())
    else:
        host_count = db.query(Host).filter_by(team_id=t.id).count()
    return {"id": t.id, "name": t.name, "slug": t.slug, "description": t.description,
            "member_count": member_count, "host_count": host_count}


def _member_out(u: User, role: str) -> dict:
    return {"user_id": u.id, "email": u.email, "display_name": u.display_name,
            "role": role}


@router.get("", dependencies=[Depends(_read), Depends(_ENT)])
def list_teams(db=Depends(get_db)):
    return [_team_out(db, t) for t in db.query(Team).order_by(Team.id)]


@router.post("", status_code=201, dependencies=[Depends(_manage), Depends(_ENT)])
def create_team(body: TeamIn, db=Depends(get_db), user: User = Depends(_manage)):
    slug = body.slug or _slugify(body.name)
    if db.query(Team).filter_by(name=body.name).one_or_none():
        raise HTTPException(409, "team name already exists")
    if db.query(Team).filter_by(slug=slug).one_or_none():
        raise HTTPException(409, "team slug already exists")
    t = Team(name=body.name, slug=slug, description=body.description)
    db.add(t)
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="team.create",
                target_type="team", target_id=t.id,
                params={"name": t.name, "slug": t.slug})
    return _team_out(db, t)


@router.patch("/{team_id}", dependencies=[Depends(_manage), Depends(_ENT)])
def patch_team(team_id: int, body: TeamPatchIn, db=Depends(get_db),
              user: User = Depends(_manage)):
    t = db.get(Team, team_id)
    if t is None:
        raise HTTPException(404, "team not found")
    changes = {}
    if body.name is not None and body.name != t.name:
        if db.query(Team).filter(Team.name == body.name, Team.id != t.id).one_or_none():
            raise HTTPException(409, "team name already exists")
        t.name = body.name
        changes["name"] = body.name
    if body.description is not None:
        t.description = body.description
        changes["description"] = body.description
    db.commit()
    write_audit(db, actor_type="user", actor_id=user.id, action="team.update",
                target_type="team", target_id=t.id, params=changes)
    return _team_out(db, t)


@router.delete("/{team_id}", dependencies=[Depends(_manage), Depends(_ENT)])
def delete_team(team_id: int, request: Request, db=Depends(get_db),
                user: User = Depends(_manage)):
    t = db.get(Team, team_id)
    if t is None:
        raise HTTPException(404, "team not found")
    if t.slug == "default":
        raise HTTPException(409, "cannot delete the default team")
    # hosts.team_id has no ON DELETE clause and foreign_keys=ON (db.py) --
    # revert hosts to the default team (team_id=NULL) before the row goes
    # away. team_members cascades on its own (ondelete=CASCADE).
    db.query(Host).filter_by(team_id=t.id).update({"team_id": None})
    db.delete(t)
    db.commit()
    # team_members cascades in the DB, but casbin keeps its own g-lines keyed
    # on the team id and enforce() trusts them without ever re-reading the
    # table. SQLite hands the same rowid to the next team created, which would
    # inherit this team's grants. Rebuild rather than sync_user: the members
    # are gone, so there is nothing left to sync policies FOR.
    request.app.state.authz = build_enforcer(db)
    write_audit(db, actor_type="user", actor_id=user.id, action="team.delete",
                target_type="team", target_id=team_id, params={"slug": t.slug})
    return {"ok": True}


@router.get("/{team_id}/members", dependencies=[Depends(_read), Depends(_ENT)])
def list_members(team_id: int, db=Depends(get_db)):
    t = db.get(Team, team_id)
    if t is None:
        raise HTTPException(404, "team not found")
    rows = (db.query(TeamMember, User)
            .join(User, User.id == TeamMember.user_id)
            .filter(TeamMember.team_id == team_id))
    return [_member_out(u, m.role) for m, u in rows]


@router.put("/{team_id}/members/{user_id}",
           dependencies=[Depends(_manage), Depends(_ENT)])
def set_member(team_id: int, user_id: int, body: MemberIn, request: Request,
              db=Depends(get_db), user: User = Depends(_manage)):
    t = db.get(Team, team_id)
    if t is None:
        raise HTTPException(404, "team not found")
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "user not found")
    m = db.query(TeamMember).filter_by(team_id=team_id, user_id=user_id).one_or_none()
    if m is None:
        m = TeamMember(team_id=team_id, user_id=user_id, role=body.role)
        db.add(m)
    else:
        m.role = body.role
    db.commit()
    sync_user(request.app.state.authz, db, user_id)
    write_audit(db, actor_type="user", actor_id=user.id, action="team.member.set",
                target_type="team", target_id=team_id,
                params={"user_id": user_id, "role": body.role})
    return _member_out(target, m.role)


@router.delete("/{team_id}/members/{user_id}",
              dependencies=[Depends(_manage), Depends(_ENT)])
def remove_member(team_id: int, user_id: int, request: Request, db=Depends(get_db),
                  user: User = Depends(_manage)):
    t = db.get(Team, team_id)
    if t is None:
        raise HTTPException(404, "team not found")
    m = db.query(TeamMember).filter_by(team_id=team_id, user_id=user_id).one_or_none()
    if m is None:
        raise HTTPException(404, "membership not found")
    if t.slug == "default" and m.role == "owner":
        owners = db.query(TeamMember).filter_by(team_id=team_id, role="owner").count()
        if owners <= 1:
            raise HTTPException(409, "cannot remove the last owner")
    db.delete(m)
    db.commit()
    sync_user(request.app.state.authz, db, user_id)
    write_audit(db, actor_type="user", actor_id=user.id, action="team.member.remove",
                target_type="team", target_id=team_id, params={"user_id": user_id})
    return {"ok": True}
