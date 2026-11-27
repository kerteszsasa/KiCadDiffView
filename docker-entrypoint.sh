#!/usr/bin/env sh
set -eu
mkdir -p /data/home /data/tmp /data/config /data/cache
exec "$@"
