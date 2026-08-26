#!/usr/bin/env bash
# Shared real-Debian-container recipe for the install/upgrade harnesses
# (Tasks 12, 13). A Proxmox LXC is a Debian userspace with systemd; this
# gives the in-container half of the installer exactly that, for real; 
# same script, same systemd, same Caddy, same TLS. Sourced, never executed.
set -euo pipefail

PP_TEST_IMAGE=proxploy-test-systemd-debian12

# ensure_systemd_image: the stock `debian:12` image has no /sbin/init: it
# is a minimal userland, not a bootable systemd system. Build a thin local
# image (packaging/tests/Dockerfile.systemd-debian12) that adds just
# systemd, once, and reuse it on every harness run.
ensure_systemd_image() {
  docker image inspect "$PP_TEST_IMAGE" >/dev/null 2>&1 && return 0
  docker build -q -t "$PP_TEST_IMAGE" \
    -f packaging/tests/Dockerfile.systemd-debian12 packaging/tests >/dev/null
}

# container_start <name>: boots a fresh systemd-enabled Debian 12 container
# with systemd as PID 1 under $name, waits for it to reach a usable state,
# and installs the curl/ca-certificates the installer itself needs to fetch
# a release. Expects $CH (the channel directory built by
# channel_fixture.sh) to already be set: it is bind-mounted read-only at
# /channel.
container_start() {
  local cname="$1"
  ensure_systemd_image
  docker run -d --name "$cname" --privileged \
    --tmpfs /run --tmpfs /run/lock -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
    --cgroupns=host \
    -v "$PWD:/src:ro" -v "$CH:/channel:ro" \
    "$PP_TEST_IMAGE" >/dev/null

  # systemd needs a moment to reach a usable state before we install into it.
  local _i
  for _i in $(seq 30); do
    docker exec "$cname" systemctl is-system-running --wait >/dev/null 2>&1 && break
    sleep 1
  done

  docker exec "$cname" bash -c \
    "apt-get update -qq && apt-get install -y -qq curl ca-certificates >/dev/null"
}

# install_in_container <version>: runs the real installer (--shape systemd)
# against $CH/<version>. Uses the global $name set by the caller, matching the
# harnesses' own convention.
#
# The BUNDLED installer, copied in alone with no packaging/ beside it, because
# that is the artifact users actually run: one file off a URL. This used to
# copy /src/install.sh AND /src/packaging in together, which quietly proved
# the one shape nobody installs from. Everything the installer needs after
# that comes out of the release tarball it fetches and verifies.
install_in_container() {
  local version="$1" bundle
  bundle=$(mktemp)
  bash packaging/bundle_install.sh "$bundle" >/dev/null
  # shellcheck disable=SC2154 # $name is the container name, set by the
  # sourcing harness (test_install.sh / test_upgrade_rollback.sh) before
  # calling this: a deliberate shared-global convention, not an unbound var.
  docker cp "$bundle" "$name:/tmp/install.sh"
  rm -f "$bundle"
  docker exec "$name" bash -c \
    "chmod 0755 /tmp/install.sh && cd /tmp && \
     ./install.sh --shape systemd --channel file:///channel/$version --version $version \
                  --pubkey /channel/release.pem"
}
