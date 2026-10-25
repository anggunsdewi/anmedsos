"""Fungsi teks bersama: pembersihan, pencocokan kata kunci, pseudonimisasi."""

from __future__ import annotations

import hashlib
import re

URL_RE = re.compile(r"https?://\S+|\bwww\.\S+", re.IGNORECASE)
# @username X: 1-15 karakter huruf/angka/garis bawah, tidak didahului huruf (agar email tidak kena).
MENTION_RE = re.compile(r"(?<![\w@])@\w{1,15}\b")
HASHTAG_RE = re.compile(r"(?<!\w)#\w+")
WORD_RE = re.compile(r"\w+", re.UNICODE)
NON_ALNUM_RE = re.compile(r"[^\w\s]+", re.UNICODE)
SPACE_RE = re.compile(r"\s+")


def clean_for_counting(text: str, drop_hashtags: bool = True) -> str:
    t = URL_RE.sub(" ", text)
    t = MENTION_RE.sub(" ", t)
    if drop_hashtags:
        t = HASHTAG_RE.sub(" ", t)
    return SPACE_RE.sub(" ", t).strip()


def word_count(text: str, drop_hashtags: bool = True) -> int:
    return len(WORD_RE.findall(clean_for_counting(text, drop_hashtags)))


def normalize_for_identity(text: str) -> str:
    """Bentuk teks untuk mendeteksi teks identik lintas akun."""
    t = clean_for_counting(text.lower(), drop_hashtags=False)
    t = NON_ALNUM_RE.sub(" ", t)
    return SPACE_RE.sub(" ", t).strip()


def keyword_regex(keyword: str) -> re.Pattern:
    kw = keyword.strip().strip('"')
    if kw.startswith("#"):
        return re.compile(re.escape(kw) + r"(?!\w)", re.IGNORECASE)
    words = kw.split()
    return re.compile(r"(?<!\w)" + r"\s+".join(re.escape(w) for w in words) + r"(?!\w)", re.IGNORECASE)


def user_hash(author_id: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{author_id}".encode("utf-8")).hexdigest()


def pseudonymize_text(text: str, replace_urls: bool = True) -> str:
    t = MENTION_RE.sub("@user", text)
    if replace_urls:
        t = URL_RE.sub("[url]", t)
    return t
