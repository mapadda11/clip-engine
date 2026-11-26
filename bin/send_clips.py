"""Send a finished run's clips to his Telegram, best first, each with its ready caption to copy.

    send_clips.py CLIPS_DIR [NOTE]
The glue names clips 01-…, 02-… in rank order and writes a .txt caption beside each. The full step 4
format (sound, YouTube title, hook ID) comes with step 4; this is the first version.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import send_telegram as T  # noqa: E402


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tags(mp4, no=None):
    """[kind=... hook=... run=... no=...] from the clip's side file: a reply to this message carries them into his
    grade, and (task 25) into "ok" / "no why" for exactly this clip."""
    import json
    import os
    side = mp4.with_name(mp4.stem + ".clip.json")
    try:
        d = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
    except ValueError:
        d = {}
    t = {"kind": d.get("kind"), "hook": d.get("hook_id"), "run": os.environ.get("GITHUB_RUN_ID"), "no": no}
    return "[%s]" % " ".join("%s=%s" % (k, v) for k, v in t.items() if v)


def side(mp4):
    f = mp4.with_name(mp4.stem + ".clip.json")
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except ValueError:
        return {}


def why(d):
    """Task 17: one line of why, e.g. 'viewer 8/10, crowd 4.1, +18 dB, dead 4%'."""
    if not d.get("rule_score"):
        return ""
    g = d.get("gate") or {}
    return "viewer %s/10, crowd %.1f, %+.0f dB, dead %.0f%%%s" % (
        d.get("viewer_score") or d["rule_score"], float(d.get("crowd") or 0), float(d.get("payoff_db") or 0),
        100 * float(g.get("dead_share") or 0), ", %s views on the source clip" % d["source_views"] if d.get("source_views") else "")


def caption(i, n, cap, note="", tag="", line=""):
    cap = cap.strip()
    rejected = cap.startswith("REJECTED:")
    head = "<b>%d/%d</b>%s%s" % (i, n, " · <b>REJECTED</b>" if rejected else "", (" · " + esc(note)) if note else "")
    head += ("\n" + esc(line)) if line else ""
    ask = "" if rejected else "\n<b>Waiting for your OK</b>: reply <code>ok %d</code> or <code>no %d why</code>" % (i, i)
    grade = ask + "\n<i>Grade it: \"%d: 7/10 your note\"</i> %s" % (i, esc(tag))
    return "%s%s\n\nCaption (tap to copy):\n<code>%s</code>" % (head, grade, esc(cap))


def parts(i, n, cap, note="", tag="", line=""):
    """(video caption, follow-up text or ""). 25 Nov: Telegram's 1,024 limit used to be met by cutting the HTML
    anywhere, which could cut through <code> and make Telegram refuse the clip; now the copy-caption moves to
    its own message instead."""
    full = caption(i, n, cap, note, tag, line)
    if len(full) <= T.CAPTION_MAX:
        return full, ""
    head = full[:full.index("\n\nCaption (tap to copy):")]
    if len(head) > T.CAPTION_MAX:
        head = "<b>%d/%d</b> %s" % (i, n, esc(tag))
    return head, "Caption for %d (tap to copy):\n<code>%s</code>" % (i, esc(cap.strip()))


def claude_notes(folder):
    """{clip file name: verdict} from the Claude check of the top 5 (claude-check.json), when it ran."""
    try:
        d = json.loads((Path(folder) / "claude-check.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for c in d.get("clips", []) if isinstance(d, dict) else []:
        if isinstance(c, dict) and c.get("file"):
            out[Path(str(c["file"])).name] = c
    return out


def hook_ideas(v):
    """The Hook Writer's ideas minus any with AI tells (task 25; alfred-hq clips/bin/humanize.py).
    Correction (2026-11-26 evening, his step 3): 2 variants per clip (was 3), both shown on the Clip Desk."""
    hooks = [str(h)[:90] for h in ((v or {}).get("hooks") or [])[:2]]
    try:
        sys.path.insert(0, str(Path(os.environ.get("ALFRED_HQ", "alfred-hq")) / "clips" / "bin"))
        import humanize
        return humanize.keep(hooks)
    except ImportError:
        return hooks


def claude_line(v):
    if not v:
        return ""
    s = "Claude: %s/10%s" % (v.get("score", "?"), (", " + str(v["why"])[:140]) if v.get("why") else "")
    hooks = hook_ideas(v)
    return s + ("\nHook ideas (reply hook N 2 to use one): " + " | ".join("%d) %s" % (k, h) for k, h in enumerate(hooks, 1))
                if hooks else "")



def summary(folder):
    """run_vod's one-message run summary (run-summary.txt), or ""."""
    try:
        return (Path(folder) / "run-summary.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def reasons(folder):
    """The run log's summary lines (windows found, skips, gate rejects), so an empty batch explains itself."""
    log = Path(folder) / "run.log"
    keep = ("Community clips:", "Skipped ", "Gate rejects:", "No new moments", "Every window failed", "Refusing")
    try:
        lines = [l.strip() for l in log.read_text(encoding="utf-8", errors="replace").splitlines() if l.startswith(keep)]
    except OSError:
        return "Why: the run log is missing; open the run on GitHub."
    return "Why:\n" + "\n".join("- " + l[:160] for l in lines[-6:]) if lines else "Why: nothing in the log; open the run on GitHub."


def glue():
    """alfred-hq's clips/bin/approvals.py (the queue and the batch ranking)."""
    sys.path.insert(0, str(Path(os.environ.get("ALFRED_HQ", "alfred-hq")) / "clips" / "bin"))
    import approvals
    return approvals


def candidates(folder, top=0):
    """The run's clips for the desk, best first: Viewer bar, SEND_TOP, and no engine REJECTED clips."""
    clips = sorted(Path(folder).rglob("*.mp4"), key=lambda p: p.name)
    bar = float(os.environ.get("MIN_SCORE") or 0)
    if bar:  # task 17: only clips the Viewer's free twin scores at the bar or above
        clips = [c for c in clips if float(side(c).get("rule_score") or 0) >= bar]
    clips = clips[:top] if top else clips  # names start 01-, 02-, ... in rank order
    out = []
    for mp4 in clips:
        txt = mp4.with_suffix(".txt")
        cap = txt.read_text(encoding="utf-8") if txt.exists() else ""
        if not cap.strip().startswith("REJECTED:") and not side(mp4).get("rejected"):
            out.append((mp4, cap))
    return out


def desk_rows(folder, top=0):
    """[(no, side + Claude's verdict, caption, file name)] for approvals.rows_for. Claude's score and one-line why
    rank the batch; keep = false (his Lacy rules: nudity, no payoff, no sound, dead start...) = rejected."""
    checked = claude_notes(folder)
    out = []
    for i, (mp4, cap) in enumerate(candidates(folder, top), 1):
        v = checked.get(mp4.name) or {}
        d = dict(side(mp4), hook_ideas=hook_ideas(v))
        if v.get("score") not in (None, ""):
            d["claude_score"] = v["score"]
        d["claude_why"] = str(v.get("why") or "") or why(side(mp4))
        if v.get("keep") is False:
            d["claude_reject"] = True
        out.append((i, d, cap, mp4.name))
    return out, bool(checked)


def main(folder, note="", top=0):
    """26 Nov 2026 (his clean slate): one Telegram message per batch, never one per clip. Every clip goes on the
    alfred-hq queue; the batch is ranked by the Claude check's score (best 15 new, the rest "low", numbered best
    first) and one message says "N new clips (X to Y) ready in the Clip Desk" with the link.
    HOLD=yes (glue-run option hold): this run is one part of a bigger batch (several VODs): queue only, no message;
    `send_clips.py --finish RUN,RUN` ranks that batch and sends its one message."""
    rows, checked = desk_rows(folder, top)
    hold = os.environ.get("HOLD") == "yes"
    run = os.environ.get("GITHUB_RUN_ID", "0")
    if not rows:  # task 17: a run that finds nothing says why, in one message
        if hold:
            print("no clips for the desk from this run")
            return 0
        T.send_text("The run finished but no clips passed this time.\n" + (esc(summary(folder)) or reasons(folder)))
        return 0
    batch, err = queue(rows, finish=() if hold else (run,))
    if hold:
        print("%d clips held for the batch (%s)" % (len(rows), err or "queued"))
        return 1 if err else 0
    return send_batch(batch, err, checked)


def send_batch(batch, err="", checked=True):
    """The batch's one message (approvals.batch_text), or why the desk didn't get it."""
    if err:
        T.send_text("A clip batch was made but the Clip Desk didn't save it: %s" % esc(err))
        return 1
    text = esc(glue().batch_text(batch))
    if not checked:
        text += "\n(Claude check didn't run, so scores are the engine's own.)"
    T.send_text(text)
    return 0


def finish(runs):
    """--finish RUN,RUN: rank the held runs as one batch and send its one message."""
    runs = [r for r in runs.replace(" ", ",").split(",") if r.strip()]
    batch, err = queue([], finish=runs)
    if not batch and not err:
        T.send_text("No clips came out of runs %s, sir. Open them on GitHub to see why." % ", ".join(runs))
        return 0
    return send_batch(batch, err)


def queue(sent, finish=()):
    """Task 25: a row per clip in alfred-hq clips/queue.csv (its clips/bin/approvals.py).
    26 Nov: rows arrive pending; finish = the runs to rank as one batch in the same write. Returns (batch, error)."""
    tok = os.environ.get("ALFRED_HQ_TOKEN", "")
    if not tok:
        return [], "no ALFRED_HQ_TOKEN in clip-engine"
    try:
        import datetime
        A = glue()
        rows = A.rows_for(sent, os.environ.get("GITHUB_RUN_ID", "0"), os.environ.get("R_RELEASE", ""),
                          datetime.date.today().isoformat(), os.environ.get("R_CAMPAIGN", ""),
                          os.environ.get("R_FORMAT", "")) if sent else []
        return A.push(rows, tok, finish_runs=tuple(finish)) or [], ""
    except (Exception, SystemExit) as e:  # noqa: BLE001 - say so in the one message instead of going quiet
        print("queue not saved: %s" % str(e)[:200])
        return [], str(e)[:160]


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--finish":
        sys.exit(finish(sys.argv[2]))
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "", int(sys.argv[3]) if len(sys.argv) > 3 else 0))
