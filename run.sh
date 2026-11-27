#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
image=kicaddiffview:local
container=kicaddiffview

usage() {
    cat <<'EOF'
Usage: ./run.sh REPOSITORY_DIRECTORY
       ./run.sh --help

Start kicaddiffview:local on all network interfaces (port 8080 by default).
REPOSITORY_DIRECTORY may contain one Git repository or multiple repositories.
Relative source paths and DATA_DIR values are resolved from the current directory.
Environment: DATA_DIR=/path/to/data PORT=8080
Default data directory: data beside this script.
The source is mounted READ ONLY. Stop with Ctrl+C; data is preserved.
Build the image first with ./build_docker_image.sh.
EOF
}

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

if [[ $# == 1 && $1 == --help ]]; then
    usage
    exit 0
fi
if [[ $# != 1 || -z ${1:-} || ${1:-} == -* ]]; then
    usage >&2
    exit 2
fi

port=${PORT:-8080}
if [[ ! $port =~ ^[0-9]{1,5}$ ]] || ((10#$port < 1 || 10#$port > 65535)); then
    fail 'Invalid PORT; use a number between 1 and 65535.'
fi
port=$((10#$port))
repo_root=$(realpath -e -- "$1" 2>/dev/null) || fail "Source directory not found: $1"
[[ -d $repo_root ]] || fail "Source is not a directory: $1"
data_dir=$(realpath -m -- "${DATA_DIR:-$script_dir/data}")
[[ $repo_root != *,* && $data_dir != *,* ]] || fail 'Mount paths cannot contain commas.'
[[ $repo_root != *:* ]] || fail 'Source paths cannot contain colons (repository root separator).'
source_prefix=${repo_root%/}/
data_prefix=${data_dir%/}/
if [[ $data_prefix == "$source_prefix"* || $source_prefix == "$data_prefix"* ]]; then
    fail 'The source and data directory trees must not overlap. Choose a separate DATA_DIR.'
fi
[[ ! -e $data_dir || -d $data_dir ]] || fail "Data path is not a directory: $data_dir"

command -v docker >/dev/null 2>&1 || fail 'Docker is not installed or not on PATH.'
docker info >/dev/null 2>&1 || fail 'Docker is unavailable. Start Docker and check your access.'
if ! docker image inspect "$image" >/dev/null 2>&1; then
    printf 'Error: Docker image %s is missing. Build it first:\n  "%s/build_docker_image.sh"\n' "$image" "$script_dir" >&2
    exit 1
fi

mkdir -p -- "$data_dir"
printf 'Local: http://localhost:%s\nNetwork: http://<server-ip>:%s\nSource (read only): %s\nData: %s\n' "$port" "$port" "$repo_root" "$data_dir"
exec docker run --rm --init --read-only --pull=never --name "$container" \
    --user "$(id -u):$(id -g)" \
    --publish "$port:8080" \
    --env "KICADDIFFVIEW_REPO_ROOTS=$repo_root" \
    --mount "type=bind,source=$repo_root,target=$repo_root,readonly" \
    --mount "type=bind,source=$data_dir,target=/data" \
    "$image"
