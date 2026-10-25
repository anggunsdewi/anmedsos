"""Uji provider Threads dan TikTok (Apify) dengan respons HTTP tiruan."""

import csv
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from crawler.collect import collect, plan_units
from crawler.config import load_config
from crawler.process import process
from crawler.providers import ProviderError, QuerySpec, SearchProvider, provider_class
from crawler.providers.base import Page
from crawler.providers.threads_api import ThreadsApiProvider
from crawler.providers.tiktok_apify import TikTokApifyProvider

ROOT = Path(__file__).resolve().parents[1]
S = datetime(2025, 2, 1, tzinfo=timezone.utc)
E = datetime(2025, 2, 8, tzinfo=timezone.utc)


class FakeResp:
    def __init__(self, status, body=None, text=""):
        self.status_code, self._body, self.text, self.headers = status, body, text or str(body), {}

    def json(self):
        if self._body is None:
            raise ValueError
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls, self.headers = list(responses), [], {}

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.responses.pop(0)

    def close(self):
        pass


def threads(responses):
    os.environ["THREADS_ACCESS_TOKEN"] = "tok"
    sess, sleeps = FakeSession(responses), []
    return ThreadsApiProvider({"min_request_interval_seconds": 0}, session=sess, sleep=sleeps.append, clock=lambda: 0.0), sess, sleeps


def tiktok(responses, **opts):
    os.environ["APIFY_TOKEN"] = "tok"
    sess = FakeSession(responses)
    return TikTokApifyProvider({"min_request_interval_seconds": 0, **opts}, session=sess, sleep=lambda s: None, clock=lambda: 0.0), sess


THREAD_ITEM = {"id": "111", "text": "Susah cari kerja, mending #KaburAjaDulu", "timestamp": "2025-02-03T10:00:00+0000",
               "username": "someone", "is_reply": False, "is_quote_post": True, "media_type": "TEXT_POST"}


class ThreadsTest(unittest.TestCase):
    def test_no_or_support(self):
        self.assertFalse(provider_class("threads_api").supports_or)
        cfg = load_config(ROOT / "config.threads.yaml")
        units = plan_units(cfg, force_split=True)
        self.assertEqual(len(units), 78 * 16)
        self.assertTrue(all(len(u.query.keywords) == 1 for u in units))

    def test_search_params_and_normalize(self):
        p, sess, _ = threads([FakeResp(200, {"data": [THREAD_ITEM]})])
        page = p.search_page(QuerySpec("aspirasi", ["#KaburAjaDulu"], "id"), S, E, 4)
        _, url, kw = sess.calls[0]
        self.assertTrue(url.endswith("/keyword_search"))
        self.assertEqual(kw["params"]["q"], "KaburAjaDulu")
        self.assertEqual(kw["params"]["search_mode"], "TAG")
        self.assertEqual(kw["params"]["limit"], 4)
        self.assertEqual(kw["params"]["since"], int(S.timestamp()))
        post = page.posts[0]
        self.assertEqual(post["created_at"], "2025-02-03T10:00:00Z")
        self.assertEqual(post["post_type"], "quote")
        self.assertIsNone(post["lang"])
        self.assertIsNone(post["like_count"])
        self.assertEqual(post["hashtags"], ["KaburAjaDulu"])
        self.assertIsNone(page.next_cursor)

    def test_rate_limit_retry(self):
        p, sess, sleeps = threads([FakeResp(400, {"error": {"code": 4, "message": "limit"}}), FakeResp(200, {"data": []})])
        p.search_page(QuerySpec("g", ["PHK"], "id"), S, E, 5)
        self.assertEqual(len(sess.calls), 2)
        self.assertEqual(len(sleeps), 1)

    def test_permission_error_is_fatal(self):
        p, _, _ = threads([FakeResp(400, {"error": {"code": 10, "message": "no permission"}})])
        with self.assertRaises(ProviderError):
            p.search_page(QuerySpec("g", ["PHK"], "id"), S, E, 5)


VIDEO = {"id": "7001", "text": "Realita fresh graduate susah cari kerja #kaburajadulu", "textLanguage": "id",
         "createTimeISO": "2025-02-02T05:00:00.000Z", "authorMeta": {"id": "u1", "name": "abc"},
         "diggCount": 10, "commentCount": 3, "shareCount": 1, "hashtags": [{"name": "kaburajadulu"}],
         "webVideoUrl": "https://www.tiktok.com/@abc/video/7001"}
OLD_VIDEO = {**VIDEO, "id": "7002", "createTimeISO": "2024-11-01T00:00:00.000Z", "webVideoUrl": "u2"}
AD_VIDEO = {**VIDEO, "id": "7003", "isAd": True, "webVideoUrl": "u3"}
COMMENT = {"cid": "c9", "text": "sama kak, udah 50 lamaran ga ada kabar", "createTimeISO": "2025-02-04T00:00:00.000Z",
           "uid": "u77", "diggCount": 2, "videoWebUrl": "https://www.tiktok.com/@abc/video/7001"}


class TikTokTest(unittest.TestCase):
    def test_videos_comments_and_window_filter(self):
        p, sess = tiktok([FakeResp(200, [VIDEO, OLD_VIDEO, AD_VIDEO]), FakeResp(200, [COMMENT])], comments_per_video=5)
        page = p.search_page(QuerySpec("umum", ["#KaburAjaDulu", "cari kerja"], "id"), S, E, 10)
        _, url, kw = sess.calls[0]
        self.assertIn("clockworks~tiktok-scraper", url)
        self.assertEqual(kw["json"]["hashtags"], ["KaburAjaDulu"])
        self.assertEqual(kw["json"]["searchQueries"], ["cari kerja"])
        self.assertEqual(kw["json"]["resultsPerPage"], 5)
        self.assertEqual(kw["json"]["oldestPostDateUnified"], "2025-02-01")
        self.assertEqual(kw["json"]["newestPostDate"], "2025-02-07")
        ids = [x["id"] for x in page.posts]
        self.assertEqual(ids, ["v7001", "v7003", "cc9"])  # video lama dibuang
        self.assertEqual(page.posts[-1]["parent_id"], "v7001")
        self.assertEqual(page.posts[-1]["post_type"], "comment")
        self.assertEqual(sess.calls[1][2]["json"]["postURLs"][0], VIDEO["webVideoUrl"])

    def test_credit_exhausted_is_fatal(self):
        p, _ = tiktok([FakeResp(402, None, text="not-enough-usage")])
        with self.assertRaises(ProviderError):
            p.search_page(QuerySpec("g", ["PHK"], "id"), S, E, 10)


class FakeTikTok(SearchProvider):
    """Provider tiruan yang meniru keluaran TikTok: video + komentar dalam satu halaman."""
    name, platform = "fake_tiktok", "tiktok"
    max_page_size = 1000

    def search_page(self, query, start, end, max_results, cursor=None):
        posts = []
        base = int(start.timestamp())
        t_video = (start + timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
        t_comment = (start + timedelta(hours=13)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(max_results + 3):  # sengaja melebihi cap
            vid = f"v{base}{query.group}{i}"
            posts.append({"id": vid, "created_at": t_video,
                          "text": f"Fresh graduate susah cari kerja, gaji kecil banget minggu {base} nomor {i}",
                          "lang": "id", "author_id": f"a{i}", "post_type": "original", "like_count": 1,
                          "reply_count": 1, "repost_count": 1, "quote_count": None, "hashtags": [],
                          "_is_ad": i == 0})
            posts.append({"id": f"c{vid}", "created_at": t_comment,
                          "text": f"Sama banget kak, aku juga udah lama nyari belum dapet {base}{i}", "lang": None,
                          "author_id": f"k{i}", "post_type": "comment", "like_count": 0, "reply_count": None,
                          "repost_count": None, "quote_count": None, "hashtags": [], "parent_id": vid})
        return Page(posts=posts)


class TikTokPipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["PSEUDONYM_SALT"] = "s"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_comments_do_not_count_toward_cap(self):
        raw = yaml.safe_load((ROOT / "config.tiktok.yaml").read_text())
        raw["extends"] = str(ROOT / "config.yaml")
        raw["collection"].update({"start_date": "2025-01-01", "end_date": "2025-01-14", "cap_per_window": 4})
        path = self.tmp / "c.yaml"
        path.write_text(yaml.safe_dump(raw))
        cfg = load_config(path)
        stats = collect(cfg, FakeTikTok())
        self.assertEqual(stats["units_remaining"], 0)
        # 2 minggu x 3 grup x (4 video + 7 komentar)
        self.assertEqual(stats["fetched_total"], 6 * 11)
        res = process(cfg)
        with open(cfg.data_dir / "final" / "dataset_final.csv", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertTrue(all(r["platform"] == "tiktok" for r in rows))
        comments = [r for r in rows if r["post_type"] == "comment"]
        self.assertTrue(comments, "komentar tanpa kata kunci tetap lolos filter keyword")
        self.assertTrue(all(r["parent_id"].startswith("v") for r in comments))
        self.assertTrue(all(r["lang_detected"] == "1" for r in comments))
        stages = {r["stage"]: r for r in res["rows"]}
        self.assertEqual(int(stages["filter_sponsored"]["dropped"]), 6)


if __name__ == "__main__":
    unittest.main()
