"""JSON Schema validation for artifacts."""
from __future__ import annotations

from functools import lru_cache
from typing import Any, List

from .jsonio import read_json
from .project import SCHEMA_DIR


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict:
    path = SCHEMA_DIR / f"{name}.schema.json"
    if not path.exists():
        raise FileNotFoundError(f"schema not found: {path}")
    return read_json(path)


def validate(instance: Any, schema_name: str) -> List[str]:
    """Return a list of human readable validation errors (empty = valid)."""
    import jsonschema  # imported lazily so hooks stay dependency free

    schema = load_schema(schema_name)
    validator_cls = jsonschema.validators.validator_for(schema)
    validator = validator_cls(schema, format_checker=jsonschema.FormatChecker())
    errors = []
    for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path)):
        loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"{loc}: {err.message}")
    return errors
