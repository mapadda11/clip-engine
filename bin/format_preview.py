"""Layout previews for his formats from real footage (task 25 step 8a, 25 Nov 2026). Run by format-preview.yml.

    format_preview.py CAMPAIGN [VOD_LINK] [FORMATS]
1. The campaign streamer's newest finished stream (or the link), 4 minutes from 10 minutes in (yt-dlp sections).
2. alfred-hq clips/bin/preview.py renders a 1080x1920 still and a 4 s sample per format.
3. Each sample goes to his Telegram with "layout N ok" / "layout N: what to change"; the stills go to the private
   alfred-hq release "previews"; clips/formats/layouts.csv rows become "waiting" with the link (the ship shows them).
No clips are made here and nothing is posted.
"""
import base64
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
GLUE = Path(os.environ.get("ALFRED_HQ", "alfred-hq")) / "clips" / "bin"
sys.path.insert(0, str(GLUE))
import send_telegram as T  # noqa: E402
import telegram_inbox as I  # noqa: E402

REPO = "mapadda11/alfred-hq"
TAG = "previews"


def fetch(link, out):
    subprocess.run(["yt-dlp", "-q", "--no-warnings", "--download-sections", "*600-840", "-f", "best[height<=1080]/best",
                    "-o", str(out), link], check=True, timeout=1200)
    return out


def upload(files):
    if subprocess.run(["gh", "release", "view", TAG, "-R", REPO], capture_output=True).returncode:
        subprocess.run(["gh", "release", "create", TAG, "-R", REPO, "--title", TAG, "--notes",
                        "Format layout previews (task 25). Private."], check=True)
    subprocess.run(["gh", "release", "upload", TAG, "-R", REPO, "--clobber"] + [str(f) for f in files], check=True)


def mark_waiting(numbers, today):
    """layouts.csv rows -> waiting, with the preview link (contents API, ALFRED_HQ_TOKEN)."""
    import formatlab as FL
    url = "https://api.github.com/repos/%s/contents/%s" % (REPO, FL.FILE)
    head = {"Authorization": "Bearer " + os.environ["ALFRED_HQ_TOKEN"], "Accept": "application/vnd.github+json"}
    with urllib.request.urlopen(urllib.request.Request(url, headers=head), timeout=30) as r:
        cur = json.load(r)
    rows = FL.load(base64.b64decode(cur["content"]).decode("utf-8"))
    for row in rows:
        if row["format"] in ["his-%d" % n for n in numbers]:
            row.update(status="waiting", note="", updated=today,
                       preview="https://github.com/%s/releases/download/%s/%s.png" % (REPO, TAG, row["format"]))
    body = {"message": "Layout previews ready for his OK", "sha": cur["sha"],
            "content": base64.b64encode(FL.dump(rows).encode("utf-8")).decode()}
    urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(body).encode(), headers=head, method="PUT"),
                           timeout=30)


def main(argv):
    import datetime
    import preview as PV
    camp_name = argv[0] if argv else "togi"
    link = argv[1] if len(argv) > 1 and argv[1] else None
    numbers = [int(x) for x in (argv[2] if len(argv) > 2 and argv[2] else "1,2,3,4,5,6").split(",")]
    work = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "previews"
    work.mkdir(parents=True, exist_ok=True)
    if not link:
        camp = I.campaigns().get(camp_name)
        found = I.latest(camp) if camp else None
        if not found:
            T.send_text("Layout previews: I couldn't find %s's newest stream. Send: previews %s LINK" % (camp_name, camp_name))
            return 1
        link = found[0]
    src = fetch(link, work / "src.mp4")
    parkour = sorted(Path(os.environ.get("CLIP_GAMEPLAY_DIR", work / "gameplay")).glob("*.mp4"))
    files = []
    for n in numbers:
        png, mp4 = PV.render(n, src, work / "out", start=30.0, parkour=str(parkour[0]) if parkour else None)
        files += [png, mp4]
        T.send_video(mp4, "<b>Layout %d</b>: %s\nReply <code>layout %d ok</code> or <code>layout %d: what to change</code>."
                     "\nAudio: original only unless you pick one (<code>audio %d 1</code>)." % (
                         n, PV.FORMATS[n]["name"], n, n, n))
    upload(files)
    mark_waiting(numbers, datetime.date.today().isoformat())
    T.send_text("That's %d layout%s from %s. No clips are made in a format until you OK its layout." % (
        len(numbers), "" if len(numbers) == 1 else "s", link))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
