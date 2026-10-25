"""Tahap pengolahan: gabung data mentah, deduplikasi, saring, pseudonimisasi, ekspor."""

from __future__ import annotations

import csv
import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path

from crawler.config import Config, get_secret
from crawler.filters import build_filters
from crawler.logs import StageSummary, append_csv
from crawler.textutils import pseudonymize_text, user_hash
from crawler.windows import build_windows, week_start_label

log = logging.getLogger(__name__)

FINAL_FIELDS = [
    "platform", "post_id", "parent_id", "created_at", "week_start", "post_type", "lang", "lang_detected",
    "text", "user_hash",
    "like_count", "reply_count", "repost_count", "quote_count", "hashtags", "matched_groups",
]
METRICS = ["like_count", "reply_count", "repost_count", "quote_count"]


def load_raw(raw_dir: Path) -> list[dict]:
    records = []
    for path in sorted(raw_dir.rglob("*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records


def deduplicate(records: list[dict]) -> list[dict]:
    """Satu baris per ID unggahan; semua grup yang menangkapnya dikumpulkan di matched_groups."""
    by_id: dict[str, dict] = {}
    group_order = []
    for r in records:
        pid = (r.get("platform", ""), r["post"]["id"])
        if r["group"] not in group_order:
            group_order.append(r["group"])
        if pid not in by_id:
            by_id[pid] = {**r, "matched_groups": {r["group"]}}
        else:
            by_id[pid]["matched_groups"].add(r["group"])
    for r in by_id.values():
        r["matched_groups"] = [g for g in group_order if g in r["matched_groups"]]
    return list(by_id.values())


def _fmt(v):
    return "" if v is None else v


def to_final_row(r: dict, salt: str, replace_urls: bool, windows) -> dict:
    p = r["post"]
    created = datetime.fromisoformat(p["created_at"].replace("Z", "+00:00"))
    return {
        "platform": r.get("platform", ""),
        "post_id": p["id"],
        "parent_id": p.get("parent_id", ""),  # untuk komentar: ID video induk
        "created_at": p["created_at"],
        "week_start": week_start_label(created, windows) or r.get("week", ""),
        "post_type": p.get("post_type", ""),
        "lang": p.get("lang") or "",
        "lang_detected": "1" if p.get("lang_detected") else "0",  # 1 = hasil langdetect, bukan dari platform
        "text": pseudonymize_text(p["text"], replace_urls),
        "user_hash": user_hash(p["author_id"], salt),
        # Nilai kosong dibiarkan kosong, tidak diisi 0.
        **{m: _fmt(p.get(m)) for m in METRICS},
        "hashtags": ";".join(p.get("hashtags") or []),
        "matched_groups": ";".join(r["matched_groups"]),
    }


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def process(cfg: Config) -> dict:
    p = cfg.processing
    salt = get_secret(p.get("pseudonymize", {}).get("salt_env", "PSEUDONYM_SALT"))
    replace_urls = p.get("pseudonymize", {}).get("replace_urls", True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary = StageSummary(cfg.log_dir / "process_summary.csv", run_id)

    windows = build_windows(cfg.start_date, cfg.end_date, int(cfg.collection["window_days"]), cfg.project["timezone"])
    period_start, period_end = windows[0].start, windows[-1].end

    raw = load_raw(cfg.data_dir / "raw")
    if not raw:
        raise SystemExit("Tidak ada data mentah di data/raw. Jalankan `collect` terlebih dahulu.")
    summary.add("raw_collected", len(raw), len(raw), "semua baris dari semua kueri dan jendela")

    records = deduplicate(raw)
    summary.add("deduplicate_by_post_id", len(raw), len(records), "grup kueri digabung ke matched_groups")
    multi = sum(1 for r in records if len(r["matched_groups"]) > 1)
    log.info("Deduplikasi: %d -> %d (%d unggahan tertangkap >1 grup)", len(raw), len(records), multi)

    interim = cfg.data_dir / "interim"
    interim.mkdir(parents=True, exist_ok=True)
    dropped_log = []
    filters = build_filters(cfg, period_start, period_end)
    for name in p["filters"]:
        if name not in filters:
            raise SystemExit(f"Filter tidak dikenal di config: {name}. Pilihan: {sorted(filters)}")
        before = len(records)
        records, dropped = filters[name](records)
        summary.add(f"filter_{name}", before, len(records))
        dropped_log += [{"post_id": r["post"]["id"], "dropped_at": f"filter_{name}"} for r in dropped]
        log.info("Filter %-15s %6d -> %6d", name, before, len(records))
    write_csv(interim / "dropped_posts.csv", dropped_log, ["post_id", "dropped_at"])

    final = [to_final_row(r, salt, replace_urls, windows) for r in records]
    final.sort(key=lambda r: (r["created_at"], r["post_id"]))
    missing = {m: sum(1 for r in final if r[m] == "") for m in METRICS}
    note = "kosong: " + ", ".join(f"{m}={n}" for m, n in missing.items())
    summary.add("final_pseudonymized", len(final), len(final), note)

    out_dir = cfg.data_dir / "final"
    write_csv(out_dir / "dataset_final.csv", final, FINAL_FIELDS)
    n_sample = min(int(p.get("sample_rows", 100)), len(final))
    sample = random.Random(p.get("sample_seed", 42)).sample(final, n_sample)
    sample.sort(key=lambda r: r["created_at"])
    write_csv(out_dir / "sample_100.csv", sample, FINAL_FIELDS)

    per_group = {}
    for r in final:
        for g in r["matched_groups"].split(";"):
            per_group[g] = per_group.get(g, 0) + 1
    append_csv(cfg.log_dir / "group_counts.csv", ["run_id", "group", "final_posts"],
               [{"run_id": run_id, "group": g, "final_posts": n} for g, n in per_group.items()])

    summary.write()
    return {"run_id": run_id, "raw": len(raw), "final": len(final), "per_group": per_group, "rows": summary.rows}
