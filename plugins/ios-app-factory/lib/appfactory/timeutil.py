from __future__ import annotations

import datetime as _dt


def now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)


def now_iso() -> str:
    return now().isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def age_seconds(value: str) -> float:
    return (now() - parse_iso(value)).total_seconds()
