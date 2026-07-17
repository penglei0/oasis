#!/bin/sh
set -eu

profile="${1:-}"
[ -n "$profile" ] || { echo "usage: install_benchmark_profile.sh PROFILE" >&2; exit 2; }
case "$profile" in
    *[!A-Za-z0-9_-]*) echo "Invalid benchmark profile: $profile" >&2; exit 2 ;;
esac

usr_bin_dir="${OASIS_USR_BIN_DIR:-/usr/bin}"
template="${usr_bin_dir}/regular_benchmark_${profile}.sh"
[ -f "$template" ] || { echo "Unknown regular benchmark profile: $profile" >&2; exit 2; }

temporary="${usr_bin_dir}/.regular_test.sh.$$"
trap 'rm -f "$temporary"' EXIT HUP INT TERM
cp "$template" "$temporary"
chmod 755 "$temporary"
mv "$temporary" "${usr_bin_dir}/regular_test.sh"
trap - EXIT HUP INT TERM
