#!/usr/bin/env bash

source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
color
catch_errors
update_os

msg_info "Configuring Thing"
echo -n "Admin password: "
read -s PASS
echo "$PASS" >/etc/thing/secret

motd_ssh
customize
