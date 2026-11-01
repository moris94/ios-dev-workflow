"""Logging: human output to stderr, full logs to .factory-tmp/logs (gitignored).
All text is redacted before it is written anywhere."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

from .redact import redact

_log_file: Optional[Path] = None


def set_log_file(path: Optional[Path]) -> None:
    global _log_file
    _log_file = path
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)


def log(message: str, *, level: str = "info", echo: bool = True) -> None:
    line = redact(str(message))
    if echo:
        print(line, file=sys.stderr)
    if _log_file:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        with _log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} [{level}] {line}\n")
