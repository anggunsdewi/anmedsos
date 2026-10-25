"""Kriteria inklusi/eksklusi (Tabel 2). Setiap filter menerima daftar rekaman dan
mengembalikan (lolos, dibuang) sehingga jumlah per filter bisa dicatat."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Callable

from crawler.config import Config
from crawler.textutils import keyword_regex, normalize_for_identity, word_count

Records = list[dict]
FilterFn = Callable[[Records], tuple[Records, Records]]


def _split(records: Records, keep: Callable[[dict], bool]) -> tuple[Records, Records]:
    kept, dropped = [], []
    for r in records:
        (kept if keep(r) else dropped).append(r)
    return kept, dropped


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _pattern_hits(patterns: list[re.Pattern], text: str) -> int:
    return sum(1 for p in patterns if p.search(text))


def build_filters(cfg: Config, period_start: datetime, period_end: datetime) -> dict[str, FilterFn]:
    p = cfg.processing
    lang = cfg.query["lang"]
    drop_tags = p.get("count_words_without_hashtags", True)
    min_words = int(p["min_words"])
    kw_patterns = [keyword_regex(k) for kws in cfg.query["groups"].values() for k in kws]

    ja = p.get("job_ad", {})
    ja_strong = [re.compile(x, re.IGNORECASE) for x in ja.get("strong_patterns", [])]
    ja_weak = [re.compile(x, re.IGNORECASE) for x in ja.get("patterns", [])]
    ja_min = int(ja.get("min_hits", 2))

    sp = p.get("spam", {})
    sp_pats = [re.compile(x, re.IGNORECASE) for x in sp.get("patterns", [])]
    sp_min = int(sp.get("min_hits", 1))

    def is_job_ad(text: str) -> bool:
        return _pattern_hits(ja_strong, text) >= 1 or _pattern_hits(ja_weak, text) >= ja_min

    def identical_text(records: Records) -> tuple[Records, Records]:
        threshold = int(p.get("identical_text_min_accounts", 3))
        authors = defaultdict(set)
        for r in records:
            key = normalize_for_identity(r["post"]["text"])
            if key:
                authors[key].add(r["post"]["author_id"])
        bad = {k for k, a in authors.items() if len(a) >= threshold}
        return _split(records, lambda r: normalize_for_identity(r["post"]["text"]) not in bad)

    return {
        "period": lambda rs: _split(rs, lambda r: period_start <= _parse_ts(r["post"]["created_at"]) < period_end),
        "lang": lambda rs: _split(rs, lambda r: (r["post"].get("lang") or "") == lang),
        "repost": lambda rs: _split(rs, lambda r: r["post"].get("post_type") != "repost"),
        "keyword": lambda rs: _split(rs, lambda r: any(k.search(r["post"]["text"]) for k in kw_patterns)),
        "min_words": lambda rs: _split(rs, lambda r: word_count(r["post"]["text"], drop_tags) >= min_words),
        "job_ad": lambda rs: _split(rs, lambda r: not is_job_ad(r["post"]["text"])),
        "spam": lambda rs: _split(rs, lambda r: _pattern_hits(sp_pats, r["post"]["text"]) < sp_min),
        "identical_text": identical_text,
    }
