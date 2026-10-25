"""Provider data sintetis untuk menguji pipeline tanpa kredensial dan tanpa biaya.

Sengaja memuat kasus yang harus ditangani pipeline: unggahan yang tertangkap
beberapa grup, iklan lowongan, spam, teks identik dari banyak akun, teks pendek,
repost, bahasa lain, dan mention.
"""

from __future__ import annotations

import random
from datetime import timezone

from crawler.providers.base import Page, SearchProvider

# (teks, grup yang menangkap, lang, post_type)
TEMPLATES = [
    ("Susah banget cari kerja sekarang, udah ngelamar ke puluhan tempat belum ada panggilan", {"umum", "spesifik"}, "id", "original"),
    ("Mending #KaburAjaDulu deh, kerja di luar negeri gajinya jauh lebih manusiawi", {"aspirasi", "spesifik"}, "id", "original"),
    ("@budi_123 iya gaji fresh graduate segitu doang, gimana mau nabung https://t.co/abc123", {"umum", "spesifik"}, "id", "reply"),
    ("Kantor gue baru PHK 200 orang, takut banget giliran berikutnya", {"spesifik"}, "id", "original"),
    ("Syarat pengalaman 3 tahun buat posisi entry level itu nggak masuk akal", {"spesifik"}, "id", "quote"),
    ("Lagi mikir pindah ke luar negeri aja, karier di sini mentok", {"aspirasi", "umum"}, "id", "original"),
    ("INFO LOKER! Dibutuhkan staff admin, kirim CV ke email kami. Lowongan kerja terbatas", {"umum"}, "id", "original"),
    ("Slot gacor maxwin hari ini, daripada cari kerja mending depo 10rb", {"umum"}, "id", "original"),
    ("Pemerintah harus buka lapangan pekerjaan sekarang juga!!!", {"umum"}, "id", "original"),  # teks bot
    ("PHK lagi", {"spesifik"}, "id", "original"),
    ("Looking for pekerjaan remote, any leads?", {"umum"}, "en", "original"),
    ("RT @akun_besar: kabur aja dulu, kerja di LN lebih menjanjikan", {"aspirasi"}, "id", "repost"),
    ("Pengangguran makin banyak tapi rekrutmen makin ribet, harus psikotes lima tahap", {"spesifik", "umum"}, "id", "original"),
]


TAILS = ["capek banget", "serius deh", "huft", "beneran", "gimana ya", "ya ampun"]


class MockProvider(SearchProvider):
    name = "mock"
    platform = "mock"
    max_page_size = 10

    def __init__(self, options=None):
        super().__init__(options)
        self.posts_per_window = int(self.options.get("posts_per_window", 40))
        self.requests_made = 0

    def _pool(self, start, end):
        rng = random.Random(int(start.timestamp()))
        span = (end - start).total_seconds()
        pool = []
        for i in range(self.posts_per_window):
            idx = i % len(TEMPLATES)
            text, groups, lang, ptype = TEMPLATES[idx]
            # Teks bot dikirim dari banyak akun berbeda; lainnya dari akun acak.
            author = f"bot{int(start.timestamp())}_{i}" if idx == 8 else f"u{rng.randint(1, 500)}"
            ts = start.timestamp() + rng.random() * span
            if idx not in (8, 9):  # selain teks bot dan teks pendek, buat tiap unggahan unik
                text = f"{text} ({rng.choice(TAILS)} {start:%d%m%y}{i})"
            pool.append({
                "id": f"{int(start.timestamp())}{i:04d}",
                "created_at": _iso(ts),
                "text": text,
                "lang": lang,
                "author_id": author,
                "post_type": ptype,
                "like_count": rng.randint(0, 300),
                "reply_count": rng.randint(0, 40),
                "repost_count": None if i % 7 == 0 else rng.randint(0, 80),
                "quote_count": rng.randint(0, 10),
                "hashtags": ["KaburAjaDulu"] if "#KaburAjaDulu" in text else [],
                "_groups": groups,
            })
        return pool

    def _matching(self, query, start, end):
        return [p for p in self._pool(start, end) if query.group in p["_groups"]]

    def search_page(self, query, start, end, max_results, cursor=None):
        self.requests_made += 1
        matches = self._matching(query, start, end)
        offset = int(cursor or 0)
        size = min(self.max_page_size, max_results)
        chunk = matches[offset : offset + size]
        posts = [{k: v for k, v in p.items() if k != "_groups"} for p in chunk]
        nxt = offset + size
        return Page(posts=posts, next_cursor=str(nxt) if nxt < len(matches) else None)

    def count(self, query, start, end):
        return len(self._matching(query, start, end))


def _iso(ts: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
