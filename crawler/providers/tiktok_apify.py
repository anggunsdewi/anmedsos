"""Provider TikTok lewat actor Apify (pihak ketiga, berbayar per hasil, ada kredit gratis bulanan).

TikTok Research API resmi hanya untuk peneliti di AS, Eropa, Kanada, dan Brasil, sehingga
belum bisa dipakai dari Indonesia. Actor Apify melakukan scraping web TikTok; ini melanggar
Ketentuan Layanan TikTok dan wajib dibahas di bagian etika.

Unit data:
- caption video (post_type "original"), dihitung terhadap cap per jendela;
- komentar video (post_type "comment"), opsional, TIDAK dihitung terhadap cap tetapi tetap ditagih Apify.

Kueri: kata kunci berawalan # dikirim sebagai `hashtags`, sisanya sebagai `searchQueries`.
Filter tanggal Apify (`oldestPostDateUnified`/`newestPostDate`) dipakai, lalu hasil disaring
ulang per jendela di sisi kita karena pencarian TikTok tidak menjamin rentang tanggal.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from crawler.config import get_secret
from crawler.providers.base import Page, ProviderError, QuerySpec, SearchProvider
from crawler.providers.http import HttpClient, RetryableError

API_BASE = "https://api.apify.com/v2"


def _classify(resp: requests.Response) -> None:
    text = resp.text[:400]
    if resp.status_code == 429:
        raise RetryableError("Rate limit Apify", wait=None)
    if resp.status_code in (401, 403):
        raise ProviderError(f"Token Apify ditolak ({resp.status_code}): {text}")
    if resp.status_code == 402 or "not-enough-usage" in text or "usage limit" in text.lower():
        raise ProviderError(f"Kredit Apify habis: {text}")
    if resp.status_code == 408:
        raise RetryableError("Run Apify melewati batas waktu sinkron", wait=None)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_video(v: dict[str, Any]) -> dict[str, Any]:
    author = v.get("authorMeta") or {}
    return {
        "id": "v" + str(v.get("id")),
        "created_at": _iso(v.get("createTimeISO") or v.get("createTime")),
        "text": v.get("text") or "",
        "lang": v.get("textLanguage") or None,
        "author_id": str(author.get("id") or author.get("name") or ""),
        "post_type": "original",
        "like_count": v.get("diggCount"),
        "reply_count": v.get("commentCount"),
        "repost_count": v.get("shareCount"),
        "quote_count": None,
        "hashtags": [h.get("name") for h in v.get("hashtags") or [] if h.get("name")],
        "_url": v.get("webVideoUrl"),
        "_is_ad": bool(v.get("isAd") or v.get("isSponsored")),
    }


def normalize_comment(c: dict[str, Any], parent_id: str) -> dict[str, Any]:
    return {
        "id": "c" + str(c.get("cid") or c.get("id")),
        "created_at": _iso(c.get("createTimeISO") or c.get("createTime")),
        "text": c.get("text") or "",
        "lang": None,
        "author_id": str(c.get("uid") or c.get("uniqueId") or ""),
        "post_type": "comment",
        "like_count": c.get("diggCount"),
        "reply_count": c.get("replyCommentTotal"),
        "repost_count": None,
        "quote_count": None,
        "hashtags": [],
        "parent_id": parent_id,
    }


class TikTokApifyProvider(SearchProvider):
    name = "tiktok_apify"
    platform = "tiktok"
    min_page_size = 1
    max_page_size = 1000

    def __init__(self, options=None, session=None, sleep=None, clock=None):
        super().__init__(options)
        o = self.options
        self.token = get_secret(o.get("token_env", "APIFY_TOKEN"))
        self.video_actor = o.get("video_actor", "clockworks~tiktok-scraper")
        self.comment_actor = o.get("comment_actor", "clockworks~tiktok-comments-scraper")
        self.comments_per_video = int(o.get("comments_per_video", 0))
        self.search_section = o.get("search_section", "/video")
        self.sorting = o.get("video_search_sorting")  # mis. LATEST; filter berbayar di Apify
        self.extra_input = o.get("extra_input") or {}
        kw = {k: v for k, v in {"session": session, "sleep": sleep, "clock": clock}.items() if v is not None}
        self.http = HttpClient({"min_request_interval_seconds": 0.5, "request_timeout_seconds": 330, **o}, _classify, **kw)

    def describe_query(self, query: QuerySpec) -> str:
        tags, terms = self._split(query)
        return f"hashtags={tags} search={terms}"

    @staticmethod
    def _split(query: QuerySpec) -> tuple[list[str], list[str]]:
        tags = [k.lstrip("#") for k in query.keywords if k.startswith("#")]
        terms = [k.strip('"') for k in query.keywords if not k.startswith("#")]
        return tags, terms

    def _run(self, actor: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        url = f"{API_BASE}/acts/{actor}/run-sync-get-dataset-items"
        return self.http.request("POST", url, params={"token": self.token, "format": "json"}, json=payload)

    def search_page(self, query, start, end, max_results, cursor=None) -> Page:
        tags, terms = self._split(query)
        per_query = math.ceil(max_results / max(1, len(tags) + len(terms)))
        payload = {
            "resultsPerPage": per_query,
            "oldestPostDateUnified": start.strftime("%Y-%m-%d"),
            "newestPostDate": (end - timedelta(seconds=1)).strftime("%Y-%m-%d"),
            "commentsPerPost": 0,
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False,
            **self.extra_input,
        }
        if tags:
            payload["hashtags"] = tags
        if terms:
            payload["searchQueries"] = terms
            payload["searchSection"] = self.search_section
            if self.sorting:
                payload["videoSearchSorting"] = self.sorting
        items = self._run(self.video_actor, payload)
        if isinstance(items, dict):  # respons error berbentuk objek
            raise ProviderError(f"Respons Apify tidak terduga: {str(items)[:300]}")

        videos, seen = [], set()
        for it in items:
            if not it.get("id") or it.get("id") in seen:
                continue
            seen.add(it.get("id"))
            v = normalize_video(it)
            if v["created_at"] and start <= datetime.fromisoformat(v["created_at"].replace("Z", "+00:00")) < end:
                videos.append(v)
        videos = videos[:max_results]

        comments = []
        if self.comments_per_video > 0 and videos:
            urls = [v["_url"] for v in videos if v.get("_url")]
            by_url = {v["_url"]: v["id"] for v in videos if v.get("_url")}
            raw = self._run(self.comment_actor, {"postURLs": urls, "commentsPerPost": self.comments_per_video, "maxRepliesPerComment": 0})
            for c in raw if isinstance(raw, list) else []:
                parent = by_url.get(c.get("videoWebUrl") or c.get("submittedVideoUrl"), "")
                if c.get("cid") or c.get("id"):
                    comments.append(normalize_comment(c, parent))

        for v in videos:
            v.pop("_url", None)
        # Satu run Apify per unit; tidak ada halaman berikutnya.
        return Page(posts=videos + comments, next_cursor=None, meta={"videos": len(videos), "comments": len(comments)})

    def close(self) -> None:
        self.http.close()
