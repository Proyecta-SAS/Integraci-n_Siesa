"""Persistent send status with one background worker per source state file.

The OS releases the lease if the server exits. Interrupted jobs are reported,
never resumed automatically: the ERP may have committed the in-flight receipt.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .state import write_json_atomic


ACTIVE = {"queued", "running"}
Progress = Callable[[dict[str, Any]], None]
Runner = Callable[[Progress], dict[str, Any]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Lease:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a+b")
        if os.name == "nt":
            import msvcrt
            if self.file.tell() == 0:
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            try:
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self.file.close()
                raise BlockingIOError("envio en curso") from None
        else:
            import fcntl
            try:
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BaseException:
                self.file.close()
                raise

    def close(self) -> None:
        if os.name == "nt":
            import msvcrt
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        self.file.close()


class SendJobs:
    def __init__(self) -> None:
        self._mutex = threading.Lock()

    @staticmethod
    def _path(state_file: Path) -> Path:
        return state_file.with_name(state_file.name + ".job.json")

    @staticmethod
    def _lease(state_file: Path) -> _Lease:
        return _Lease(state_file.with_name(state_file.name + ".send.lock"))

    def _read(self, state_file: Path) -> dict[str, Any] | None:
        path = self._path(state_file)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def status(self, state_file: Path) -> dict[str, Any] | None:
        with self._mutex:
            job = self._read(state_file)
            if job and job["status"] in ACTIVE:
                try:
                    lease = self._lease(state_file)
                except BlockingIOError:
                    return job
                try:
                    # Re-read after obtaining the lease: the worker may have
                    # completed between the initial read and lock acquisition.
                    job = self._read(state_file)
                    if job and job["status"] in ACTIVE:
                        job.update(status="interrupted", finished_at=_now(), error=(
                            "El servidor se reinicio durante el lote. Revise los pagos sin "
                            "confirmar en Siesa antes de reintentar. Los confirmados se conservan."
                        ))
                        write_json_atomic(self._path(state_file), job)
                finally:
                    lease.close()
            return job

    def start(self, state_file: Path, activator: str, runner: Runner) -> dict[str, Any]:
        with self._mutex:
            try:
                lease = self._lease(state_file)
            except BlockingIOError:
                existing = self._read(state_file)
                if existing:
                    return existing
                raise RuntimeError("El envio se esta preparando; consulte su estado.") from None
            job = {
                "id": uuid4().hex, "activator": activator, "status": "queued",
                "started_at": _now(), "updated_at": _now(), "progress": {},
            }
            try:
                write_json_atomic(self._path(state_file), job)
                # Non-daemon workers are allowed to finish on a normal shutdown.
                threading.Thread(target=self._run, args=(state_file, job.copy(), runner, lease),
                                 name=f"siesa-send-{activator}", daemon=False).start()
            except BaseException:
                lease.close()
                raise
            return job

    def _run(self, state_file: Path, job: dict[str, Any], runner: Runner, lease: _Lease) -> None:
        def save() -> None:
            job["updated_at"] = _now()
            write_json_atomic(self._path(state_file), job)

        def progress(value: dict[str, Any]) -> None:
            job["progress"] = value
            save()

        try:
            job["status"] = "running"
            save()
            job["outcome"] = runner(progress)
            job["status"] = "completed"
        except Exception as exc:
            job.update(status="failed", error=str(exc))
        finally:
            try:
                job["finished_at"] = _now()
                save()
            finally:
                lease.close()
