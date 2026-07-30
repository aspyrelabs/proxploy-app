#!/usr/bin/env bash

source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
color
catch_errors
update_os

msg_info "Installing Thing"
$STD apt install -y thing

# No -p flag, but it still blocks on stdin and still aborts under set -Ee.
echo "Continue? [y/N]"
read ANSWER
case "${ANSWER,,}" in
y | yes) : ;;
*) exit 1 ;;
esac

# A loop consuming a stream is NOT a prompt and must not be flagged.
while read -r pkg; do
  $STD apt install -y "$pkg"
done </opt/extra-packages.txt

motd_ssh
customize
