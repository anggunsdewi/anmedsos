"""Pembagian periode penelitian menjadi jendela mingguan (dan irisan opsional)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Window:
    index: int
    start: datetime  # UTC, inklusif
    end: datetime    # UTC, eksklusif
    label: str       # tanggal mulai lokal, mis. 2025-01-01

    def slices(self, n: int) -> list["Window"]:
        if n <= 1:
            return [self]
        step = (self.end - self.start) / n
        out = []
        for i in range(n):
            s = self.start + step * i
            e = self.end if i == n - 1 else self.start + step * (i + 1)
            out.append(Window(self.index, s, e, f"{self.label}_s{i + 1}"))
        return out


def build_windows(start: date, end: date, window_days: int, tz_name: str) -> list[Window]:
    """Jendela [start, end] inklusif dalam zona waktu lokal, dikonversi ke UTC."""
    tz = ZoneInfo(tz_name)
    last = datetime.combine(end + timedelta(days=1), time.min, tz)
    windows = []
    cur = start
    i = 0
    while True:
        s_local = datetime.combine(cur, time.min, tz)
        if s_local >= last:
            break
        e_local = min(datetime.combine(cur + timedelta(days=window_days), time.min, tz), last)
        windows.append(
            Window(i, s_local.astimezone(timezone.utc), e_local.astimezone(timezone.utc), cur.isoformat())
        )
        cur += timedelta(days=window_days)
        i += 1
    return windows


def split_evenly(total: int, parts: int) -> list[int]:
    """Bagi `total` ke `parts` bagian sebisa mungkin rata (selisih maks 1)."""
    base, rem = divmod(total, parts)
    return [base + (1 if i < rem else 0) for i in range(parts)]


def week_start_label(created_at: datetime, windows: list[Window]) -> str | None:
    for w in windows:
        if w.start <= created_at < w.end:
            return w.label
    return None
