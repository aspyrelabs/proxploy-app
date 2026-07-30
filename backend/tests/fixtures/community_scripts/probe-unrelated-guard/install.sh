#!/usr/bin/env bash

source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
color
catch_errors
update_os

# An env-var default that has nothing whatsoever to do with the prompt below.
FOO="${FOO:-bar}"
msg_info "Installing Thing ($FOO)"
read -r -p "${TAB3}Enter the admin email: " admin_email
echo "$admin_email" >/etc/thing/admin

motd_ssh
customize
