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

# install_in_container <version>: copies the repo and runs the real
# in-container installer (--shape systemd) against $CH/<version>. Uses the
# global $name set by the caller, matching the harnesses' own convention.
install_in_container() {
  local version="$1"
  # shellcheck disable=SC2154 # $name is the container name, set by the
  # sourcing harness (test_install.sh / test_upgrade_rollback.sh) before
  # calling this: a deliberate shared-global convention, not an unbound var.
  docker exec "$name" bash -c \
    "cp -r /src/install.sh /src/packaging /tmp/ && cd /tmp && \
     ./install.sh --shape systemd --channel file:///channel/$version --version $version \
                  --pubkey /channel/release.pem"
}
