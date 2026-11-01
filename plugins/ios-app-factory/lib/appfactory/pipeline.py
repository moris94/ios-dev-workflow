"""Static pipeline definition (pipeline.json) and graph helpers."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from .jsonio import read_json

PIPELINE_PATH = Path(__file__).with_name("pipeline.json")


class Stage:
    def __init__(self, raw: dict):
        self.raw = raw
        self.id: str = raw["id"]
        self.title: str = raw["title"]
        self.agent: str = raw["agent"]
        self.skills: List[str] = raw.get("skills", [])
        self.depends_on: List[str] = raw.get("depends_on", [])
        self.inputs: List[str] = raw.get("inputs", [])
        self.outputs_include: List[str] = raw["outputs"]["include"]
        self.outputs_exclude: List[str] = raw["outputs"].get("exclude", [])
        self.gate: str = raw["gate"]
        self.human_approval = raw.get("human_approval")

    def to_dict(self) -> dict:
        return dict(self.raw)


class Pipeline:
    def __init__(self, raw: dict):
        self.stages: List[Stage] = [Stage(s) for s in raw["stages"]]
        self.by_id: Dict[str, Stage] = {s.id: s for s in self.stages}
        self._validate()

    def _validate(self) -> None:
        seen = set()
        for stage in self.stages:
            for dep in stage.depends_on:
                if dep not in seen:
                    raise ValueError(f"pipeline.json: stage {stage.id} depends on {dep}, which is not defined before it")
            seen.add(stage.id)

    def get(self, stage_id: str) -> Stage:
        if stage_id not in self.by_id:
            raise KeyError(f"Unknown stage '{stage_id}'. Known: {', '.join(self.by_id)}")
        return self.by_id[stage_id]

    def ids(self) -> List[str]:
        return [s.id for s in self.stages]

    def downstream(self, stage_id: str) -> List[str]:
        """All stages that transitively depend on stage_id, in pipeline order."""
        affected = {stage_id}
        result = []
        for stage in self.stages:
            if stage.id != stage_id and affected.intersection(stage.depends_on):
                affected.add(stage.id)
                result.append(stage.id)
        return result


@lru_cache(maxsize=1)
def load() -> Pipeline:
    return Pipeline(read_json(PIPELINE_PATH))
