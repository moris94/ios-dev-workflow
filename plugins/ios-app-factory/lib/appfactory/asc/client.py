"""Minimal App Store Connect REST transport with retry and redacted logging.

Retries: 429 and 5xx are retried with exponential backoff only for
idempotent methods (GET/PATCH/DELETE/PUT). POSTs are never blindly retried;
a POST whose outcome is unknown is recorded as *uncertain* in the ledger and
reconciled with a lookup before any resend.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from ..logutil import log
from ..redact import redact

BASE_URL = "https://api.appstoreconnect.apple.com"
IDEMPOTENT = {"GET", "PATCH", "DELETE", "PUT"}


class ASCError(RuntimeError):
    def __init__(self, status: int, method: str, path: str, body: Any):
        self.status = status
        self.method = method
        self.path = path
        self.body = body
        detail = ""
        if isinstance(body, dict) and body.get("errors"):
            detail = "; ".join(f"{e.get('code')}: {e.get('detail') or e.get('title')}" for e in body["errors"][:5])
        super().__init__(redact(f"{method} {path} -> HTTP {status} {detail}"))


class UncertainOutcome(RuntimeError):
    pass


class Response:
    def __init__(self, status: int, body: Any = None, headers: Optional[Dict[str, str]] = None):
        self.status = status
        self.body = body
        self.headers = headers or {}


class HttpTransport:
    """Real network transport (requests)."""

    def __init__(self, token_provider, base_url: str = BASE_URL, timeout: int = 60):
        import requests

        self._requests = requests
        self.session = requests.Session()
        self.tokens = token_provider
        self.base_url = base_url
        self.timeout = timeout

    def request(self, method: str, path: str, body: Any = None, params: Optional[dict] = None) -> Response:
        url = path if path.startswith("http") else self.base_url + path
        headers = {"Authorization": f"Bearer {self.tokens.token()}", "Content-Type": "application/json"}
        try:
            r = self.session.request(method, url, headers=headers, params=params,
                                     data=json.dumps(body) if body is not None else None, timeout=self.timeout)
        except self._requests.RequestException as exc:
            if method == "POST":
                raise UncertainOutcome(redact(f"POST {path}: network error {type(exc).__name__}")) from None
            raise
        try:
            payload = r.json() if r.content else None
        except ValueError:
            payload = {"raw": r.text[:500]}
        return Response(r.status_code, payload, dict(r.headers))

    def upload(self, url: str, method: str, headers: Dict[str, str], data: bytes) -> Response:
        r = self.session.request(method, url, headers=headers, data=data, timeout=self.timeout)
        return Response(r.status_code, None, dict(r.headers))


class Client:
    def __init__(self, transport, max_retries: int = 4, sleep=time.sleep):
        self.t = transport
        self.max_retries = max_retries
        self.sleep = sleep
        self.requests_sent = 0

    def call(self, method: str, path: str, body: Any = None, params: Optional[dict] = None, ok=(200, 201, 204)) -> Response:
        attempt = 0
        while True:
            self.requests_sent += 1
            resp = self.t.request(method, path, body=body, params=params)
            if resp.status in ok:
                return resp
            retryable = resp.status == 429 or resp.status >= 500
            if retryable and method in IDEMPOTENT and attempt < self.max_retries:
                delay = 2 ** attempt
                log(f"ASC {method} {path} -> {resp.status}; retry in {delay}s", level="warn")
                self.sleep(delay)
                attempt += 1
                continue
            if retryable and method == "POST":
                raise UncertainOutcome(f"POST {path} -> HTTP {resp.status}; outcome unknown, will reconcile before resend")
            raise ASCError(resp.status, method, path, resp.body)

    def get(self, path: str, params: Optional[dict] = None, allow_404: bool = False):
        try:
            return self.call("GET", path, params=params).body
        except ASCError as exc:
            if allow_404 and exc.status == 404:
                return None
            raise

    def get_all(self, path: str, params: Optional[dict] = None) -> list:
        items, included = [], []
        body = self.get(path, params=params)
        while body:
            data = body.get("data") or []
            items.extend(data if isinstance(data, list) else [data])
            included.extend(body.get("included") or [])
            nxt = (body.get("links") or {}).get("next")
            body = self.get(nxt) if nxt else None
        self.last_included = included
        return items

    def upload_part(self, op: dict, data: bytes) -> None:
        headers = {h["name"]: h["value"] for h in op.get("requestHeaders", [])}
        resp = self.t.upload(op["url"], op.get("method", "PUT"), headers, data)
        if resp.status not in (200, 201, 204):
            raise ASCError(resp.status, op.get("method", "PUT"), "<upload>", None)
