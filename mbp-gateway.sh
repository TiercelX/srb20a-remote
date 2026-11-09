#!/bin/sh
set -eu
base_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$base_dir/.venv/bin/python" "$base_dir/gateway_client.py" "$@"
