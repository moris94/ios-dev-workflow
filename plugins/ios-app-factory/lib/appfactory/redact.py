"""Secret redaction. Every log line and every error printed by the engine
passes through :func:`redact` so credentials never reach logs or the
conversation transcript."""
from __future__ import annotations

import os
import re
from typing import Iterable

SECRET_ENV_NAMES = (
    "ASC_PRIVATE_KEY",
    "ASC_PRIVATE_KEY_BASE64",
    "ASC_KEY_ID",
    "ASC_ISSUER_ID",
    "FASTLANE_PASSWORD",
    "FASTLANE_SESSION",
    "MATCH_PASSWORD",
    "APP_STORE_CONNECT_API_KEY_CONTENT",
    "SPACESHIP_2FA_SMS_DEFAULT_PHONE_NUMBER",
)
_SECRET_NAME_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSPHRASE|CREDENTIAL)", re.I)
_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),  # JWT
    re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s\"']+"),
]


def _secret_values(extra: Iterable[str] = ()) -> list:
    values = []
    for name, value in os.environ.items():
        if not value or len(value) < 6:
            continue
        if name in SECRET_ENV_NAMES or (_SECRET_NAME_RE.search(name) and not name.endswith("_PATH")):
            values.append(value)
    values.extend(v for v in extra if v and len(v) >= 6)
    return sorted(set(values), key=len, reverse=True)


def redact(text: str, extra: Iterable[str] = ()) -> str:
    if not text:
        return text
    out = str(text)
    for pattern in _PATTERNS:
        if pattern.groups:
            out = pattern.sub(lambda m: m.group(1) + "[REDACTED]", out)
        else:
            out = pattern.sub("[REDACTED]", out)
    for value in _secret_values(extra):
        out = out.replace(value, "[REDACTED]")
    return out
