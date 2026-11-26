"""26 Nov 2026, his step 2: the Scout (bin/scout.py) starts batches on its own: a new finished stream, or a top-up
from the next unused older stream when fewer than 8 fresh clips of that streamer reached the desk today."""
import datetime as dt
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:" + "a" * 35)
os.environ.setdefault("TELEGRAM_CHAT_ID", "123456")
sys.path.insert(0, str(ROOT / "bin"))
import scout as S  # noqa: E402

LACY = {"channel": "lacy", "platform": "twitch"}
V = ["https://www.twitch.tv/videos/%d" % n for n in (300, 200, 100)]  # newest first
MORNING = dt.datetime(2026, 11, 27, 9, 0)


def desk(n, camp="lacy", day="2026-11-27", status="waiting"):
    return [{"campaign": camp, "date": day, "status": status} for _ in range(n)]


def run(camp, url, status="completed", opts="scout", day="2026-11-27"):
    return {"displayTitle": "clip %s %s %s" % (camp, url, opts), "status": status, "createdAt": day + "T08:00:00Z"}


class ScoutTest(unittest.TestCase):
    def decide(self, done=(), runs=(), queue=(), now=MORNING):
        return S.decide(LACY, "lacy", V, set(done), list(runs), list(queue), now, now.date().isoformat())

    def test_a_new_finished_stream_starts_a_batch(self):
        self.assertEqual(self.decide(done={"200", "100"}, queue=desk(12)), (V[0], "new stream"))

    def test_short_day_tops_up_from_the_next_unused_older_stream(self):
        url, why = self.decide(done={"300", "200"}, queue=desk(3))
        self.assertEqual(url, V[2])
        self.assertIn("only 3 fresh", why)

    def test_enough_fresh_clips_and_no_new_stream_starts_nothing(self):
        url, why = self.decide(done={"300"}, queue=desk(8))
        self.assertIsNone(url)

    def test_his_ok_or_posting_still_counts_as_fresh(self):
        url, _ = self.decide(done={"300"}, queue=desk(4, status="ready") + desk(4, status="posted"))
        self.assertIsNone(url)

    def test_low_and_yesterday_clips_are_not_fresh(self):
        url, _ = self.decide(done={"300"}, queue=desk(8, status="low") + desk(8, day="2026-11-26"))
        self.assertEqual(url, V[1])

    def test_one_run_per_streamer_at_a_time(self):
        url, why = self.decide(runs=[run("lacy", V[0], status="in_progress")])
        self.assertIsNone(url)
        self.assertIn("already going", why)
        url, _ = self.decide(runs=[run("togi", "https://kick.com/togi/videos/x", status="in_progress")])
        self.assertEqual(url, V[0])  # Togi's run doesn't hold Lacy up

    def test_a_stream_with_a_run_is_never_started_again(self):
        url, _ = self.decide(runs=[run("lacy", V[0], status="completed")], queue=desk(0))
        self.assertEqual(url, V[1])

    def test_daily_cap_stops_a_loop(self):
        runs = [run("lacy", "https://www.twitch.tv/videos/%d" % n) for n in (1, 2, 3)]
        url, why = self.decide(runs=runs, queue=desk(0))
        self.assertIsNone(url)
        self.assertIn("daily cap", why)
        retries = [run("lacy", "https://www.twitch.tv/videos/%d" % n, opts="scout retry") for n in (1, 2, 3)]
        self.assertEqual(self.decide(runs=retries, queue=desk(0))[0], V[0])  # retries don't count

    def test_no_top_up_before_six_uk(self):
        url, why = self.decide(done={"300"}, queue=desk(0), now=dt.datetime(2026, 11, 27, 4, 0))
        self.assertIsNone(url)

    def test_an_old_untitled_run_counts_as_busy(self):
        url, _ = self.decide(runs=[{"displayTitle": "glue-run", "status": "in_progress", "createdAt": ""}])
        self.assertIsNone(url)

    def test_vod_ids_match_used_csv(self):
        self.assertEqual(S.vod_id("https://www.twitch.tv/videos/2937465519"), "2937465519")
        self.assertEqual(S.vod_id("https://kick.com/togi/videos/56264616-1e0a-4f5b-b7d8-7ceec211f624"),
                         "56264616-1e0a-4f5b-b7d8-7ceec211f624")

    def test_start_asks_for_a_scout_batch(self):
        got = []
        S.start("lacy", V[0], "new stream", dispatch=lambda: got.append(1))
        self.assertEqual(got, [1])
        self.assertEqual(S.FRESH, 8)

    def test_an_empty_twitch_answer_is_asked_again(self):
        # 26 Nov review: Twitch once answered "no streams" for Lacy on the runner, then fine a minute later
        from unittest import mock
        answers = [{}, {"user": {"videos": {"edges": [{"node": {"id": "300", "status": "RECORDED"}}]}}}]
        with mock.patch.object(S.I, "twitch_gql", lambda q: answers.pop(0)), mock.patch("time.sleep"):
            self.assertEqual(S.finished_vods(LACY), [V[0]])

    def test_glue_run_retries_once_then_tells_him(self):
        wf = (ROOT / ".github" / "workflows" / "glue-run.yml").read_text(encoding="utf-8")
        self.assertIn("run-name: clip ${{ inputs.campaign", wf)
        self.assertIn('options="$R_OPTIONS retry"', wf)
        self.assertIn('[ "${R_RETRY:-}" != yes ]', wf)
        self.assertIn("It failed twice", wf)
        sc = (ROOT / ".github" / "workflows" / "scout.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "37 */2 * * *"', sc)


if __name__ == "__main__":
    unittest.main()
