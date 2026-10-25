"""Provider Threads API resmi (Meta), endpoint keyword_search.

Dokumentasi: https://developers.facebook.com/documentation/threads/keyword-search

Catatan akses:
- Butuh izin `threads_basic` dan `threads_keyword_search`. Tanpa persetujuan App Review
  untuk `threads_keyword_search`, hasil pencarian hanya berisi unggahan milik akun sendiri.
- Batas 2.200 kueri per 24 jam (bergulir) per pengguna; kueri tanpa hasil tidak dihitung.
- Tidak ada filter bahasa di API, jadi bahasa dideteksi saat `process`.
- Satu kueri hanya satu kata kunci (tidak ada OR), sehingga pipeline membuat kueri per kata kunci.
- Respons tidak memiliki pagination; satu kueri mengembalikan maksimal 100 unggahan.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import requests

from crawler.config import get_secret
from crawler.providers.base import Page, ProviderError, QuerySpec, SearchProvider
from crawler.providers.http import HttpClient, RetryableError

API_BASE = "https://graph.threads.com/v1.0"
# Field minimal. `username` hanya untuk di-hash; tidak ikut ke dataset final.
FIELDS = "id,text,timestamp,username,is_reply,is_quote_post,media_type"
HASHTAG_RE = re.compile(r"(?<!\w)#(\w+)")
# Kode error Graph API untuk pembatasan laju.
RATE_LIMIT_CODES = {4, 17, 32, 613, 80001}


def _classify(resp: requests.Response) -> None:
    try:
        err = resp.json().get("error", {})
    except ValueError:
        err = {}
    code = err.get("code")
    msg = err.get("message", resp.text[:300])
    if resp.status_code == 429 or code in RATE_LIMIT_CODES:
        raise RetryableError(f"Rate limit Threads (kode {code})", wait=None)
    if code == 190 or resp.status_code == 401:
        raise ProviderError(f"Access token Threads tidak valid atau kedaluwarsa: {msg}")
    if code in (10, 200) or resp.status_code == 403:
        raise ProviderError(
            f"Izin ditolak: {msg}. Pastikan aplikasi punya izin threads_keyword_search "
            "(perlu App Review untuk mencari unggahan publik)."
        )


def normalize(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("is_reply"):
        post_type = "reply"
    elif item.get("is_quote_post"):
        post_type = "quote"
    else:
        post_type = "original"
    ts = item.get("timestamp")
    created = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc) if ts else None
    text = item.get("text") or ""
    return {
        "id": str(item["id"]),
        "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ") if created else None,
        "text": text,
        "lang": None,  # tidak disediakan API; dideteksi saat process
        "author_id": item.get("username") or "",
        "post_type": post_type,
        # Jumlah suka/balasan unggahan orang lain tidak tersedia lewat API publik.
        "like_count": None,
        "reply_count": None,
        "repost_count": None,
        "quote_count": None,
        "hashtags": HASHTAG_RE.findall(text),
    }


class ThreadsApiProvider(SearchProvider):
    name = "threads_api"
    platform = "threads"
    supports_or = False
    min_page_size = 1
    max_page_size = 100

    def __init__(self, options=None, session=None, sleep=None, clock=None):
        super().__init__(options)
        o = self.options
        self.search_type = o.get("search_type", "TOP")  # TOP atau RECENT
        self.api_base = o.get("api_base", API_BASE)
        self.token = get_secret(o.get("access_token_env", "THREADS_ACCESS_TOKEN"))
        kw = {k: v for k, v in {"session": session, "sleep": sleep, "clock": clock}.items() if v is not None}
        self.http = HttpClient({"min_request_interval_seconds": 1.0, **o}, _classify, **kw)

    def _params(self, query: QuerySpec, start: datetime, end: datetime) -> dict[str, Any]:
        if len(query.keywords) != 1:
            raise ValueError("Threads hanya menerima satu kata kunci per kueri")
        kw = query.keywords[0].strip().strip('"')
        is_tag = kw.startswith("#")
        return {
            "q": kw.lstrip("#"),
            "search_mode": "TAG" if is_tag else "KEYWORD",
            "search_type": self.search_type,
            "since": int(start.timestamp()),
            "until": int(min(end, datetime.now(timezone.utc)).timestamp()) - 1,
            "fields": FIELDS,
            "access_token": self.token,
        }

    def describe_query(self, query: QuerySpec) -> str:
        kw = query.keywords[0]
        return f"{'TAG' if kw.startswith('#') else 'KEYWORD'} {kw.lstrip('#')}"

    def search_page(self, query, start, end, max_results, cursor=None) -> Page:
        params = self._params(query, start, end)
        params["limit"] = max(1, min(self.max_page_size, max_results))
        if cursor:
            params["after"] = cursor
        body = self.http.request("GET", f"{self.api_base}/keyword_search", params=params)
        items = body.get("data", [])
        posts = [normalize(i) for i in items if i.get("id")]
        # Dokumentasi tidak menyebut pagination. Jika suatu saat ada paging.cursors.after, dipakai.
        paging = body.get("paging") or {}
        nxt = (paging.get("cursors") or {}).get("after") if paging.get("next") or paging.get("cursors") else None
        if nxt == cursor:
            nxt = None
        return Page(posts=posts, next_cursor=nxt if items else None)

    def close(self) -> None:
        self.http.close()
