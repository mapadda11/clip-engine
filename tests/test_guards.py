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

    def test_long_caption_moves_to_its_own_message(self):  # lesson 3
        head, rest = S.parts(1, 3, "hook line\n" + "word " * 400, "ready to post", "[run=1 no=1]")
        self.assertLessEqual(len(head), T.CAPTION_MAX)
        self.assertEqual(head.count("<code>"), head.count("</code>"))  # never cut through a tag
        self.assertNotIn("word word", head)
        self.assertTrue(rest.startswith("Caption for 1") and rest.rstrip().endswith("</code>"))

    def test_last_message_says_sent_x_of_y(self):  # lesson 4
        d = Path(tempfile.mkdtemp())
        for name in ("01-a", "02-b"):
            (d / (name + ".mp4")).write_bytes(b"x")
            (d / (name + ".txt")).write_text("a hook\ncaption", encoding="utf-8")
        sent = []
        old = (T.send_video, T.send_text, os.environ.pop("ALFRED_HQ_TOKEN", None))
        T.send_video, T.send_text = (lambda p, c: sent.append(c)), (lambda t: sent.append(t))
        try:
            S.main(str(d), "ready to post")
        finally:
            T.send_video, T.send_text = old[0], old[1]
        self.assertIn("Sent 2 of 2 clips.", sent[-1])
        self.assertIn("Nothing is posted until you say ok", sent[-1])
        self.assertIn("reply <code>ok 1</code>", sent[0])

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
        for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
            text = wf.read_text(encoding="utf-8")
            if "schedule:" in text:
                self.assertEqual(wf.name, "telegram-inbox.yml", "only the message reader may have a timer")


if __name__ == "__main__":
    unittest.main()
