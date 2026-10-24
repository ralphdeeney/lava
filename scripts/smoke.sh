#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose up --build --wait --wait-timeout 180
python3 - <<'PY'
import json
from urllib.request import urlopen
for path, expected in [('health', 'ok'), ('ready', 'ready')]:
    with urlopen(f'http://127.0.0.1:8000/{path}', timeout=10) as response:
        assert response.status == 200
        assert json.load(response) == {'status': expected}
with urlopen('http://127.0.0.1:3000', timeout=10) as response:
    assert response.status == 200
    assert b'A foundation for shipping.' in response.read()
print('Compose API, PostgreSQL readiness, and frontend smoke checks passed')
PY
