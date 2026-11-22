"""Send clips to his private Telegram chat. Python stdlib only (urllib, hand-built multipart).

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from the environment (Actions secrets); never prints them.
  send_telegram.py test                      one "Clip robot connected" message
  send_telegram.py text "message"            one text message
  send_telegram.py video FILE CAPTION_FILE   one video with its caption (HTML) underneath
Bots can upload at most 50 MB per file, so bigger videos are re-encoded first (see fit()).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

API = "https://api.telegram.org/bot%s/%s"
LIMIT = 49 * 1024 * 1024  # a little under the 50 MB bot upload cap
CAPTION_MAX = 1024        # Telegram's caption limit; longer text goes in a follow-up message


def _call(method, fields=None, files=None, tries=4):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    fields = {k: str(v) for k, v in (fields or {}).items()}
    if files:
        boundary = uuid.uuid4().hex
        body = b""
        for k, v in fields.items():
            body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode()
        for k, path in files.items():
            body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                     "Content-Type: video/mp4\r\n\r\n" % (boundary, k, Path(path).name)).encode()
            body += Path(path).read_bytes() + b"\r\n"
        body += ("--%s--\r\n" % boundary).encode()
        ctype = "multipart/form-data; boundary=%s" % boundary
    else:
        body = json.dumps(fields).encode()
        ctype = "application/json"
    for attempt in range(tries):
        req = urllib.request.Request(API % (token, method), data=body, headers={"Content-Type": ctype})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            info = json.loads(e.read() or b"{}")
            wait = (info.get("parameters") or {}).get("retry_after")
            if e.code == 429 and wait and attempt < tries - 1:  # flood limit: wait as told
                time.sleep(int(wait) + 1)
                continue
            raise SystemExit("Telegram %s failed: %s %s" % (method, e.code, info.get("description", "")))
        except urllib.error.URLError:
            if attempt == tries - 1:
                raise
            time.sleep(5 * (attempt + 1))


def fit(path):
    """The video itself if it is under the limit, else a smaller copy (same length, lower bitrate)."""
    path = Path(path)
    if path.stat().st_size <= LIMIT:
        return path
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(path)], capture_output=True, text=True).stdout or 30)
    kbps = int(LIMIT * 8 / 1000 / dur * 0.9) - 160
    out = Path(tempfile.mkdtemp()) / path.name
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path), "-c:v", "libx264", "-preset", "medium",
                    "-b:v", "%dk" % kbps, "-maxrate", "%dk" % kbps, "-bufsize", "%dk" % (2 * kbps),
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)], check=True)
    return out


def send_text(text, chat=None):
    return _call("sendMessage", {"chat_id": chat or os.environ["TELEGRAM_CHAT_ID"], "text": text,
                                 "parse_mode": "HTML", "disable_web_page_preview": "true"})


def send_video(video, caption, chat=None):
    chat = chat or os.environ["TELEGRAM_CHAT_ID"]
    head, rest = (caption, "") if len(caption) <= CAPTION_MAX else split_caption(caption)
    r = _call("sendVideo", {"chat_id": chat, "caption": head, "parse_mode": "HTML", "supports_streaming": "true"},
              files={"video": fit(video)})
    if rest:
        send_text(rest, chat)
    return r


def split_caption(text):
    cut = text.rfind("\n", 0, CAPTION_MAX)
    cut = cut if cut > 0 else CAPTION_MAX
    return text[:cut], text[cut:].lstrip("\n")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    if cmd == "test":
        send_text("Clip robot connected ✅\nClips will arrive here, best first.")
    elif cmd == "text":
        send_text(sys.argv[2])
    elif cmd == "video":
        send_video(sys.argv[2], Path(sys.argv[3]).read_text(encoding="utf-8"))
    else:
        raise SystemExit(__doc__)
    print("sent")
