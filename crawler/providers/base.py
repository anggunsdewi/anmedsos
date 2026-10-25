"""Antarmuka yang harus dipenuhi setiap sumber data.

Provider hanya bertugas mengambil satu halaman hasil pencarian dan mengubahnya
ke format unggahan standar (NORMALIZED_FIELDS). Jendela waktu, cap, checkpoint,
deduplikasi, penyaringan, dan pseudonimisasi diurus oleh pipeline, sehingga
mengganti API cukup dengan menulis provider baru.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Format unggahan standar yang dikembalikan provider. Atribut lain (nama tampilan,
# foto profil, bio, lokasi) sengaja tidak diminta maupun disimpan.
NORMALIZED_FIELDS = (
    "id",            # str, ID unggahan
    "created_at",    # str ISO-8601 UTC, mis. 2025-02-14T03:21:09Z
    "text",          # str, teks lengkap
    "lang",          # str | None, kode bahasa dari platform
    "author_id",     # str, ID akun (hanya untuk di-hash; tidak ikut ke dataset final)
    "post_type",     # "original" | "reply" | "quote" | "repost"
    "like_count",    # int | None (None = tidak tersedia, jangan diisi 0)
    "reply_count",   # int | None
    "repost_count",  # int | None
    "quote_count",   # int | None
    "hashtags",      # list[str] tanpa tanda #
)


@dataclass
class QuerySpec:
    group: str
    keywords: list[str]
    lang: str
    exclude_reposts: bool = True
    include_replies: bool = True
    include_quotes: bool = True


@dataclass
class Page:
    posts: list[dict[str, Any]]
    next_cursor: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class ProviderError(Exception):
    """Kesalahan yang tidak bisa diselesaikan dengan mencoba ulang (kredensial, kuota habis, kueri salah)."""


class SearchProvider(ABC):
    name = "base"
    # Batas ukuran halaman yang diterima API. Pipeline menyesuaikan permintaan ke rentang ini.
    min_page_size = 1
    max_page_size = 100

    def __init__(self, options: dict[str, Any] | None = None):
        self.options = options or {}

    @abstractmethod
    def search_page(
        self,
        query: QuerySpec,
        start: datetime,
        end: datetime,
        max_results: int,
        cursor: str | None = None,
    ) -> Page:
        """Ambil satu halaman unggahan dengan start <= created_at < end (UTC)."""

    def count(self, query: QuerySpec, start: datetime, end: datetime) -> int | None:
        """Opsional: jumlah total unggahan yang cocok (tanpa mengambil isinya). None jika tidak didukung."""
        return None

    def describe_query(self, query: QuerySpec) -> str:
        """Teks kueri yang dikirim ke API, untuk dicatat di log."""
        return f"{query.group}: {', '.join(query.keywords)}"

    def close(self) -> None:
        pass
