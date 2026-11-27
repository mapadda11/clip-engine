"""Guards for faults that must never come back (alfred-hq clips/lessons.md, task 25, 25 Nov 2026).

    python -m unittest discover -s tests
Plain standard library; no Telegram, GitHub or alfred-hq checkout needed (fakes stand in).
"""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:" + "a" * 35)
os.environ.setdefault("TELEGRAM_CHAT_ID", "123456")
import send_clips as S  # noqa: E402
import send_telegram as T  # noqa: E402

GLUE = (ROOT / ".github" / "workflows" / "glue-run.yml").read_text(encoding="utf-8")


class GuardsTest(unittest.TestCase):
    def test_failure_message_also_runs_when_cancelled(self):  # lesson 2
        self.assertIn("if: (failure() || cancelled())", GLUE)

    def test_parkour_only_when_the_recipe_says_so(self):  # 25 Nov night: a Lacy clip got Fortnite parkour
        step = GLUE.split("His parkour gameplay", 1)[1].split("- name:", 1)[0]
        self.assertIn("grep -E '^bottom:'", step)
        self.assertIn('[ "$bottom" = parkour ]', step)
        self.assertNotIn("R_FORMAT", step)  # a format: option can never fetch parkour
        self.assertNotIn("^format:", step)

    def test_long_caption_moves_to_its_own_message(self):  # lesson 3
        head, rest = S.parts(1, 3, "hook line\n" + "word " * 400, "ready to post", "[run=1 no=1]")
        self.assertLessEqual(len(head), T.CAPTION_MAX)
        self.assertEqual(head.count("<code>"), head.count("</code>"))  # never cut through a tag
        self.assertNotIn("word word", head)
        self.assertTrue(rest.startswith("Caption for 1") and rest.rstrip().endswith("</code>"))

    def test_one_message_per_batch_never_one_per_clip(self):  # lesson 4, corrected 26 Nov (his clean slate)
        d = Path(tempfile.mkdtemp())
        for name in ("01-a", "02-b", "03-c"):
            (d / (name + ".mp4")).write_bytes(b"x")
            (d / (name + ".txt")).write_text("a hook\ncaption", encoding="utf-8")
        (d / "03-c.txt").write_text("REJECTED: no payoff\ncaption", encoding="utf-8")
        (d / "claude-check.json").write_text(
            '{"clips": [{"file": "01-a.mp4", "score": 4, "keep": true, "why": "fine, forgettable"},'
            ' {"file": "02-b.mp4", "score": 9, "keep": false, "why": "Nudity: Lucia in the shower at 6 s."}]}',
            encoding="utf-8")
        sent, queued = [], []
        fake = types.SimpleNamespace(batch_text=lambda b: "%d new clips (1 to %d) ready in the Clip Desk\nhttps://x/desk.html"
                                     % (len(b), len(b)))
        old = (T.send_video, T.send_text, S.queue, sys.modules.get("approvals"), os.environ.pop("HOLD", None))
        T.send_video = lambda p, c: sent.append(("video", c))
        T.send_text = lambda t: sent.append(("text", t))
        S.queue = lambda rows, finish=(): (queued.extend(rows) or [{"num": "1"}], "")
        sys.modules["approvals"] = fake
        try:
            S.main(str(d), "ready to post")
        finally:
            T.send_video, T.send_text, S.queue = old[0], old[1], old[2]
            sys.modules.pop("approvals", None)
            if old[3] is not None:
                sys.modules["approvals"] = old[3]
        self.assertEqual([k for k, _ in sent], ["text"])  # one message for the batch, no clip videos
        self.assertIn("1 new clips (1 to 1) ready in the Clip Desk", sent[0][1])
        self.assertEqual([r[3] for r in queued], ["01-a.mp4", "02-b.mp4"])  # the engine's REJECTED clip never queued
        self.assertEqual(queued[0][1]["claude_score"], 4)
        self.assertTrue(queued[1][1].get("claude_reject"))  # Claude's keep = false (his Lacy rules) = rejected
        self.assertIn('hold) echo "R_HOLD=yes"', GLUE)  # one batch across several VOD runs (batch-finish.yml)
        self.assertIn("env.R_PROGRESS == 'yes'", GLUE)  # no live progress message unless asked for

    def test_every_run_has_a_backup_release(self):  # lesson 5
        self.assertIn('[ -n "$release" ] || release="${R_CAMPAIGN:-test}-', GLUE)

    def test_stall_warning_after_20_minutes(self):  # lesson 6
        import progress
        self.assertEqual(progress.STALL, 20 * 60)

    def test_unknown_words_reach_crew_cmds(self):  # lesson 8
        import telegram_inbox as I
        fake_grades = types.SimpleNamespace(parse=lambda t: None)
        fake_crew = types.SimpleNamespace(reply=lambda text, replied_to, call=None: "crew got: " + text)
        old = {k: sys.modules.get(k) for k in ("grades", "crew_cmds")}
        sys.modules["grades"], sys.modules["crew_cmds"] = fake_grades, fake_crew
        try:
            self.assertEqual(I.reply_for("views 3 1240"), "crew got: views 3 1240")
            self.assertEqual(I.reply_for("ok 3"), "crew got: ok 3")
        finally:
            for k, v in old.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    def test_previews_start_the_preview_job_not_a_clip_run(self):  # task 25 step 8a
        import telegram_inbox as I
        started = []
        out = I.do_previews(["togi", "5,6"], start=lambda: started.append(1))
        self.assertEqual(started, [1])
        self.assertIn("formats 5,6", out)
        wf = (ROOT / ".github" / "workflows" / "format-preview.yml").read_text(encoding="utf-8")
        self.assertNotIn("schedule:", wf)
        self.assertNotIn("${{ inputs.vod_url }}\"", wf)  # inputs go through env, never inline in a shell line

    def test_youtube_links_go_to_his_pc_with_their_case_kept(self):  # task 25 step 7
        import telegram_inbox as I
        camps = {"togi": {"title": "Togi", "labels": ["campaign:joined"], "state": "OPEN", "ready": False,
                          "channel": "togi", "any_streamer": False}}
        sent = []
        out = I.do_clip(["https://youtu.be/abcdef", "togi", "5"], camps=camps, start=sent.append,
                        raw=["https://youtu.be/AbCdEf", "togi", "5"])
        self.assertIn("Sent to your PC: 5 clips", out)
        self.assertEqual(sent[0]["inputs"]["vod_url"], "https://youtu.be/AbCdEf")
        self.assertEqual(sent[0]["inputs"]["campaign"], "togi")

    def test_each_run_has_its_own_concurrency_group(self):  # lesson 13
        self.assertIn("group: glue-run-${{ github.run_id }}", GLUE)
        self.assertNotIn("group: glue-run-${{ inputs.vod_url }}", GLUE)

    def test_no_clip_run_starts_on_a_timer(self):  # task 25 step 1
        # Correction (2026-11-26, his step 2 "clips arrive on their own"): the Scout (scout.yml, every 2 h) may start
        # clip runs too; glue-run itself still never has a timer, and nothing ever posts.
        for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
            text = wf.read_text(encoding="utf-8")
            if "schedule:" in text:
                self.assertIn(wf.name, ("telegram-inbox.yml", "scout.yml"), "only the message reader and the Scout may have a timer")


if __name__ == "__main__":
    unittest.main()


class EveryClipSentTest(unittest.TestCase):  # alfred-hq clips/lessons.md 48 (27 Nov, his fix)
    def test_every_batch_ends_by_sending_every_clip(self):
        step = GLUE.split("Send every clip to Telegram (Python, no Claude)")[1].split("- name:")[0]
        self.assertIn("deliver.py --runs \"$GITHUB_RUN_ID\"", step)
        self.assertIn("env.R_HOLD != 'yes'", step)  # a held run sends from batch-finish instead
        self.assertLess(GLUE.index("bin/send_clips.py \"$WORK/out\""), GLUE.index("deliver.py --runs"))
        fin = (ROOT / ".github" / "workflows" / "batch-finish.yml").read_text(encoding="utf-8")
        self.assertIn("deliver.py --runs \"$RUNS\"", fin)


class OneClaudePerBatchTest(unittest.TestCase):  # 27 Nov, his step 4
    def test_claude_runs_once_per_batch_in_20_turns_from_context_md(self):
        self.assertEqual(GLUE.count("claude -p"), 1)
        self.assertIn("--max-turns 20", GLUE)
        self.assertIn("context.py --batch", GLUE)
        self.assertLess(GLUE.index("alfred-hq/clips/bin/context.py"), GLUE.index("claude -p"))
