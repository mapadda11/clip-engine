"""One live progress message in his Telegram, edited every 30 s while a glue-run works (24 Nov, his ask).

    progress.py RUN_LOG DONE_FILE      (started in the background by glue-run.yml; stops when DONE_FILE appears)

Reads the PROGRESS lines run_vod.py prints (alfred-hq clips/bin/run_vod.py) and shows:
    Step 4/6: cutting windows   [######----] 58%   about 31 min left   moments found: 7
"""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import send_telegram as T  # noqa: E402

# (step name, share of the run where the step starts, where it ends)
STEPS = [("setting up the tools", 0, 10), ("reading chat and community clips", 10, 15),
         ("finding the best windows", 15, 25), ("cutting windows and captions", 25, 70),
         ("checking moments", 70, 85), ("rendering and sending", 85, 100)]
EVERY = 30


def state(log):
    """(step index 0-5, percent, moments found) from the run log text."""
    found = 0
    for m in re.finditer(r"found (\d+)", log):
        found = int(m.group(1))
    marks = [(i, m) for i, pat in ((5, r"PROGRESS render (\d+)/(\d+)"), (4, r"PROGRESS check (\d+)/(\d+)"),
                                    (3, r"PROGRESS window (\d+)/(\d+)")) for m in re.finditer(pat, log)]
    if marks:
        i, m = max(marks, key=lambda t: t[1].start())
        done, total = int(m.group(1)), max(1, int(m.group(2)))
    elif "Prescan kept" in log or "Crowd-only" in log:
        i, done, total = 2, 1, 1
    elif "Grades read" in log:
        i, done, total = 1, 0, 1
    else:
        i, done, total = 0, 0, 1
    a, b = STEPS[i][1:]
    return i, a + (b - a) * min(done, total) / total, found


def text(i, pct, found, elapsed):
    bar = "#" * int(pct // 10) + "-" * (10 - int(pct // 10))
    left = "working it out" if pct < 12 else "about %d min left" % max(1, round(elapsed * (100 - pct) / pct / 60))
    return "<b>Clip run</b>  Step %d/6: %s\n<code>[%s] %d%%</code>  %s\nMoments found: %d" % (
        i + 1, STEPS[i][0], bar, pct, left, found)


def main(log_path, done_path):
    t0, last = time.time(), None
    msg = T.send_text(text(0, 1, 0, 0))["result"]["message_id"]
    while not Path(done_path).exists() and time.time() - t0 < 6 * 3600:
        time.sleep(EVERY)
        log = Path(log_path).read_text(encoding="utf-8", errors="replace") if Path(log_path).exists() else ""
        i, pct, found = state(log)
        if i == 0:  # tool setup prints nothing; it takes about 10 min
            pct = min(9.0, (time.time() - t0) / 66)
        body = text(i, max(pct, 1), found, time.time() - t0)
        if body != last:
            try:
                T._call("editMessageText", {"chat_id": T.chat_id(), "message_id": msg, "text": body, "parse_mode": "HTML"})
                last = body
            except (Exception, SystemExit):  # noqa: BLE001 - a missed edit is fine; try again in 30 s
                pass
    try:
        T._call("editMessageText", {"chat_id": T.chat_id(), "message_id": msg, "parse_mode": "HTML",
                                    "text": "<b>Clip run</b> finished in %d min." % ((time.time() - t0) // 60)})
    except (Exception, SystemExit):  # noqa: BLE001
        pass


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
