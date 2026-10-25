"""Klien HTTP sederhana dengan jeda antar-request, retry, dan backoff eksponensial.
Dipakai provider Threads dan TikTok. Provider X punya penanganan sendiri karena
header rate limit-nya khusus."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import requests

from crawler.providers.base import ProviderError

log = logging.getLogger(__name__)


class RetryableError(Exception):
    """Dilempar oleh `classify` untuk respons yang layak dicoba ulang (mis. rate limit)."""

    def __init__(self, message: str, wait: float | None = None):
        super().__init__(message)
        self.wait = wait


class HttpClient:
    def __init__(
        self,
        options: dict[str, Any],
        classify: Callable[[requests.Response], None],
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ):
        """`classify(resp)` dipanggil untuk respons non-2xx: lempar RetryableError
        agar dicoba ulang, atau ProviderError untuk berhenti."""
        self.session = session or requests.Session()
        self.classify = classify
        self.min_interval = float(options.get("min_request_interval_seconds", 1.0))
        self.timeout = float(options.get("request_timeout_seconds", 60))
        self.max_retries = int(options.get("max_retries", 6))
        self.backoff_base = float(options.get("backoff_base_seconds", 2))
        self.max_backoff = float(options.get("max_backoff_seconds", 900))
        self._sleep, self._clock = sleep, clock
        self._last = 0.0

    def request(self, method: str, url: str, **kwargs) -> Any:
        kwargs.setdefault("timeout", self.timeout)
        for attempt in range(self.max_retries + 1):
            wait = self.min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = self._clock()
            try:
                resp = self.session.request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as e:
                self._wait(attempt, None, f"koneksi gagal ({e.__class__.__name__})")
                continue
            if 200 <= resp.status_code < 300:
                return resp.json()
            try:
                self.classify(resp)
            except RetryableError as e:
                self._wait(attempt, e.wait, str(e))
                continue
            if resp.status_code >= 500 or resp.status_code == 429:
                self._wait(attempt, None, f"HTTP {resp.status_code}")
                continue
            raise ProviderError(f"Permintaan ditolak ({resp.status_code}): {resp.text[:500]}")
        raise ProviderError(f"Gagal setelah {self.max_retries + 1} percobaan: {url.split('?')[0]}")

    def _wait(self, attempt: int, wait: float | None, reason: str) -> None:
        wait = wait if wait is not None else min(self.max_backoff, self.backoff_base * (2 ** attempt))
        log.warning("%s. Coba lagi dalam %.0f detik.", reason, wait)
        self._sleep(wait)

    def close(self) -> None:
        self.session.close()
