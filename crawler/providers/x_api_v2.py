"""Provider X API v2 resmi (search/all untuk arsip penuh, search/recent untuk 7 hari terakhir).

Dokumentasi: https://docs.x.com/x-api/posts/search/introduction
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

import requests

from crawler.config import get_secret
from crawler.providers.base import Page, ProviderError, QuerySpec, SearchProvider

log = logging.getLogger(__name__)

API_BASE = "https://api.x.com/2"

# Hanya field unggahan yang dibutuhkan penelitian. Tidak ada expansions ke objek
# pengguna, sehingga nama tampilan, bio, foto, dan lokasi tidak pernah diambil.
TWEET_FIELDS = "id,text,created_at,lang,author_id,public_metrics,entities,referenced_tweets,note_tweet"


def _rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _term(keyword: str) -> str:
    kw = keyword.strip()
    if kw.startswith("#") or kw.startswith('"'):
        return kw
    return f'"{kw}"' if " " in kw else kw


def build_query(q: QuerySpec) -> str:
    terms = [_term(k) for k in q.keywords]
    core = terms[0] if len(terms) == 1 else "(" + " OR ".join(terms) + ")"
    parts = [core]
    if q.lang:
        parts.append(f"lang:{q.lang}")
    if q.exclude_reposts:
        parts.append("-is:retweet")
    if not q.include_replies:
        parts.append("-is:reply")
    if not q.include_quotes:
        parts.append("-is:quote")
    return " ".join(parts)


def normalize(tweet: dict[str, Any]) -> dict[str, Any]:
    refs = {r.get("type") for r in tweet.get("referenced_tweets") or []}
    if "retweeted" in refs:
        post_type = "repost"
    elif "replied_to" in refs:
        post_type = "reply"
    elif "quoted" in refs:
        post_type = "quote"
    else:
        post_type = "original"
    # Unggahan panjang (>280 karakter) terpotong di `text`; teks utuh ada di note_tweet.
    text = (tweet.get("note_tweet") or {}).get("text") or tweet.get("text", "")
    entities = (tweet.get("note_tweet") or {}).get("entities") or tweet.get("entities") or {}
    metrics = tweet.get("public_metrics") or {}
    return {
        "id": str(tweet["id"]),
        "created_at": tweet.get("created_at"),
        "text": text,
        "lang": tweet.get("lang"),
        "author_id": str(tweet.get("author_id", "")),
        "post_type": post_type,
        "like_count": metrics.get("like_count"),
        "reply_count": metrics.get("reply_count"),
        "repost_count": metrics.get("retweet_count"),
        "quote_count": metrics.get("quote_count"),
        "hashtags": [h.get("tag") for h in entities.get("hashtags", []) if h.get("tag")],
    }


class XApiV2Provider(SearchProvider):
    name = "x_api_v2"
    platform = "x"
    min_page_size = 10

    def __init__(
        self,
        options: dict[str, Any] | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ):
        super().__init__(options)
        o = self.options
        self.endpoint = o.get("endpoint", "all")
        if self.endpoint not in ("all", "recent"):
            raise ValueError("provider.options.endpoint harus 'all' atau 'recent'")
        self.max_page_size = 500 if self.endpoint == "all" else 100
        self.sort_order = o.get("sort_order", "relevancy")
        self.min_interval = float(o.get("min_request_interval_seconds", 1.1))
        self.timeout = float(o.get("request_timeout_seconds", 30))
        self.max_retries = int(o.get("max_retries", 6))
        self.backoff_base = float(o.get("backoff_base_seconds", 2))
        self.max_backoff = float(o.get("max_backoff_seconds", 900))
        self._sleep = sleep
        self._clock = clock
        self._last_request = 0.0
        token = get_secret(o.get("bearer_token_env", "X_BEARER_TOKEN"))
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "User-Agent": "kaburajadulu-research-crawler/0.1"})

    def describe_query(self, query: QuerySpec) -> str:
        return build_query(query)

    def search_page(self, query, start, end, max_results, cursor=None) -> Page:
        params = {
            "query": build_query(query),
            "start_time": _rfc3339(start),
            "end_time": _rfc3339(end),
            "max_results": max(self.min_page_size, min(self.max_page_size, max_results)),
            "tweet.fields": TWEET_FIELDS,
            "sort_order": self.sort_order,
        }
        if cursor:
            params["next_token"] = cursor
        body = self._get(f"/tweets/search/{self.endpoint}", params)
        meta = body.get("meta", {})
        posts = [normalize(t) for t in body.get("data", [])]
        return Page(posts=posts, next_cursor=meta.get("next_token"), meta={"result_count": meta.get("result_count")})

    def count(self, query, start, end) -> int | None:
        params = {
            "query": build_query(query),
            "start_time": _rfc3339(start),
            "end_time": _rfc3339(end),
            "granularity": "day",
        }
        total = 0
        while True:
            body = self._get(f"/tweets/counts/{self.endpoint}", params)
            total += int(body.get("meta", {}).get("total_tweet_count", 0))
            nxt = body.get("meta", {}).get("next_token")
            if not nxt:
                return total
            params["next_token"] = nxt

    # ------------------------------------------------------------------ HTTP

    def _throttle(self) -> None:
        wait = self.min_interval - (self._clock() - self._last_request)
        if wait > 0:
            self._sleep(wait)
        self._last_request = self._clock()

    def _backoff(self, attempt: int) -> float:
        return min(self.max_backoff, self.backoff_base * (2 ** attempt))

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = API_BASE + path
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as e:
                wait = self._backoff(attempt)
                log.warning("Koneksi gagal (%s). Coba lagi dalam %.0f detik.", e.__class__.__name__, wait)
                self._sleep(wait)
                continue

            if resp.status_code == 200:
                self._respect_remaining(resp)
                return resp.json()

            text = resp.text[:500]
            if resp.status_code == 429:
                if "UsageCapExceeded" in text or "usage cap" in text.lower():
                    raise ProviderError(f"Kuota bulanan/kredit X API habis: {text}")
                wait = self._reset_wait(resp) or self._backoff(attempt)
                log.warning("Rate limit (429). Menunggu %.0f detik.", wait)
                self._sleep(wait)
                continue
            if resp.status_code >= 500:
                wait = self._backoff(attempt)
                log.warning("Server X error %s. Coba lagi dalam %.0f detik.", resp.status_code, wait)
                self._sleep(wait)
                continue
            if resp.status_code in (401, 403):
                raise ProviderError(
                    f"Akses ditolak ({resp.status_code}). Periksa X_BEARER_TOKEN dan apakah akun "
                    f"developer Anda punya akses ke /tweets/search/{self.endpoint}. Respons: {text}"
                )
            if resp.status_code == 402:
                raise ProviderError(f"Kredit X API tidak cukup (402): {text}")
            raise ProviderError(f"Permintaan ditolak ({resp.status_code}): {text}")
        raise ProviderError(f"Gagal setelah {self.max_retries + 1} percobaan: {url}")

    def _reset_wait(self, resp: requests.Response) -> float | None:
        retry_after = resp.headers.get("retry-after")
        if retry_after and retry_after.isdigit():
            return float(retry_after) + 1
        reset = resp.headers.get("x-rate-limit-reset")
        if reset and reset.isdigit():
            return max(1.0, float(reset) - self._clock() + 1)
        return None

    def _respect_remaining(self, resp: requests.Response) -> None:
        # Jika jatah jendela 15 menit sudah habis, tunggu sampai reset sebelum request berikutnya.
        remaining = resp.headers.get("x-rate-limit-remaining")
        if remaining is not None and remaining.isdigit() and int(remaining) == 0:
            wait = self._reset_wait(resp)
            if wait:
                log.info("Jatah rate limit habis. Menunggu %.0f detik sampai reset.", wait)
                self._sleep(wait)

    def close(self) -> None:
        self.session.close()
