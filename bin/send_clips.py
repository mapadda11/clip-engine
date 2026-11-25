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


def tags(mp4):
    """[kind=... hook=... run=...] from the clip's side file: a reply to this message carries them into his grade."""
    import json
    import os
    side = mp4.with_name(mp4.stem + ".clip.json")
    try:
        d = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
    except ValueError:
        d = {}
    t = {"kind": d.get("kind"), "hook": d.get("hook_id"), "run": os.environ.get("GITHUB_RUN_ID")}
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
    grade = "\n<i>Grade it: reply \"%d: 7/10 your note\"</i> %s" % (i, esc(tag))
    return "%s%s\n\nCaption (tap to copy):\n<code>%s</code>" % (head, grade, esc(cap))


def reasons(folder):
    """The run log's summary lines (windows found, skips, gate rejects), so an empty batch explains itself."""
    log = Path(folder) / "run.log"
    keep = ("Community clips:", "Skipped ", "Gate rejects:", "No new moments", "Every window failed", "Refusing")
    try:
        lines = [l.strip() for l in log.read_text(encoding="utf-8", errors="replace").splitlines() if l.startswith(keep)]
    except OSError:
        return "Why: the run log is missing; open the run on GitHub."
    return "Why:\n" + "\n".join("- " + l[:160] for l in lines[-6:]) if lines else "Why: nothing in the log; open the run on GitHub."


def main(folder, note="", top=0):
    clips = sorted(Path(folder).rglob("*.mp4"), key=lambda p: p.name)
    made = clips
    bar = float(os.environ.get("MIN_SCORE") or 0)
    if bar:  # task 17: only clips the Viewer's free twin scores at the bar or above (rejects still go in grade mode)
        keep = [c for c in clips if side(c).get("rejected") or float(side(c).get("rule_score") or 0) >= bar]
        print("Viewer bar %.1f: %d of %d clips pass" % (bar, len(keep), len(clips)))
        clips = keep
    clips = clips[:top] if top else clips  # names start 01-, 02-, ... in rank order
    if not clips:  # task 17: a run that finds nothing says why, in one message
        scores = ", ".join("%.1f" % float(side(c).get("rule_score") or 0) for c in made)
        under = ("%d clip%s made, Viewer scores %s, all under the bar %.1f.\n" % (len(made), "" if len(made) == 1 else "s", scores, bar)
                 if made and bar else "")
        T.send_text("The run finished but no clips passed this time.\n" + under + reasons(folder))
        return
    failed = []
    for i, mp4 in enumerate(clips, 1):
        txt = mp4.with_suffix(".txt")
        try:
            T.send_video(mp4, caption(i, len(clips), txt.read_text(encoding="utf-8") if txt.exists() else "", note, tags(mp4),
                                      why(side(mp4))))
        except (Exception, SystemExit) as e:  # noqa: BLE001 - one bad clip must not stop the rest of the batch
            failed.append(i)
            print("clip %d not sent: %s" % (i, str(e)[:200]))
    if failed:
        T.send_text("Clip%s %s couldn't be sent (see the run log)." % ("s" if len(failed) > 1 else "",
                                                                     ", ".join(map(str, failed))))
    if "practice" in note or "test" in note:
        T.send_text("That's all %d. These are test clips: tell me what you think, but don't post them yet." % len(clips))
    else:
        T.send_text("That's all %d. Post, then submit on Content Rewards within 30 min." % len(clips))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "", int(sys.argv[3]) if len(sys.argv) > 3 else 0)
