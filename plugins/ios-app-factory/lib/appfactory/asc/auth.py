"""App Store Connect API authentication (ES256 JWT).

Credentials are read only from environment variables and never logged:

* ``ASC_KEY_ID``            – API key ID (kid)
* ``ASC_ISSUER_ID``         – issuer ID (iss)
* ``ASC_PRIVATE_KEY_PATH``  – path to AuthKey_XXXX.p8, or
* ``ASC_PRIVATE_KEY``       – the PEM contents (or ``ASC_PRIVATE_KEY_BASE64``)

Token: header {alg: ES256, kid, typ: JWT}; payload {iss, iat, exp<=iat+20min,
aud: "appstoreconnect-v1"}.
"""
from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Optional

AUDIENCE = "appstoreconnect-v1"
MAX_LIFETIME = 20 * 60


class MissingCredentials(RuntimeError):
    pass


def credentials_present() -> bool:
    return bool(os.environ.get("ASC_KEY_ID") and os.environ.get("ASC_ISSUER_ID") and (
        os.environ.get("ASC_PRIVATE_KEY_PATH") or os.environ.get("ASC_PRIVATE_KEY") or os.environ.get("ASC_PRIVATE_KEY_BASE64")))


def _private_key() -> str:
    if os.environ.get("ASC_PRIVATE_KEY"):
        return os.environ["ASC_PRIVATE_KEY"].replace("\\n", "\n")
    if os.environ.get("ASC_PRIVATE_KEY_BASE64"):
        return base64.b64decode(os.environ["ASC_PRIVATE_KEY_BASE64"]).decode("utf-8")
    path = os.environ.get("ASC_PRIVATE_KEY_PATH")
    if path:
        p = Path(path).expanduser()
        if not p.exists():
            raise MissingCredentials("ASC_PRIVATE_KEY_PATH points to a missing file")
        return p.read_text(encoding="utf-8")
    raise MissingCredentials("set ASC_PRIVATE_KEY_PATH (or ASC_PRIVATE_KEY / ASC_PRIVATE_KEY_BASE64)")


class TokenProvider:
    def __init__(self, lifetime: int = 15 * 60):
        if not credentials_present():
            raise MissingCredentials("App Store Connect credentials missing: ASC_KEY_ID, ASC_ISSUER_ID, ASC_PRIVATE_KEY_PATH")
        self.lifetime = min(lifetime, MAX_LIFETIME)
        self._token: Optional[str] = None
        self._exp = 0

    def token(self) -> str:
        now = int(time.time())
        if self._token and now < self._exp - 60:
            return self._token
        import jwt  # PyJWT[crypto]

        payload = {"iss": os.environ["ASC_ISSUER_ID"], "iat": now, "exp": now + self.lifetime, "aud": AUDIENCE}
        headers = {"alg": "ES256", "kid": os.environ["ASC_KEY_ID"], "typ": "JWT"}
        self._token = jwt.encode(payload, _private_key(), algorithm="ES256", headers=headers)
        self._exp = now + self.lifetime
        return self._token
