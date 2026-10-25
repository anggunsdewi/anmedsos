"""Uji provider X API v2 dengan respons HTTP tiruan (tanpa koneksi internet)."""

import os
import unittest
from datetime import datetime, timezone

import requests

from crawler.providers import ProviderError, QuerySpec
from crawler.providers.x_api_v2 import XApiV2Provider, build_query, normalize


class FakeResp:
    def __init__(self, status, body=None, headers=None, text=""):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params)))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def close(self):
        pass


TWEET = {
    "id": "1", "text": "potong", "created_at": "2025-02-10T01:00:00.000Z", "lang": "id", "author_id": "99",
    "public_metrics": {"like_count": 5, "reply_count": 1, "retweet_count": 2, "quote_count": 0},
    "referenced_tweets": [{"type": "quoted", "id": "7"}],
    "note_tweet": {"text": "teks panjang utuh #KaburAjaDulu", "entities": {"hashtags": [{"tag": "KaburAjaDulu"}]}},
}

Q = QuerySpec("aspirasi", ["#KaburAjaDulu", "kerja di LN"], "id")
S = datetime(2025, 2, 1, tzinfo=timezone.utc)
E = datetime(2025, 2, 8, tzinfo=timezone.utc)


def provider(responses, **opts):
    os.environ["X_BEARER_TOKEN"] = "dummy"
    sleeps = []
    sess = FakeSession(responses)
    p = XApiV2Provider({"min_request_interval_seconds": 0, **opts}, session=sess, sleep=sleeps.append, clock=lambda: 1000.0)
    return p, sess, sleeps


class XProviderTest(unittest.TestCase):
    def test_build_query(self):
        self.assertEqual(build_query(Q), '(#KaburAjaDulu OR "kerja di LN") lang:id -is:retweet')
        self.assertEqual(build_query(QuerySpec("x", ["PHK"], "id", include_replies=False)), "PHK lang:id -is:retweet -is:reply")

    def test_normalize_uses_note_tweet(self):
        n = normalize(TWEET)
        self.assertEqual(n["text"], "teks panjang utuh #KaburAjaDulu")
        self.assertEqual(n["post_type"], "quote")
        self.assertEqual(n["repost_count"], 2)
        self.assertEqual(n["hashtags"], ["KaburAjaDulu"])

    def test_page_and_params(self):
        p, sess, _ = provider([FakeResp(200, {"data": [TWEET], "meta": {"next_token": "abc", "result_count": 1}})])
        page = p.search_page(Q, S, E, 22)
        self.assertEqual(page.next_cursor, "abc")
        url, params = sess.calls[0]
        self.assertTrue(url.endswith("/tweets/search/all"))
        self.assertEqual(params["max_results"], 22)
        self.assertEqual(params["start_time"], "2025-02-01T00:00:00Z")
        self.assertNotIn("expansions", params)

    def test_min_page_size(self):
        p, sess, _ = provider([FakeResp(200, {"meta": {}})])
        p.search_page(Q, S, E, 3)
        self.assertEqual(sess.calls[0][1]["max_results"], 10)

    def test_retry_on_429_then_success(self):
        p, sess, sleeps = provider([
            FakeResp(429, headers={"x-rate-limit-reset": "1060"}, text="Too Many Requests"),
            FakeResp(503, text="unavailable"),
            requests.ConnectionError("reset"),
            FakeResp(200, {"data": [TWEET], "meta": {}}),
        ])
        page = p.search_page(Q, S, E, 10)
        self.assertEqual(len(page.posts), 1)
        self.assertEqual(sleeps[0], 61.0)   # tunggu sampai reset + 1 detik
        self.assertEqual(len(sess.calls), 4)

    def test_usage_cap_is_fatal(self):
        p, _, _ = provider([FakeResp(429, text='{"title":"UsageCapExceeded"}')])
        with self.assertRaises(ProviderError):
            p.search_page(Q, S, E, 10)

    def test_forbidden_is_fatal(self):
        p, _, _ = provider([FakeResp(403, text="client-not-enrolled")])
        with self.assertRaises(ProviderError):
            p.search_page(Q, S, E, 10)

    def test_gives_up_after_max_retries(self):
        p, _, _ = provider([FakeResp(500)] * 3, max_retries=2)
        with self.assertRaises(ProviderError):
            p.search_page(Q, S, E, 10)

    def test_count_paginates(self):
        p, _, _ = provider([
            FakeResp(200, {"meta": {"total_tweet_count": 40, "next_token": "n"}}),
            FakeResp(200, {"meta": {"total_tweet_count": 2}}),
        ])
        self.assertEqual(p.count(Q, S, E), 42)


if __name__ == "__main__":
    unittest.main()
