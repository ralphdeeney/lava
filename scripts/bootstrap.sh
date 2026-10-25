#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${LAVA_CACHE_DIR:?Set LAVA_CACHE_DIR to a directory on your data disk}"
mkdir -p "$LAVA_CACHE_DIR"/{npm,uv,pnpm,tools}
export npm_config_cache="$LAVA_CACHE_DIR/npm" UV_CACHE_DIR="$LAVA_CACHE_DIR/uv"
command -v docker >/dev/null
command -v uv >/dev/null
node -e 'if (+process.versions.node.split(".")[0] < 22) process.exit(1)'
if [[ ! -x "$LAVA_CACHE_DIR/tools/node_modules/.bin/pnpm" ]]; then
  npm install --prefix "$LAVA_CACHE_DIR/tools" pnpm@10.32.1
fi
export PATH="$LAVA_CACHE_DIR/tools/node_modules/.bin:$PATH"
[[ "$(pnpm --version)" == "10.32.1" ]]
CI=true pnpm install --frozen-lockfile --store-dir "$LAVA_CACHE_DIR/pnpm"
uv sync --project apps/api --locked
if [[ ! -f .env ]]; then
  python3 - <<'PY'
from pathlib import Path
import secrets
import os
template = Path('.env.example').read_text()
for name in ('POSTGRES_PASSWORD', 'POSTGRES_WORKER_PASSWORD'):
    template = template.replace(name + '=\n', name + '=' + secrets.token_hex(24) + '\n')
with os.fdopen(os.open('.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as envfile:
    envfile.write(template)
PY
fi
if ! grep -q '^POSTGRES_WORKER_PASSWORD=' .env; then
  python3 - <<'PY'
from pathlib import Path
import secrets
with Path('.env').open('a') as envfile:
    envfile.write('POSTGRES_WORKER_PASSWORD=' + secrets.token_hex(24) + '\n')
PY
fi
./scripts/check.sh
