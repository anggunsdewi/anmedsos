"""Antarmuka baris perintah.

    python -m crawler plan       # lihat rencana kueri dan perkiraan jumlah unggahan
    python -m crawler estimate   # hitung volume asli per jendela (endpoint counts)
    python -m crawler collect    # ambil data (bisa dihentikan dan dilanjutkan)
    python -m crawler process    # dedup, filter, pseudonimisasi, ekspor
    python -m crawler run        # collect lalu process
    python -m crawler status     # progres checkpoint
"""

from __future__ import annotations

import argparse
import logging
import sys

from crawler.checkpoint import Checkpoint
from crawler.collect import collect, estimate, plan_units
from crawler.config import ConfigError, load_config
from crawler.process import process
from crawler.providers import ProviderError, load_provider, provider_class


def _provider(cfg, override: str | None):
    pc = cfg.provider
    return load_provider(override or pc["name"], pc.get("options") or {})


def _units(cfg, args):
    cls = provider_class(args.provider or cfg.provider["name"])
    return plan_units(cfg, force_split=not cls.supports_or)


def cmd_plan(cfg, args):
    units = _units(cfg, args)
    weeks = sorted({u.week_label for u in units})
    total_cap = sum(u.cap for u in units)
    print(f"Jendela   : {len(weeks)} ({weeks[0]} s.d. {weeks[-1]})")
    print(f"Grup      : {', '.join(cfg.query['groups'])}")
    print(f"Unit kueri: {len(units)}")
    print(f"Maks unggahan mentah (jumlah cap): {total_cap}")
    print(f"Rem biaya max_posts_total: {cfg.collection.get('max_posts_total')}")
    prov = args.provider or cfg.provider["name"]
    if not provider_class(prov).supports_or:
        print("Provider ini tidak mendukung OR, jadi dibuat satu kueri per kata kunci (cap dibagi rata).")
    if prov == "x_api_v2":
        from crawler.providers import QuerySpec
        from crawler.providers.x_api_v2 import build_query
        for g, kws in cfg.query["groups"].items():
            q = QuerySpec(g, list(kws), cfg.query["lang"], cfg.query.get("exclude_reposts", True),
                          cfg.query.get("include_replies", True), cfg.query.get("include_quotes", True))
            print(f"  [{g}] {build_query(q)}")
        min_page = 10
        small = sum(1 for u in units if u.cap < min_page)
        if small:
            print(f"Peringatan: {small} unit punya cap < {min_page} (ukuran halaman minimum X API). "
                  "Unggahan ekstra tetap terambil dan bisa ikut ditagih.")
    return 0


def cmd_status(cfg, args):
    units = _units(cfg, args)
    ck = Checkpoint(cfg.checkpoint_file)
    done = sum(1 for u in units if ck.unit(u.uid)["done"])
    print(f"Unit selesai: {done}/{len(units)}")
    print(f"Unggahan mentah terambil: {ck.total_fetched()}")
    nxt = next((u for u in units if not ck.unit(u.uid)["done"]), None)
    if nxt:
        print(f"Berikutnya: {nxt.uid}")
    return 0


def cmd_collect(cfg, args):
    provider = _provider(cfg, args.provider)
    try:
        stats = collect(cfg, provider, args.limit_units)
    finally:
        provider.close()
    print(f"Diambil sekarang: {stats['fetched_now']}, total mentah: {stats['fetched_total']}, "
          f"unit tersisa: {stats['units_remaining']}/{stats['units_total']}")
    if stats["stopped"]:
        print(f"Berhenti: {stats['stopped']}")
        print("Jalankan perintah yang sama lagi untuk melanjutkan dari checkpoint.")
        return 2
    return 0


def cmd_process(cfg, args):
    res = process(cfg)
    print(f"run_id {res['run_id']}: {res['raw']} mentah -> {res['final']} final")
    for r in res["rows"]:
        print(f"  {r['stage']:<26} {r['input_count']:>7} -> {r['output_count']:>7}  (-{r['dropped']}, {r['dropped_pct_of_raw']}% dari mentah) {r['note']}")
    print("Per grup:", ", ".join(f"{g}={n}" for g, n in res["per_group"].items()))
    return 0


def cmd_run(cfg, args):
    rc = cmd_collect(cfg, args)
    if rc != 0:
        return rc
    return cmd_process(cfg, args)


def cmd_estimate(cfg, args):
    provider = _provider(cfg, args.provider)
    try:
        out = estimate(cfg, provider)
    finally:
        provider.close()
    print(f"Tersimpan: {out}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m crawler", description="Crawler X untuk penelitian #KaburAjaDulu")
    ap.add_argument("command", choices=["plan", "estimate", "collect", "process", "run", "status"])
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("--provider", help="timpa provider.name di config (mis. mock)")
    ap.add_argument("--limit-units", type=int, help="ambil paling banyak N unit kueri (untuk uji coba)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    try:
        cfg = load_config(args.config)
        return {"plan": cmd_plan, "estimate": cmd_estimate, "collect": cmd_collect, "process": cmd_process,
                "run": cmd_run, "status": cmd_status}[args.command](cfg, args)
    except (ConfigError, ProviderError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nDihentikan. Progres tersimpan; jalankan lagi untuk melanjutkan.", file=sys.stderr)
        return 130
