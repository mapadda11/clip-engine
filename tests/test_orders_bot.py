"""Task 25 step 8b on the bot: plain words -> plan -> his ok -> a run; standing orders tick (bin/orders_bot.py).
Needs the alfred-hq checkout next to clip-engine (its clips/bin); skipped where that private repo isn't there."""
import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HQ = Path(os.environ.get("ALFRED_HQ", ROOT.parent / "alfred-hq"))
os.environ["ALFRED_HQ"] = str(HQ)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:" + "a" * 35)
os.environ.setdefault("TELEGRAM_CHAT_ID", "123456")
sys.path.insert(0, str(ROOT / "bin"))
HAVE = (HQ / "clips" / "bin" / "orders.py").exists()

CAMPS = {"togi": {"title": "Togi", "channel": "togi", "platform": "kick", "ready": False, "labels": ["campaign:joined"],
                  "state": "OPEN", "any_streamer": False}}
NOW = dt.datetime(2026, 11, 26, 18, 0)


@unittest.skipUnless(HAVE, "needs the alfred-hq checkout")
class OrdersBotTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(HQ / "clips" / "bin"))
        import crew_cmds
        import orders_bot
        self.B = orders_bot
        self.root = Path(tempfile.mkdtemp())
        self.repo = crew_cmds.Repo(root=self.root)
        self.started = []

    def say(self, text, mins=0):
        return self.B.reply(text, self.repo, NOW + dt.timedelta(minutes=mins), dispatch=lambda: self.started.append(1),
                            camps=CAMPS)

    def test_plan_waits_for_ok_then_runs_once(self):
        import telegram_inbox as I
        old = I.latest
        I.latest = lambda camp, *a: ("https://kick.com/togi/videos/x", "t")
        try:
            self.assertIn("Reply <code>ok</code>", self.say("make 5 togi clips from his latest stream"))
            self.assertEqual(self.started, [])
            self.assertIn("making 5 togi clips", self.say("ok", 3))
            self.assertEqual(self.started, [1])
            self.assertIsNone(self.say("ok", 4))  # nothing left to OK: "ok" falls through
        finally:
            I.latest = old

    def test_unbuilt_formats_are_refused_kindly(self):
        self.say("make 5 togi clips in format 6")
        self.assertIn("isn't built yet", self.say("ok", 1))
        self.assertEqual(self.started, [])

    def test_standing_order_ticks_only_when_short_and_idle(self):
        self.say("keep making togi clips, 20 a day")
        self.assertIn("is on", self.say("ok", 1))
        import telegram_inbox as I
        old = I.latest
        I.latest = lambda camp, *a: ("https://kick.com/togi/videos/x", "t")
        sent = []
        try:
            p = self.root / "clips" / "orders.csv"
            self.assertIsNone(self.B.tick(busy=lambda: True, dispatch=lambda: None, camps=CAMPS, path=p, now=NOW, send=sent.append))
            out = self.B.tick(busy=lambda: False, dispatch=lambda: self.started.append(1), camps=CAMPS, path=p, now=NOW,
                              send=sent.append)
            self.assertIn("making 10 togi clips", out)
            self.assertEqual(len(sent), 1)
            self.assertIn("paused", self.say("pause 1", 2))
            self.assertIsNone(self.B.tick(busy=lambda: False, dispatch=lambda: None, camps=CAMPS, path=p, now=NOW, send=sent.append))
        finally:
            I.latest = old


class WiringTest(unittest.TestCase):
    def test_stop_with_a_number_is_an_order_and_the_tick_never_blocks_messages(self):
        src = (ROOT / "bin" / "telegram_inbox.py").read_text(encoding="utf-8")
        self.assertIn('if cmd == "stop" and len(words) == 1:', src)
        self.assertIn("orders_bot.tick()", src)
        self.assertIn('print("orders tick: %s"', src)
        wf = (ROOT / ".github" / "workflows" / "plain-words.yml").read_text(encoding="utf-8")
        self.assertNotIn("schedule:", wf)
        self.assertIn("TEXT: ${{ inputs.text }}", wf)  # his words via env, never inline in a shell line


if __name__ == "__main__":
    unittest.main()
