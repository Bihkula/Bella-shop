"""Small helper for calling sibling services with timeouts and retries."""

from __future__ import annotations

import logging
import time

import httpx

from .config import get_settings
from .logging_setup import request_id_var

log = logging.getLogger(__name__)


class UpstreamError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"{status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class ServiceClient:
    def __init__(self, base_url: str, timeout: float = 5.0, retries: int = 2) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries

    def _headers(self) -> dict[str, str]:
        return {
            "X-Internal-Token": get_settings().internal_token,
            "X-Request-ID": request_id_var.get(),
        }

    def request(self, method: str, path: str, json: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                resp = httpx.request(
                    method, url, json=json, headers=self._headers(), timeout=self.timeout
                )
            except httpx.TransportError as exc:
                last_exc = exc
                log.warning("call %s %s failed (attempt %d): %s", method, url, attempt + 1, exc)
                time.sleep(0.2 * (2**attempt))
                continue
            if resp.status_code >= 400:
                try:
                    detail = resp.json().get("detail", resp.text)
                except ValueError:
                    detail = resp.text
                raise UpstreamError(resp.status_code, str(detail))
            return resp.json() if resp.content else {}
        raise UpstreamError(503, f"upstream unavailable: {last_exc}")
