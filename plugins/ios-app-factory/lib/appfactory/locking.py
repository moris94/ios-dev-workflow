"""Locks.

* ``state_mutex`` – short critical section around read-modify-write of
  state.json (fcntl.flock).
* Stage run locks – one per stage, created atomically with O_EXCL. They
  prevent the same stage from being executed twice concurrently (e.g. two
  Claude sessions resuming the same pipeline). A lock carries an owner
  (Claude session id) and a heartbeat; locks whose heartbeat is older than
  ``stale_after`` may be taken over by a new owner, which is how an
  interrupted session is resumed.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import socket
from pathlib import Path
from typing import Optional

from .jsonio import write_json_atomic
from .timeutil import age_seconds, now_iso


class LockHeld(RuntimeError):
    def __init__(self, stage: str, info: dict):
        self.stage = stage
        self.info = info
        super().__init__(
            f"Stage '{stage}' is already running (owner={info.get('owner')}, run_id={info.get('run_id')}, "
            f"heartbeat={info.get('heartbeat_at')}). Refusing duplicate execution."
        )


@contextlib.contextmanager
def state_mutex(lock_dir: Path):
    lock_dir.mkdir(parents=True, exist_ok=True)
    path = lock_dir / "state.mutex"
    with path.open("a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _lock_path(lock_dir: Path, stage: str) -> Path:
    return lock_dir / f"{stage}.lock"


def read_lock(lock_dir: Path, stage: str) -> Optional[dict]:
    path = _lock_path(lock_dir, stage)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"owner": "unknown", "heartbeat_at": "1970-01-01T00:00:00Z", "corrupt": True}


def lock_is_stale(info: dict, stale_after_s: float) -> bool:
    try:
        return age_seconds(info.get("heartbeat_at", "1970-01-01T00:00:00Z")) > stale_after_s
    except ValueError:
        return True


def acquire(lock_dir: Path, stage: str, owner: str, run_id: str, stale_after_s: float, takeover: bool = False) -> dict:
    """Acquire the run lock. Re-entrant for the same owner."""
    lock_dir.mkdir(parents=True, exist_ok=True)
    path = _lock_path(lock_dir, stage)
    info = {
        "stage": stage,
        "owner": owner,
        "run_id": run_id,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "acquired_at": now_iso(),
        "heartbeat_at": now_iso(),
    }
    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            current = read_lock(lock_dir, stage) or {}
            if current.get("owner") == owner:
                current["heartbeat_at"] = now_iso()
                write_json_atomic(path, current)
                return current
            if takeover or lock_is_stale(current, stale_after_s):
                path.unlink(missing_ok=True)
                continue
            raise LockHeld(stage, current)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(info, fh, indent=2)
        return info
    raise LockHeld(stage, read_lock(lock_dir, stage) or {})


def heartbeat(lock_dir: Path, stage: str, owner: str) -> bool:
    info = read_lock(lock_dir, stage)
    if not info or info.get("owner") != owner:
        return False
    info["heartbeat_at"] = now_iso()
    write_json_atomic(_lock_path(lock_dir, stage), info)
    return True


def release(lock_dir: Path, stage: str, owner: Optional[str] = None) -> None:
    info = read_lock(lock_dir, stage)
    if info is None:
        return
    if owner is not None and info.get("owner") not in (owner, "unknown"):
        raise LockHeld(stage, info)
    _lock_path(lock_dir, stage).unlink(missing_ok=True)
