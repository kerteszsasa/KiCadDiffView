#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
image=kicaddiffview:local

usage() {
    cat <<'EOF'
Usage: ./build_docker_image.sh
       ./build_docker_image.sh --help

Build kicaddiffview:local using the project beside this script.
Does not create a data directory or start a container.
EOF
}

if [[ $# == 1 && $1 == --help ]]; then
    usage
    exit 0
fi
if [[ $# != 0 ]]; then
    usage >&2
    exit 2
fi
command -v docker >/dev/null 2>&1 || { printf 'Error: Docker is not installed or not on PATH.\n' >&2; exit 1; }
docker info >/dev/null 2>&1 || { printf 'Error: Docker is unavailable. Start Docker and check your access.\n' >&2; exit 1; }
exec docker build --tag "$image" "$script_dir"
