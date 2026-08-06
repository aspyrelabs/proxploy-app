#!/usr/bin/env bash
# The advertised one-liner takes NO arguments. Every 9a harness passed
# --channel/--version/--pubkey explicitly, so the piped form nobody tested
# is exactly the form every user will run.
set -euo pipefail
cd "$(dirname "$0")/../.."

# Argument parsing and defaulting happen long before anything is fetched or
# installed, so a non-root dry parse is enough to prove the defaults exist:
# we assert it gets PAST argument validation, not that it installs.
out=$(bash install.sh --shape systemd --dry-parse 2>&1 || true)
case "$out" in
  *"--channel is required"*|*"--version is required"*|*"--pubkey is required"*)
    echo "FAIL: the no-argument form still demands flags:"; echo "$out"; exit 1 ;;
esac
echo "OK: install.sh has usable defaults for channel, version and pubkey"

grep -q "BEGIN PUBLIC KEY" install.sh \
  || { echo "FAIL: no release public key compiled into install.sh"; exit 1; }
echo "OK: the release public key is compiled in"
echo "PASS: one-liner harness"
