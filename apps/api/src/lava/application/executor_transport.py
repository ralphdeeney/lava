"""Restricted local transport for authenticated executor requests.

The handler must check durable nonce and lease ownership before any side effect.
"""

import asyncio
import json
import os
import socket
import struct
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path

from lava.application.executor_protocol import ExecutorRequest, authenticate

MAX_MESSAGE = 4096


class ExecutorSocket:
    def __init__(self, path: Path, key: bytes, handler: Callable[[ExecutorRequest], dict]):
        self.path = path
        self.key = key
        self.handler = handler
        self.server: asyncio.AbstractServer | None = None

    async def __aenter__(self):
        if self.path.exists() or self.path.is_symlink():
            raise FileExistsError("Executor socket path already exists")
        self.server = await asyncio.start_unix_server(
            self._serve, path=str(self.path), limit=MAX_MESSAGE
        )
        os.chmod(self.path, 0o600)
        return self

    async def __aexit__(self, *_):
        assert self.server is not None
        self.server.close()
        await self.server.wait_closed()
        self.path.unlink(missing_ok=True)

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            peer = writer.get_extra_info("socket")
            if peer is None or not hasattr(socket, "SO_PEERCRED"):
                return
            _, uid, _ = struct.unpack(
                "3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
            if uid != os.getuid():
                return
            while True:
                try:
                    data = await asyncio.wait_for(reader.readline(), timeout=5)
                    if not data:
                        break
                    if len(data) > MAX_MESSAGE or not data.endswith(b"\n"):
                        raise ValueError("Invalid frame")
                    frame = json.loads(data)
                    raw = frame["request"]
                    if set(raw) != {field.name for field in fields(ExecutorRequest)}:
                        raise ValueError("Invalid fields")
                    request = ExecutorRequest(**raw)
                    authenticate(request, frame["signature"], self.key)
                    result = self.handler(request)
                    response = json.dumps(result, separators=(",", ":"))
                except (
                    TimeoutError,
                    ValueError,
                    TypeError,
                    KeyError,
                    PermissionError,
                    asyncio.LimitOverrunError,
                ):
                    response = '{"error":"rejected"}'
                writer.write(response.encode() + b"\n")
                await writer.drain()
                if response == '{"error":"rejected"}':
                    break
        finally:
            writer.close()
            await writer.wait_closed()
