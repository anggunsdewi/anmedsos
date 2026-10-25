"""Tahap pengambilan data: per jendela mingguan x grup kata kunci, dengan cap, checkpoint, dan log."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from crawler.checkpoint import Checkpoint, truncate_lines
from crawler.config import Config
from crawler.logs import append_csv, now_iso
from crawler.providers import ProviderError, QuerySpec, SearchProvider
from crawler.windows import Window, build_windows, split_evenly

log = logging.getLogger(__name__)

COLLECTION_LOG_FIELDS = [
    "timestamp_utc", "window", "group", "query", "slice_start_utc", "slice_end_utc",
    "cap", "fetched", "requests", "status",
]


@dataclass
class Unit:
    uid: str
    window: Window      # irisan waktu yang diambil (bisa sama dengan jendela mingguan)
    week_label: str
    query: QuerySpec
    cap: int
    raw_path: Path


def plan_units(cfg: Config) -> list[Unit]:
    c, q = cfg.collection, cfg.query
    windows = build_windows(cfg.start_date, cfg.end_date, int(c["window_days"]), cfg.project["timezone"])
    n_slices = int(c.get("slices_per_window", 1))
    split = bool(q.get("split_keywords", False))
    raw_dir = cfg.data_dir / "raw"
    units = []
    for w in windows:
        for group, keywords in q["groups"].items():
            kw_sets = [[k] for k in keywords] if split else [list(keywords)]
            subs = [(ki, kws, s) for ki, kws in enumerate(kw_sets) for s in w.slices(n_slices)]
            caps = split_evenly(int(c["cap_per_window"]), len(subs))
            for (ki, kws, s), cap in zip(subs, caps):
                if cap <= 0:
                    continue
                suffix = (f"_k{ki + 1}" if split else "") + (s.label[len(w.label):] if n_slices > 1 else "")
                spec = QuerySpec(
                    group=group,
                    keywords=kws,
                    lang=q["lang"],
                    exclude_reposts=q.get("exclude_reposts", True),
                    include_replies=q.get("include_replies", True),
                    include_quotes=q.get("include_quotes", True),
                )
                units.append(Unit(
                    uid=f"{w.label}|{group}{suffix}",
                    window=s,
                    week_label=w.label,
                    query=spec,
                    cap=cap,
                    raw_path=raw_dir / w.label / f"{group}{suffix}.jsonl",
                ))
    return units


def collect(cfg: Config, provider: SearchProvider, limit_units: int | None = None) -> dict:
    units = plan_units(cfg)
    ckpt = Checkpoint(cfg.checkpoint_file)
    budget = int(cfg.collection.get("max_posts_total") or 0)
    coll_log = cfg.log_dir / "collection_log.csv"
    stats = {"units_total": len(units), "units_done_before": 0, "units_done_now": 0, "fetched_now": 0, "stopped": None}

    pending = []
    for u in units:
        if ckpt.unit(u.uid)["done"]:
            stats["units_done_before"] += 1
        else:
            pending.append(u)
    log.info("%d unit kueri, %d sudah selesai sebelumnya, %d tersisa.", len(units), stats["units_done_before"], len(pending))
    if limit_units is not None:
        pending = pending[:limit_units]

    for u in pending:
        if budget and ckpt.total_fetched() >= budget:
            stats["stopped"] = f"max_posts_total ({budget}) tercapai"
            log.warning("Berhenti: %s.", stats["stopped"])
            break
        try:
            fetched = _collect_unit(u, provider, ckpt, budget)
        except ProviderError as e:
            stats["stopped"] = str(e)
            log.error("Berhenti di %s: %s", u.uid, e)
            st = ckpt.unit(u.uid)
            _log_unit(coll_log, u, provider, st, "error: " + str(e)[:200])
            break
        stats["fetched_now"] += fetched
        st = ckpt.unit(u.uid)
        if st["done"]:
            stats["units_done_now"] += 1
            _log_unit(coll_log, u, provider, st, st.get("status", "done"))

    stats["fetched_total"] = ckpt.total_fetched()
    stats["units_remaining"] = sum(1 for u in units if not ckpt.unit(u.uid)["done"])
    ckpt.save()
    return stats


def _collect_unit(u: Unit, provider: SearchProvider, ckpt: Checkpoint, budget: int) -> int:
    st = ckpt.unit(u.uid)
    u.raw_path.parent.mkdir(parents=True, exist_ok=True)
    truncate_lines(u.raw_path, st["lines"])  # buang sisa tulisan yang belum tercatat di checkpoint
    fetched_now = 0
    query_text = provider.describe_query(u.query)
    log.info("[%s] %s (cap %d, sudah %d)", u.uid, query_text, u.cap, st["lines"])

    while st["lines"] < u.cap:
        if budget and ckpt.total_fetched() >= budget:
            return fetched_now
        remaining = u.cap - st["lines"]
        request_size = max(provider.min_page_size, min(provider.max_page_size, remaining))
        page = provider.search_page(u.query, u.window.start, u.window.end, request_size, st["cursor"])
        st["requests"] += 1
        posts = page.posts[:remaining]
        if len(page.posts) > remaining:
            log.debug("[%s] %d unggahan ekstra dibuang karena melebihi cap.", u.uid, len(page.posts) - remaining)
        with open(u.raw_path, "a", encoding="utf-8") as f:
            for p in posts:
                rec = {
                    "post": p,
                    "group": u.query.group,
                    "keywords": u.query.keywords,
                    "week": u.week_label,
                    "fetched_at": now_iso(),
                    "provider": provider.name,
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        st["lines"] += len(posts)
        st["cursor"] = page.next_cursor
        fetched_now += len(posts)
        if st["lines"] >= u.cap:
            st["done"], st["status"], st["cursor"] = True, "cap_reached", None
        elif not page.next_cursor or not page.posts:
            st["done"], st["status"] = True, "exhausted"  # hasil pencarian di jendela ini habis sebelum cap
        ckpt.save()
        if st["done"]:
            return fetched_now

    # Sampai di sini jika cap sudah terpenuhi sebelumnya (mis. cap di config diturunkan).
    st["done"], st["status"], st["cursor"] = True, "cap_reached", None
    ckpt.save()
    return fetched_now


def _log_unit(path: Path, u: Unit, provider: SearchProvider, st: dict, status: str) -> None:
    append_csv(path, COLLECTION_LOG_FIELDS, [{
        "timestamp_utc": now_iso(),
        "window": u.week_label,
        "group": u.query.group,
        "query": provider.describe_query(u.query),
        "slice_start_utc": u.window.start.isoformat(),
        "slice_end_utc": u.window.end.isoformat(),
        "cap": u.cap,
        "fetched": st["lines"],
        "requests": st["requests"],
        "status": status,
    }])


ESTIMATE_FIELDS = ["window", "group", "query", "matching_posts"]


def estimate(cfg: Config, provider: SearchProvider) -> Path:
    """Jumlah unggahan yang cocok per jendela x grup (endpoint counts). Berguna untuk
    melihat volume asli sebelum dibatasi cap, mis. untuk descriptive analysis."""
    out = cfg.log_dir / "volume_estimate.csv"
    c = cfg.collection
    windows = {w.label: w for w in build_windows(cfg.start_date, cfg.end_date, int(c["window_days"]), cfg.project["timezone"])}
    seen = set()
    rows = []
    for u in plan_units(cfg):
        key = (u.week_label, u.query.group, tuple(u.query.keywords))
        if key in seen:
            continue
        seen.add(key)
        w = windows[u.week_label]  # hitung untuk satu jendela utuh, bukan irisan
        n = provider.count(u.query, w.start, w.end)
        if n is None:
            raise ProviderError(f"Provider {provider.name} tidak mendukung penghitungan volume.")
        rows.append({"window": u.week_label, "group": u.query.group, "query": provider.describe_query(u.query), "matching_posts": n})
        log.info("%s %s: %d", u.week_label, u.query.group, n)
    if out.exists():
        out.unlink()
    append_csv(out, ESTIMATE_FIELDS, rows)
    return out
