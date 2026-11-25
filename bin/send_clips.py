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


def claude_line(v):
    if not v:
        return ""
    s = "Claude: %s/10%s" % (v.get("score", "?"), (", " + str(v["why"])[:140]) if v.get("why") else "")
    hooks = [str(h)[:90] for h in (v.get("hooks") or [])[:3]]
    return s + ("\nHook ideas: " + " | ".join(hooks) if hooks else "")


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


def main(folder, note="", top=0):
    clips = sorted(Path(folder).rglob("*.mp4"), key=lambda p: p.name)
    made = clips
    bar = float(os.environ.get("MIN_SCORE") or 0)
    under = 0
    if bar:  # task 17: only clips the Viewer's free twin scores at the bar or above (rejects still go in grade mode)
        keep = [c for c in clips if side(c).get("rejected") or float(side(c).get("rule_score") or 0) >= bar]
        under = len(clips) - len(keep)
        print("Viewer bar %.1f: %d of %d clips pass" % (bar, len(keep), len(clips)))
        clips = keep
    clips = clips[:top] if top else clips  # names start 01-, 02-, ... in rank order
    checked = claude_notes(folder)
    if checked:  # 25 Nov (his C + light B): clips Claude says to skip go last, still sent, labelled
        clips = sorted(clips, key=lambda c: bool(checked.get(c.name, {}).get("keep") is False))
    backup = os.environ.get("BACKUP_NOTE", "")
    if not clips:  # task 17: a run that finds nothing says why, in one message
        scores = ", ".join("%.1f" % float(side(c).get("rule_score") or 0) for c in made)
        why_none = ("%d clip%s made, Viewer scores %s, all under the bar %.1f.\n" % (len(made), "" if len(made) == 1 else "s", scores, bar)
                    if made and bar else "")
        T.send_text("The run finished but no clips passed this time.\n" + why_none + (esc(summary(folder)) or reasons(folder)))
        return 0
    failed, queued = [], []
    for i, mp4 in enumerate(clips, 1):
        txt = mp4.with_suffix(".txt")
        v = checked.get(mp4.name)
        line = "\n".join(x for x in (why(side(mp4)), claude_line(v)) if x)
        if v and v.get("keep") is False:
            line = "Claude says skip this one. " + line
        cap = txt.read_text(encoding="utf-8") if txt.exists() else ""
        head, rest = parts(i, len(clips), cap, note, tags(mp4, i), line)
        try:
            T.send_video(mp4, head)
            if rest:
                T.send_text(rest)
            if not cap.strip().startswith("REJECTED:"):
                queued.append((i, side(mp4), cap, mp4.name))
        except (Exception, SystemExit) as e:  # noqa: BLE001 - one bad clip must not stop the rest of the batch
            failed.append(i)
            print("clip %d not sent: %s" % (i, str(e)[:200]))
    sent = len(clips) - len(failed)
    qnote = queue(queued)
    end = ["Sent %d of %d clip%s." % (sent, len(clips), "" if len(clips) == 1 else "s")]
    if under:
        end.append("%d more were made but scored under the Viewer bar %.0f (they're in the backup)." % (under, bar))
    if failed:
        end.append("Not sent: %s (Telegram refused them; they're in the backup)." % ", ".join(map(str, failed)))
    if backup:
        end.append(backup)
    if not checked:
        end.append("Claude check of the top 5: didn't run (no CLAUDE_CODE_OAUTH_TOKEN in clip-engine, or it failed).")
    if "practice" in note or "test" in note:
        end.append("These are test clips: tell me what you think, but don't post them yet.")
    end.append("Nothing is posted until you say ok. ok clips go on the Ready list on the ship." + qnote)
    s = summary(folder)
    T.send_text("\n".join(esc(x) for x in end) + ("\n\n" + esc(s) if s else ""))
    return 1 if failed and not sent else 0


def queue(sent):
    """Task 25: a waiting row per sent clip in alfred-hq clips/queue.csv (its clips/bin/approvals.py). Returns a note."""
    tok = os.environ.get("ALFRED_HQ_TOKEN", "")
    if not sent:
        return ""
    if not tok:
        return " (Not on the waiting list: no ALFRED_HQ_TOKEN.)"
    try:
        import datetime
        sys.path.insert(0, str(Path(os.environ.get("ALFRED_HQ", "alfred-hq")) / "clips" / "bin"))
        import approvals as A
        rows = A.rows_for(sent, os.environ.get("GITHUB_RUN_ID", "0"), os.environ.get("R_RELEASE", ""),
                          datetime.date.today().isoformat(), os.environ.get("R_CAMPAIGN", ""), os.environ.get("R_FORMAT", ""))
        A.push(rows, tok)
        return ""
    except (Exception, SystemExit) as e:  # noqa: BLE001 - the clips are already sent; just say the list missed them
        print("queue not saved: %s" % str(e)[:200])
        return " (The waiting list didn't save this time, so ok/no for this batch may not find the clips.)"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "", int(sys.argv[3]) if len(sys.argv) > 3 else 0))
