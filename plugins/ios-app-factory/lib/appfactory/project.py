"""Locations inside an app repository driven by the factory."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .jsonio import read_json

FACTORY_DIR = "factory"
TMP_DIR = ".factory-tmp"

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = Path(__file__).resolve().parent
SCHEMA_DIR = LIB_DIR / "schemas"
TEMPLATE_DIR = PLUGIN_ROOT / "templates"


class ProjectNotFound(RuntimeError):
    pass


class Project:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    # --- discovery -------------------------------------------------------
    @classmethod
    def find(cls, start: Optional[Path] = None, must_exist: bool = True) -> "Project":
        env = os.environ.get("APP_FACTORY_PROJECT")
        if env:
            start = Path(env)
        start = Path(start or os.getcwd()).resolve()
        for candidate in [start, *start.parents]:
            if (candidate / FACTORY_DIR / "config.json").exists():
                return cls(candidate)
        if must_exist:
            raise ProjectNotFound(
                f"No factory/config.json found from {start}. Run `app-factory init` in the app repository first."
            )
        return cls(start)

    # --- paths -----------------------------------------------------------
    @property
    def factory(self) -> Path:
        return self.root / FACTORY_DIR

    @property
    def tmp(self) -> Path:
        return self.root / TMP_DIR

    @property
    def config_path(self) -> Path:
        return self.factory / "config.json"

    @property
    def state_path(self) -> Path:
        return self.factory / "state.json"

    @property
    def history_path(self) -> Path:
        return self.factory / "history.jsonl"

    @property
    def gates_dir(self) -> Path:
        return self.factory / "gates"

    @property
    def artifacts(self) -> Path:
        return self.factory / "artifacts"

    @property
    def reports(self) -> Path:
        return self.factory / "reports"

    @property
    def approvals_dir(self) -> Path:
        return self.factory / "approvals"

    @property
    def asc_dir(self) -> Path:
        return self.factory / "asc"

    @property
    def screenshots_dir(self) -> Path:
        return self.factory / "screenshots"

    @property
    def locks_dir(self) -> Path:
        return self.tmp / "locks"

    @property
    def logs_dir(self) -> Path:
        return self.tmp / "logs"

    def artifact(self, stage: str, name: str) -> Path:
        return self.artifacts / stage / name

    def config(self) -> dict:
        return read_json(self.config_path, {}) or {}

    def rel(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.root).as_posix()
