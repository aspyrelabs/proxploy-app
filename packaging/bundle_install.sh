#!/usr/bin/env bash
# Splice packaging/lib/common.sh into install.sh, producing the single file
# published at the install URL.
#
# The one-liner (`curl -fsSL .../install.sh | bash`) hands bash a pipe, not a
# path: the script has no directory of its own, so it cannot source anything
# beside it. Rather than duplicating common.sh in the repo, the shared copy is
# spliced in at publish time. install.sh keeps working from a checkout, and
# common.sh stays a real file for packaging/proxploy-update and
# build_release.sh, which both source it.
#
# Nothing else needs splicing: the other four support files (proxploy-update,
# common.sh's installed copy, proxploy.service, caddy/Caddyfile.tmpl) are read
# out of the unpacked release, which by then has been fetched and had its
# manifest signature verified.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
out="${1:-}"
[ -n "$out" ] || { echo "usage: bundle_install.sh <out-install.sh>" >&2; exit 1; }

python3 - "$root/install.sh" "$root/packaging/lib/common.sh" "$out" <<'PY'
import sys

src, lib, out = sys.argv[1], sys.argv[2], sys.argv[3]
START, END = "# >>> BUNDLE:common.sh >>>", "# <<< BUNDLE:common.sh <<<"

text = open(src).read()
a, b = text.find(START), text.find(END)
if a < 0 or b < 0:
    sys.exit(f"{src}: BUNDLE:common.sh markers not found")

# The shebang goes: this lands mid-file, where it is at best a comment and at
# worst confusing. `set -euo pipefail` goes too, install.sh sets it on line 14
# and a second copy would suggest the two could differ.
body = [ln for ln in open(lib).read().splitlines()
        if not ln.startswith("#!") and ln.strip() != "set -euo pipefail"]

spliced = (text[:a]
           + "# --- packaging/lib/common.sh, spliced in by "
             "packaging/bundle_install.sh ---\n"
           + "\n".join(body).strip("\n") + "\n"
           + "# --- end packaging/lib/common.sh ---"
           + text[b + len(END):])
open(out, "w").write(spliced)
PY

chmod 0755 "$out"
bash -n "$out" || { echo "error: bundled installer is not valid bash" >&2; exit 1; }
echo "  wrote $out" >&2
