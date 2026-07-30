#!/usr/bin/env bash

source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
color
verb_ip6
catch_errors
setting_up_container
network_check
update_os

msg_info "Installing Jellyfin"
$STD apt install -y jellyfin
msg_ok "Installed Jellyfin"

if [[ "$nvidia_selected" == "yes" ]]; then
  if [[ -n "${INSTALL_NVIDIA_DRIVERS:-}" ]]; then
    install_nvidia_drivers="${INSTALL_NVIDIA_DRIVERS}"
  else
    read -r -t 60 -p "${TAB3}Install NVIDIA driver libraries in the container? [Y/n] (auto-yes in 60s): " nvidia_reply || nvidia_reply=""
    case "${nvidia_reply,,}" in
    n | no) install_nvidia_drivers="no" ;;
    *) install_nvidia_drivers="yes" ;;
    esac
  fi
fi

motd_ssh
customize
cleanup_lxc
