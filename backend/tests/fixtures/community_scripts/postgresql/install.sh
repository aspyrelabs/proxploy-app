#!/usr/bin/env bash

source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
color
verb_ip6
catch_errors
setting_up_container
network_check
update_os

read -r -p "${TAB3}Enter PostgreSQL version (15/16/17/18): " ver
[[ $ver =~ ^(15|16|17|18)$ ]] || {
  echo "Invalid version"
  exit 64
}
PG_VERSION=$ver setup_postgresql
