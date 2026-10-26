"""Durable owner-scoped process supervision without PID-based recovery signals."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from uuid import UUID


class ProcessSupervisor:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(tempfile.mkdtemp(prefix="lava-executor-process-"))
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if (
            self.root.is_symlink()
            or self.root.stat().st_uid != os.getuid()
            or self.root.stat().st_mode & 0o077
        ):
            raise PermissionError("Process spool must be owner-private")
        self._children: dict[str, subprocess.Popen] = {}
        self._lock = threading.RLock()

    def _directory(self, execution_id: str) -> Path:
        if str(UUID(execution_id)) != execution_id:
            raise ValueError("Invalid execution identity")
        return self.root / execution_id

    def start(self, execution_id: str, argv: list[str], *, timeout: float) -> subprocess.Popen:
        if not 0 < timeout <= 3600 or not argv:
            raise ValueError("Invalid execution bounds")
        executable = shutil.which(argv[0])
        if executable is None:
            raise ValueError("Approved executable is unavailable")
        argv = [executable, *argv[1:]]
        with self._lock:
            directory = self._directory(execution_id)
            try:
                directory.mkdir(mode=0o700)
            except FileExistsError:
                raise ValueError("Execution identity already used") from None
            with (directory / "spec.json").open("x") as stream:
                json.dump({"argv": argv, "timeout": timeout}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            process = subprocess.Popen(
                [sys.executable, "-m", "lava.application.executor_child", str(directory)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
                env={"PATH": os.defpath, "LANG": "C.UTF-8"},
            )
            self._children[execution_id] = process
            return process

    def status(self, execution_id: str) -> str:
        directory = self._directory(execution_id)
        if not directory.is_dir() or directory.is_symlink():
            return "UNKNOWN"
        receipt = directory / "result.json"
        if receipt.exists():
            result = json.loads(receipt.read_text())
            status = result.get("status")
            if status not in {"COMPLETED", "CANCELLED", "FAILED", "UNKNOWN"}:
                return "UNKNOWN"
            child = self._children.get(execution_id)
            if child is not None:
                child.wait(timeout=2)
            return status
        child = self._children.get(execution_id)
        return "RUNNING" if child is not None and child.poll() is None else "UNKNOWN"

    def cancel(self, execution_id: str) -> str:
        with self._lock:
            directory = self._directory(execution_id)
            status = self.status(execution_id)
            if status in {"COMPLETED", "CANCELLED", "FAILED"}:
                return status
            if not directory.is_dir() or directory.is_symlink():
                return "UNKNOWN"
            (directory / "cancel").touch(mode=0o600, exist_ok=True)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                status = self.status(execution_id)
                if status in {"COMPLETED", "CANCELLED", "FAILED"}:
                    return status
                time.sleep(0.05)
            return "UNKNOWN"

    def shutdown(self) -> None:
        for execution_id in tuple(self._children):
            self.cancel(execution_id)
