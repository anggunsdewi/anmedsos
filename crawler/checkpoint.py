"""Penyimpanan progres pengambilan data agar bisa dilanjutkan dari titik terakhir."""

from __future__ import annotations

import json
import os
from pathlib import Path


class Checkpoint:
    def __init__(self, path: Path):
        self.path = path
        self.state: dict = {"units": {}}
        if path.exists():
            with open(path, encoding="utf-8") as f:
                self.state = json.load(f)
            self.state.setdefault("units", {})

    def unit(self, uid: str) -> dict:
        return self.state["units"].setdefault(uid, {"lines": 0, "count": 0, "cursor": None, "done": False, "requests": 0})

    def total_fetched(self) -> int:
        """Total baris mentah (termasuk komentar), dipakai untuk rem biaya max_posts_total."""
        return sum(u.get("lines", 0) for u in self.state["units"].values())

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)


def truncate_lines(path: Path, keep: int) -> None:
    """Buang baris yang ditulis setelah checkpoint terakhir (mis. karena proses terhenti di tengah halaman)."""
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    if len(lines) != keep:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines[:keep])
