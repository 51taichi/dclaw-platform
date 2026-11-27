#!/bin/sh
set -eu

if [ "$#" -ne 3 ]; then
    echo "usage: $0 ACTIVE_SYMLINK RELEASE_FRAGMENT HEALTH_URL" >&2
    exit 2
fi

active=$1
release=$2
health_url=$3
old=$(readlink -f "$active")
next="${active}.next"
committed=0

case "$active:$release:$old" in
    /*:/*:/*) ;;
    *) exit 2 ;;
esac
test -f "$release"
test -f "$old"

restore_old() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ "$committed" -eq 0 ]; then
        set +e
        sudo ln -sfn "$old" "$next"
        sudo mv -Tf "$next" "$active"
        sudo nginx -t
        sudo nginx -s reload
        set -e
    fi
    exit "$status"
}
trap restore_old EXIT HUP INT TERM

# Pre-validate the release fragment through the site owner's staged config
# before changing the active symlink.
sudo nginx -t
sudo ln -sfn "$release" "$next"
sudo mv -Tf "$next" "$active"
sudo nginx -t
sudo nginx -s reload
curl --fail --silent --show-error "$health_url"
committed=1
trap - EXIT HUP INT TERM
