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


def caption(i, n, cap, note=""):
    head = "<b>%d/%d</b>%s" % (i, n, (" · " + esc(note)) if note else "")
    return "%s\n\nCaption (tap to copy):\n<code>%s</code>" % (head, esc(cap.strip()))


def main(folder, note="", top=0):
    clips = sorted(Path(folder).rglob("*.mp4"), key=lambda p: p.name)
    clips = clips[:top] if top else clips  # names start 01-, 02-, ... in rank order
    if not clips:
        T.send_text("The run finished but no clips passed the filters this time.")
        return
    for i, mp4 in enumerate(clips, 1):
        txt = mp4.with_suffix(".txt")
        T.send_video(mp4, caption(i, len(clips), txt.read_text(encoding="utf-8") if txt.exists() else "", note))
    if "practice" in note or "test" in note:
        T.send_text("That's all %d. These are test clips: tell me what you think, but don't post them yet." % len(clips))
    else:
        T.send_text("That's all %d. Post, then submit on Content Rewards within 30 min." % len(clips))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "", int(sys.argv[3]) if len(sys.argv) > 3 else 0)
