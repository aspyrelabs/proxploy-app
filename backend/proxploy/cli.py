"""The `proxploy` command. Currently: `proxploy audit export`.

doc 04 specifies this CLI by name. It exists so an operator can get the audit
trail out WITHOUT a working web session, which is exactly the situation an
audit export is most often needed in: nobody can log in, or the admin account
is locked out, or the box is being decommissioned. It therefore reads the
database directly rather than calling the API, and shares the row shape and
filters with `api/audit.py` so a CLI export and a UI export of the same window
cannot disagree.

Being local and direct is also why this is not an authentication bypass worth
worrying about: anyone who can run it already has the database file and the
master key, which is strictly more access than the export gives them.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime

from proxploy.api.audit import EXPORT_COLUMNS, _filtered, row_dict
from proxploy.config import get_settings
from proxploy.db import make_engine, make_sessionmaker
from proxploy.models import AuditEvent


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise SystemExit(f"not an ISO 8601 timestamp: {value!r}") from None


def audit_export(args: argparse.Namespace) -> int:
    settings = get_settings()
    db = make_sessionmaker(make_engine(settings))()
    try:
        q = (_filtered(db, args.action, args.actor,
                       _parse_ts(args.since), _parse_ts(args.until))
             .order_by(AuditEvent.ts.desc(), AuditEvent.id.desc()))

        out = open(args.out, "w", newline="") if args.out else sys.stdout
        try:
            if args.format == "jsonl":
                for r in q.yield_per(500):
                    out.write(json.dumps(row_dict(r)) + "\n")
            else:
                w = csv.DictWriter(out, fieldnames=EXPORT_COLUMNS,
                                   extrasaction="ignore")
                w.writeheader()
                for r in q.yield_per(500):
                    d = row_dict(r)
                    d["params"] = (json.dumps(d["params"])
                                   if d["params"] is not None else "")
                    w.writerow(d)
        finally:
            if out is not sys.stdout:
                out.close()
    finally:
        db.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="proxploy", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="group", required=True)

    audit = sub.add_parser("audit", help="audit trail tools")
    audit_sub = audit.add_subparsers(dest="command", required=True)

    exp = audit_sub.add_parser(
        "export", help="write the audit trail to a file or stdout",
        description="Reads the database directly; no web session needed.")
    exp.add_argument("--format", choices=("csv", "jsonl"), default="csv")
    exp.add_argument("--out", help="output file (default: stdout)")
    exp.add_argument("--action", help="exact action, e.g. app.uninstall")
    exp.add_argument("--actor", type=int, help="actor user id")
    exp.add_argument("--since", help="ISO 8601 lower bound on ts, inclusive")
    exp.add_argument("--until", help="ISO 8601 upper bound on ts, inclusive")
    exp.set_defaults(func=audit_export)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
