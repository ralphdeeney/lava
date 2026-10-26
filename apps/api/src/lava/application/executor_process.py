"""Owner-scoped subprocess groups for audited executor commands."""

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from uuid import UUID


@dataclass
class OwnedProcess:
    process: subprocess.Popen
    deadline: float
    outcome: str = "RUNNING"


class ProcessSupervisor:
    def __init__(self):
        self._owned: dict[str, OwnedProcess] = {}
        self._lock = threading.RLock()

    def start(self, execution_id: str, argv: list[str], *, timeout: float) -> subprocess.Popen:
        UUID(execution_id)
        if not 0 < timeout <= 3600 or not argv:
            raise ValueError("Invalid execution bounds")
        with self._lock:
            if execution_id in self._owned:
                raise ValueError("Execution identity already used")
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
            self._owned[execution_id] = OwnedProcess(process, time.monotonic() + timeout)
            return process

    def _terminate(self, owned: OwnedProcess) -> None:
        if owned.process.poll() is not None:
            return
        # The subprocess is the session leader of a group created by this supervisor.
        os.killpg(owned.process.pid, signal.SIGTERM)
        try:
            owned.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            if owned.process.poll() is None:
                os.killpg(owned.process.pid, signal.SIGKILL)
                owned.process.wait(timeout=1)

    def cancel(self, execution_id: str) -> str:
        with self._lock:
            owned = self._owned[execution_id]
            if owned.outcome == "RUNNING":
                self._terminate(owned)
                owned.outcome = "CANCELLED"
            return owned.outcome

    def status(self, execution_id: str) -> str:
        with self._lock:
            owned = self._owned[execution_id]
            if owned.outcome == "RUNNING":
                if time.monotonic() >= owned.deadline:
                    self._terminate(owned)
                    owned.outcome = "FAILED"
                elif (code := owned.process.poll()) is not None:
                    owned.outcome = "COMPLETED" if code == 0 else "FAILED"
            return owned.outcome

    def shutdown(self) -> None:
        with self._lock:
            for execution_id in tuple(self._owned):
                self.cancel(execution_id)
