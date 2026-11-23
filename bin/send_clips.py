"""Send a finished run's clips to his Telegram, best first, each with its ready caption to copy.

    send_clips.py CLIPS_DIR [NOTE]
The glue names clips 01-…, 02-… in rank order and writes a .txt caption beside each. The full step 4
format (sound, YouTube title, hook ID) comes with step 4; this is the first version.
"""
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


def caption(i, n, cap, note="", tag=""):
    cap = cap.strip()
    rejected = cap.startswith("REJECTED:")
    head = "<b>%d/%d</b>%s%s" % (i, n, " · <b>REJECTED</b>" if rejected else "", (" · " + esc(note)) if note else "")
    grade = "\n<i>Grade it: reply \"%d: 7/10 your note\"</i> %s" % (i, esc(tag))
    return "%s%s\n\nCaption (tap to copy):\n<code>%s</code>" % (head, grade, esc(cap))


def main(folder, note="", top=0):
    clips = sorted(Path(folder).rglob("*.mp4"), key=lambda p: p.name)
    clips = clips[:top] if top else clips  # names start 01-, 02-, ... in rank order
    if not clips:
        T.send_text("The run finished but no clips passed the filters this time.")
        return
    for i, mp4 in enumerate(clips, 1):
        txt = mp4.with_suffix(".txt")
        T.send_video(mp4, caption(i, len(clips), txt.read_text(encoding="utf-8") if txt.exists() else "", note, tags(mp4)))
    if "practice" in note or "test" in note:
        T.send_text("That's all %d. These are test clips: tell me what you think, but don't post them yet." % len(clips))
    else:
        T.send_text("That's all %d. Post, then submit on Content Rewards within 30 min." % len(clips))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "", int(sys.argv[3]) if len(sys.argv) > 3 else 0)
