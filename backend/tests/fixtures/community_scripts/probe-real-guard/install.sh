#!/usr/bin/env bash

source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
color
catch_errors
update_os

# This guard names the variable the read assigns into, so an unattended run
# with ADMIN_EMAIL exported never reaches the prompt at all.
if [[ -z "${ADMIN_EMAIL:-}" ]]; then
  read -r -p "${TAB3}Enter the admin email: " ADMIN_EMAIL
fi
echo "$ADMIN_EMAIL" >/etc/thing/admin

motd_ssh
customize
