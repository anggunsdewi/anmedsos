"""Contoh kerangka provider untuk API lain (mis. Scweet atau API pihak ketiga).

Cara pakai:
1. Salin berkas ini, ganti isi `search_page` sesuai API yang dipakai.
2. Di config.yaml:
       provider:
         name: "crawler.providers.example_custom:ExampleCustomProvider"
         options:
           api_key_env: THIRD_PARTY_API_KEY
3. Jalankan crawler seperti biasa. Jendela mingguan, cap, checkpoint, dedup,
   filter, dan pseudonimisasi tetap diurus pipeline.

Yang wajib: kembalikan Page berisi unggahan dengan field persis seperti
NORMALIZED_FIELDS di base.py, dan `next_cursor` (None jika halaman terakhir).
Isi None untuk metrik yang tidak tersedia, jangan 0.
"""

from __future__ import annotations

from crawler.config import get_secret
from crawler.providers.base import Page, ProviderError, SearchProvider  # noqa: F401  (Page dipakai di contoh)


class ExampleCustomProvider(SearchProvider):
    name = "example_custom"
    min_page_size = 1
    max_page_size = 20

    def __init__(self, options=None):
        super().__init__(options)
        self.api_key = get_secret(self.options.get("api_key_env", "THIRD_PARTY_API_KEY"))

    def search_page(self, query, start, end, max_results, cursor=None):
        # Contoh: susun kueri sesuai sintaks API tujuan.
        # q = " OR ".join(query.keywords) + f" lang:{query.lang} since:{start:%Y-%m-%d} until:{end:%Y-%m-%d}"
        # resp = requests.get("https://api.contoh.com/search", params={"q": q, "cursor": cursor}, headers=...)
        # items = resp.json()["tweets"]
        # posts = [{
        #     "id": str(t["id"]), "created_at": t["createdAt"], "text": t["text"], "lang": t.get("lang"),
        #     "author_id": str(t["author"]["id"]),
        #     "post_type": "reply" if t.get("isReply") else "quote" if t.get("quoted") else "original",
        #     "like_count": t.get("likeCount"), "reply_count": t.get("replyCount"),
        #     "repost_count": t.get("retweetCount"), "quote_count": t.get("quoteCount"),
        #     "hashtags": [h["text"] for h in t.get("entities", {}).get("hashtags", [])],
        # } for t in items]
        # return Page(posts=posts, next_cursor=resp.json().get("next_cursor"))
        raise ProviderError("ExampleCustomProvider hanya kerangka; isi search_page() terlebih dahulu.")
