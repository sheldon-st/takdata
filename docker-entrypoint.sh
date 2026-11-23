#!/bin/sh
# Drop to the unprivileged `takdata` user (uid/gid 1001). Volumes created by
# older images are root-owned, so fix ownership on the way down rather than
# failing to write the SQLite DB.
set -e

if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA_DIR/certs" "$DATA_DIR/packages"
  chown -R 1001:1001 "$DATA_DIR"
  exec python -c 'import os, sys
os.setgroups([]); os.setgid(1001); os.setuid(1001)
os.execvp(sys.argv[1], sys.argv[1:])' "$@"
fi

exec "$@"
