#!/usr/bin/env bash
# The advertised one-liner takes NO arguments and arrives down a pipe. Every
# 9a harness passed --channel/--version/--pubkey explicitly AND ran
# `bash install.sh` from the repo root, where packaging/ sits right beside it,
# so the piped form nobody tested was exactly the form every user runs. That
# is why install.sh shipped for a while dying on line 21 against a real curl.
set -euo pipefail
cd "$(dirname "$0")/../.."

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

bash packaging/bundle_install.sh "$work/install.sh"

if grep -q 'BUNDLE:common.sh' "$work/install.sh"; then
  echo "FAIL: the bundle still carries the splice markers"; exit 1
fi
if grep -q 'SCRIPT_DIR/packaging' "$work/install.sh"; then
  echo "FAIL: the bundle still reads a file out of its own directory"; exit 1
fi
echo "OK: the bundle has no \$SCRIPT_DIR dependency left"

# Piped, from a directory with no packaging/ in it and none above it: this is
# the shape `curl -fsSL ... | bash` actually produces. Argument parsing and
# defaulting happen long before anything is fetched or installed, so a non-root
# dry parse proves it gets past them without a network or a release.
# shellcheck disable=SC2002 # The cat is the point: `bash -s < file` hands
# bash a seekable file, and `curl | bash` does not. A pipe is the shape
# under test, so the "useless" cat is what makes this a real reproduction.
out=$(cd "$work" && cat "$work/install.sh" | bash -s -- --shape systemd --dry-parse 2>&1) \
  || { echo "FAIL: the piped installer exited non-zero:"; echo "$out"; exit 1; }
case "$out" in
  *"dry parse ok"*) ;;
  *) echo "FAIL: the piped installer never reached the dry parse:"; echo "$out"; exit 1 ;;
esac
echo "OK: the published installer runs piped, with no file on disk"

case "$out" in
  *"--channel is required"*|*"--version is required"*|*"--pubkey is required"*)
    echo "FAIL: the no-argument form still demands flags:"; echo "$out"; exit 1 ;;
esac
echo "OK: install.sh has usable defaults for channel, version and pubkey"

# The domain pair comes from PROXPLOY_ENV and from nowhere else, so a future
# environment is one line in install.sh's case rather than a search-replace.
env_url() {  # env_url <PROXPLOY_ENV>
  ( cd "$work" && PROXPLOY_ENV="$1" bash -s -- --shape systemd --dry-parse \
      < "$work/install.sh" 2>&1 ) | sed -n 's/.*installer=\([^ ]*\).*/\1/p'
}
[ "$(env_url dev)" = "https://web.proxploy.dev/install.sh" ] \
  || { echo "FAIL: dev resolved to $(env_url dev)"; exit 1; }
[ "$(env_url prod)" = "https://proxploy.com/install.sh" ] \
  || { echo "FAIL: prod resolved to $(env_url prod)"; exit 1; }
# The DEFAULT, not just the explicit values. The published installer carried
# a dev default while it was served from proxploy.com, so a production install
# fetched its payload from web.proxploy.dev and licensed against
# api.proxploy.dev without saying so. Only an unset PROXPLOY_ENV reproduces
# that, which is why neither check above caught it.
default_url=$( cd "$work" && env -u PROXPLOY_ENV bash -s -- --shape systemd --dry-parse \
    < "$work/install.sh" 2>&1 | sed -n 's/.*installer=\([^ ]*\).*/\1/p' )
[ "$default_url" = "https://proxploy.com/install.sh" ] \
  || { echo "FAIL: with PROXPLOY_ENV unset the installer resolved to $default_url"; exit 1; }
echo "OK: the install URL follows PROXPLOY_ENV, and defaults to prod"

# The one-liner passes no flags, so --shape has to be worked out rather than
# demanded. Running it inside a CT you made yourself used to die on
# "--shape is required", which is a question the advertised URL never mentions.
shape_of() {  # shape_of <what systemd-detect-virt --container should say>
  ( cd "$work" && PATH="$work/bin:$PATH" FAKE_VIRT="$1" \
      bash -s -- --version 1.0.0 --dry-parse < "$work/install.sh" 2>&1 ) \
    | sed -n 's/.*shape=\([a-z]*\).*/\1/p'
}
mkdir -p "$work/bin"
cp packaging/tests/fake-systemd-detect-virt "$work/bin/systemd-detect-virt"
[ "$(shape_of lxc)" = "lxc" ] \
  || { echo "FAIL: inside a container, shape resolved to $(shape_of lxc)"; exit 1; }
[ "$(shape_of none)" = "systemd" ] \
  || { echo "FAIL: on a plain host, shape resolved to $(shape_of none)"; exit 1; }
echo "OK: --shape is detected, not demanded"

grep -q "BEGIN PUBLIC KEY" "$work/install.sh" \
  || { echo "FAIL: no release public key compiled into install.sh"; exit 1; }
echo "OK: the release public key is compiled in"

# The SAME key as backend/proxploy/release_pubkey.pem. There are two copies and
# they verify different things: this one is what a FIRST install checks the
# manifest against, that one is what an INSTALLED release checks the next
# release against. Publishing a release having replaced only one of them fails
# in a way that looks like a bad signature rather than a mismatched key, and
# only for new installs, so upgrades keep working and nobody notices.
sed -n '/BEGIN PUBLIC KEY/,/END PUBLIC KEY/p' "$work/install.sh" \
  | sed "s/^RELEASE_PUBKEY_PEM=//; s/'//g" > "$work/compiled.pem"
diff -q "$work/compiled.pem" backend/proxploy/release_pubkey.pem >/dev/null \
  || { echo "FAIL: install.sh's compiled key differs from backend/proxploy/release_pubkey.pem"
       diff "$work/compiled.pem" backend/proxploy/release_pubkey.pem || true; exit 1; }
echo "OK: both copies of the release public key agree"
echo "PASS: one-liner harness"
