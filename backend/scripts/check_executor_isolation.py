#!/usr/bin/env python3
"""Hard structural rule (docs 08 §4, 09): no module outside proxploy/executor/ may
import the SSH client (asyncssh) or call the SecretStore accessor that returns the
SSH private key. Mechanical enforcement, not convention. Wired from Phase 1, 
passes trivially until executor/ exists in Phase 4."""
import argparse
import ast
import sys
from pathlib import Path

FORBIDDEN_IMPORTS = {"asyncssh"}
FORBIDDEN_NAMES = {"get_ssh_private_key"}


def violations(root: Path):
    for py in sorted(root.rglob("*.py")):
        rel = py.relative_to(root)
        if rel.parts and rel.parts[0] == "executor":
            continue
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {a.name.split(".")[0] for a in node.names}
                if names & FORBIDDEN_IMPORTS:
                    yield rel, node.lineno, "imports asyncssh"
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in FORBIDDEN_IMPORTS:
                    yield rel, node.lineno, "imports asyncssh"
            elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
                yield rel, node.lineno, f"references {node.id}"
            elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
                yield rel, node.lineno, f"references {node.attr}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=str(Path(__file__).resolve().parents[1] / "proxploy"))
    args = p.parse_args()
    found = list(violations(Path(args.root)))
    for rel, line, why in found:
        print(f"EXECUTOR-ISOLATION VIOLATION: {rel}:{line} {why}")
    if found:
        print(f"\n{len(found)} violation(s). Only proxploy/executor/ may touch the "
              "SSH client or the SSH-key accessor (docs 08 §4, 09).")
        return 1
    print("executor isolation: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
