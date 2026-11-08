"""Deterministic digests over files and JSON values."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, List


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def md5_file(path: Path) -> str:
    h = hashlib.md5()  # App Store Connect sourceFileChecksum uses MD5
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def _excluded(rel: str, excludes: Iterable[str]) -> bool:
    p = Path(rel)
    return any(p.match(pattern) or rel == pattern for pattern in excludes)


IGNORED_PARTS = {".git", ".factory-tmp", "DerivedData", "__pycache__", ".build", "xcuserdata"}


def expand_globs(root: Path, includes: Iterable[str], excludes: Iterable[str] = ()) -> List[Path]:
    root = Path(root)
    found = set()
    excludes = list(excludes)
    for pattern in includes:
        for p in root.glob(pattern):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if IGNORED_PARTS.intersection(Path(rel).parts):
                continue
            if p.name == ".DS_Store" or _excluded(rel, excludes):
                continue
            found.add(p)
    return sorted(found, key=lambda x: x.relative_to(root).as_posix())


def digest_files(root: Path, includes: Iterable[str], excludes: Iterable[str] = ()) -> dict:
    """Return {"digest": ..., "files": {relpath: sha256}} for the matched files."""
    root = Path(root)
    files = {p.relative_to(root).as_posix(): sha256_file(p) for p in expand_globs(root, includes, excludes)}
    return {"digest": sha256_json(files), "files": files}


SOURCE_GLOBS = ["project.yml", "App/**/*", "AppTests/**/*", "AppUITests/**/*"]


def source_digest(root: Path) -> str:
    """Digest of everything that affects the compiled app & tests."""
    return digest_files(root, SOURCE_GLOBS)["digest"]


APP_GLOBS = ["project.yml", "App/**/*"]
TEST_GLOBS = ["AppTests/**/*", "AppUITests/**/*"]


def app_digest(root: Path) -> str:
    """Digest of the app itself (no test code): unchanged app => an app fix did not happen."""
    return digest_files(root, APP_GLOBS)["digest"]


def test_file_digests(root: Path) -> dict:
    return digest_files(root, TEST_GLOBS)["files"]
