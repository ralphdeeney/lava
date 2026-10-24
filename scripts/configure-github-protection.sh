#!/usr/bin/env bash
# Uses gh's existing authorized session; never accepts or prints credentials.
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -m engineering.configure_github "$@"
