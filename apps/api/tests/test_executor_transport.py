import asyncio
import json
import stat
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

import pytest

from lava.application.executor_protocol import ExecutorRequest, sign
from lava.application.executor_transport import ExecutorSocket

KEY = b"disposable-test-key-only-32-bytes!"


def request():
    from time import time

    return ExecutorRequest(
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        1,
        "a" * 40,
        1,
        "python",
        "status",
        "b" * 64,
        int(time()) + 20,
    )


@pytest.mark.anyio
async def test_socket_authentication_permissions_and_bounds(tmp_path: Path):
    path = tmp_path / "executor.sock"
    seen = []
    async with ExecutorSocket(path, KEY, lambda value: seen.append(value) or {"status": "UNKNOWN"}):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        reader, writer = await asyncio.open_unix_connection(str(path))
        value = request()
        writer.write(
            (json.dumps({"request": asdict(value), "signature": sign(value, KEY)}) + "\n").encode()
        )
        await writer.drain()
        assert json.loads(await reader.readline()) == {"status": "UNKNOWN"}
        assert len(seen) == 1
        bad = replace(value, fixture="customer")
        writer.write(
            (json.dumps({"request": asdict(bad), "signature": sign(bad, KEY)}) + "\n").encode()
        )
        await writer.drain()
        assert json.loads(await reader.readline()) == {"error": "rejected"}
        writer.close()
        await writer.wait_closed()
        reader, writer = await asyncio.open_unix_connection(str(path))
        writer.write(b"x" * 4097 + b"\n")
        await writer.drain()
        assert json.loads(await reader.readline()) == {"error": "rejected"}
        writer.close()
        await writer.wait_closed()
    assert not path.exists()
