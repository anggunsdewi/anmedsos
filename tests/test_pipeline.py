"""Uji end-to-end dengan provider mock: python -m unittest discover tests"""

import csv
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from crawler.collect import collect, plan_units
from crawler.config import load_config
from crawler.process import process
from crawler.providers import load_provider
from crawler.textutils import keyword_regex, pseudonymize_text, word_count

ROOT = Path(__file__).resolve().parents[1]


def make_config(tmp: Path, **collection) -> Path:
    raw = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    raw["provider"] = {"name": "mock", "options": {"posts_per_window": 60}}
    raw["collection"].update({"start_date": "2025-01-01", "end_date": "2025-02-28", "cap_per_window": 10})
    raw["collection"].update(collection)
    path = tmp / "config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return path


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["PSEUDONYM_SALT"] = "test-salt"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_windows_cover_period(self):
        cfg = load_config(make_config(self.tmp))
        units = plan_units(cfg)
        weeks = sorted({u.week_label for u in units})
        self.assertEqual(weeks[0], "2025-01-01")
        self.assertEqual(len(weeks), 9)  # 59 hari -> 8 minggu penuh + 1 jendela 3 hari
        self.assertEqual(len(units), 9 * 3)

    def test_full_period_has_78_windows(self):
        cfg = load_config(ROOT / "config.yaml")
        self.assertEqual(len({u.week_label for u in plan_units(cfg)}), 78)

    def test_slices_split_cap(self):
        cfg = load_config(make_config(self.tmp, slices_per_window=7, cap_per_window=22))
        units = [u for u in plan_units(cfg) if u.week_label == "2025-01-01" and u.query.group == "umum"]
        self.assertEqual(len(units), 7)
        self.assertEqual(sum(u.cap for u in units), 22)

    def test_collect_resume_and_process(self):
        cfg = load_config(make_config(self.tmp))
        prov = load_provider("mock", {"posts_per_window": 60})

        # Ambil sebagian, lalu lanjutkan: unit yang sudah selesai tidak diulang.
        s1 = collect(cfg, prov, limit_units=5)
        self.assertEqual(s1["units_done_now"], 5)
        s2 = collect(cfg, prov)
        self.assertEqual(s2["units_done_before"], 5)
        self.assertEqual(s2["units_remaining"], 0)
        self.assertEqual(s2["fetched_total"], 27 * 10)
        req_before = prov.requests_made
        s3 = collect(cfg, prov)
        self.assertEqual(prov.requests_made, req_before, "run ulang tidak boleh memanggil API lagi")
        self.assertEqual(s3["fetched_now"], 0)

        res = process(cfg)
        self.assertGreater(res["final"], 0)
        self.assertLess(res["final"], res["raw"])

        with open(cfg.data_dir / "final" / "dataset_final.csv", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        ids = [r["post_id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)), "post_id harus unik")
        for r in rows:
            self.assertNotIn("@budi_123", r["text"])
            self.assertNotIn("t.co", r["text"])
            self.assertEqual(len(r["user_hash"]), 64)
            self.assertEqual(r["lang"], "id")
            self.assertNotEqual(r["post_type"], "repost")
            self.assertNotIn("LOKER", r["text"])
            self.assertNotIn("gacor", r["text"])
            self.assertNotIn("Pemerintah harus buka lapangan", r["text"])
            self.assertGreaterEqual(word_count(r["text"]), 3)
        self.assertTrue(any(";" in r["matched_groups"] for r in rows), "harus ada unggahan multi-grup")
        self.assertTrue(any(r["repost_count"] == "" for r in rows), "nilai kosong tidak boleh diisi 0")
        self.assertNotIn("author_id", rows[0])

        with open(cfg.log_dir / "process_summary.csv", encoding="utf-8") as f:
            stages = [r["stage"] for r in csv.DictReader(f)]
        self.assertEqual(stages[0], "raw_collected")
        self.assertIn("filter_identical_text", stages)
        self.assertEqual(stages[-1], "final_pseudonymized")

    def test_resume_truncates_partial_page(self):
        cfg = load_config(make_config(self.tmp))
        prov = load_provider("mock", {"posts_per_window": 60})
        collect(cfg, prov, limit_units=1)
        unit = plan_units(cfg)[0]
        # Simulasikan crash: baris tambahan tertulis tetapi checkpoint tidak diperbarui.
        state = json.loads(cfg.checkpoint_file.read_text())
        state["units"][unit.uid].update({"done": False, "lines": 3, "count": 3, "cursor": "3"})
        cfg.checkpoint_file.write_text(json.dumps(state))
        collect(cfg, prov, limit_units=1)
        lines = unit.raw_path.read_text().splitlines()
        self.assertEqual(len(lines), 10)
        self.assertEqual(len({json.loads(l)["post"]["id"] for l in lines}), 10)


class TextTest(unittest.TestCase):
    def test_keyword_regex(self):
        self.assertTrue(keyword_regex("PHK").search("baru kena #PHK nih"))
        self.assertTrue(keyword_regex("cari kerja").search("susah  cari\nkerja"))
        self.assertFalse(keyword_regex("gaji").search("penggajian"))
        self.assertTrue(keyword_regex("#KaburAjaDulu").search("#kaburajadulu aja"))

    def test_pseudonymize(self):
        self.assertEqual(pseudonymize_text("@a_b halo @CD, mail x@y.com https://t.co/z"),
                         "@user halo @user, mail x@y.com [url]")

    def test_word_count(self):
        self.assertEqual(word_count("@x PHK lagi #KaburAjaDulu https://t.co/a"), 2)


if __name__ == "__main__":
    unittest.main()
