"""App Store Connect API authentication (ES256 JWT).

Credentials are read only from environment variables and never logged:

* ``ASC_KEY_ID``              – API key ID (kid)
* ``ASC_ISSUER_ID``           – issuer ID (iss)
* ``ASC_KEY_CONTENT_BASE64``  – the AuthKey_XXXX.p8 file contents, base64-encoded
                                (``base64 -i AuthKey_XXXX.p8 | tr -d '\\n'``)

Token: header {alg: ES256, kid, typ: JWT}; payload {iss, iat, exp<=iat+20min,
aud: "appstoreconnect-v1"}.
"""
from __future__ import annotations

import base64
import binascii
import os
import time
from typing import Optional

AUDIENCE = "appstoreconnect-v1"
MAX_LIFETIME = 20 * 60
KEY_ENV = "ASC_KEY_CONTENT_BASE64"
REQUIRED_ENV = ("ASC_KEY_ID", "ASC_ISSUER_ID", KEY_ENV)


class MissingCredentials(RuntimeError):
    pass


def credentials_present() -> bool:
    return all(os.environ.get(name) for name in REQUIRED_ENV)


def missing_env() -> list:
    return [name for name in REQUIRED_ENV if not os.environ.get(name)]


def private_key_pem() -> str:
    """Decode ASC_KEY_CONTENT_BASE64 to the PEM text. Error messages never include the value."""
    raw = os.environ.get(KEY_ENV, "")
    if not raw:
        raise MissingCredentials(f"{KEY_ENV} is not set")
    compact = "".join(raw.split())
    try:
        pem = base64.b64decode(compact, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise MissingCredentials(f"{KEY_ENV} is not valid base64 of an AuthKey .p8 file") from None
    if "BEGIN PRIVATE KEY" not in pem:
        raise MissingCredentials(f"{KEY_ENV} does not decode to a PEM private key (base64-encode the whole .p8 file)")
    return pem


class TokenProvider:
    def __init__(self, lifetime: int = 15 * 60):
        if not credentials_present():
            raise MissingCredentials("App Store Connect credentials missing: " + ", ".join(missing_env()))
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
        self._token = jwt.encode(payload, private_key_pem(), algorithm="ES256", headers=headers)
        self._exp = now + self.lifetime
        return self._token
