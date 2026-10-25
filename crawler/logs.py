"""Pencatatan jumlah data per tahap ke CSV."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if new:
            w.writeheader()
        w.writerows(rows)


SUMMARY_FIELDS = ["run_id", "timestamp_utc", "stage", "input_count", "output_count", "dropped", "dropped_pct_of_raw", "note"]


class StageSummary:
    """Mengumpulkan baris untuk logs/process_summary.csv dalam satu kali proses."""

    def __init__(self, path: Path, run_id: str):
        self.path = path
        self.run_id = run_id
        self.rows: list[dict] = []
        self.raw_total: int | None = None

    def add(self, stage: str, input_count: int, output_count: int, note: str = "") -> None:
        if self.raw_total is None:
            self.raw_total = input_count
        dropped = input_count - output_count
        pct = round(100 * dropped / self.raw_total, 2) if self.raw_total else 0.0
        self.rows.append({
            "run_id": self.run_id,
            "timestamp_utc": now_iso(),
            "stage": stage,
            "input_count": input_count,
            "output_count": output_count,
            "dropped": dropped,
            "dropped_pct_of_raw": pct,
            "note": note,
        })

    def write(self) -> None:
        append_csv(self.path, SUMMARY_FIELDS, self.rows)
