"""Send clips to his private Telegram chat. Python stdlib only (urllib, hand-built multipart).

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from the environment (Actions secrets); never prints them.
  send_telegram.py test                      one "Clip robot connected" message
  send_telegram.py text "message"            one text message
  send_telegram.py video FILE CAPTION_FILE   one video with its caption (HTML) underneath
Bots can upload at most 50 MB per file, so bigger videos are re-encoded first (see fit()).
"""
import json
import re
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


def _secret(name, pattern):
    """The token or chat ID inside whatever was pasted (extra words or spaces from a phone copy)."""
    raw = os.environ.get(name, "")
    m = re.search(pattern, raw)
    if not m:  # describe the shape only, never the value
        shape = "%d characters, %d spaces, %s colon, %d digits, starts with %s" % (
            len(raw), raw.count(" "), "has a" if ":" in raw else "no", sum(c.isdigit() for c in raw),
            "a digit" if raw[:1].isdigit() else "a letter" if raw[:1].isalpha() else "a symbol or space")
        raise SystemExit("%s doesn't look right (%s): paste it again (docs/telegram-setup.md, step D)" % (name, shape))
    return m.group()


def token():
    return _secret("TELEGRAM_BOT_TOKEN", r"\d{5,}:[A-Za-z0-9_-]{30,}")


def chat_id():
    return _secret("TELEGRAM_CHAT_ID", r"-?\d{5,}")


def _call(method, fields=None, files=None, tries=4):
    tok = token()
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
        req = urllib.request.Request(API % (tok, method), data=body, headers={"Content-Type": ctype})
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


def probe(path):
    """(width, height, seconds) of the video stream, so Telegram shows it at its real 9:16 shape."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True).stdout
    info = json.loads(out or "{}")
    st = (info.get("streams") or [{}])[0]
    return int(st.get("width") or 1080), int(st.get("height") or 1920), float((info.get("format") or {}).get("duration") or 30)


def fit(path):
    """A copy ready to stream: moov atom first (+faststart), same picture. Over the limit it is re-encoded
    at the highest bitrate that fits (22 Nov: he wants it sharp, so no lower than needed)."""
    path = Path(path)
    out = Path(tempfile.mkdtemp()) / path.name
    if path.stat().st_size <= LIMIT:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path), "-c", "copy",
                        "-movflags", "+faststart", str(out)], check=True)
        return out
    dur = probe(path)[2]
    kbps = int(LIMIT * 8 / 1000 / dur * 0.95) - 192
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path), "-c:v", "libx264", "-preset", "slow",
                    "-b:v", "%dk" % kbps, "-maxrate", "%dk" % int(kbps * 1.2), "-bufsize", "%dk" % (2 * kbps),
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)], check=True)
    return out


def send_text(text, chat=None):
    return _call("sendMessage", {"chat_id": chat or chat_id(), "text": text,
                                 "parse_mode": "HTML", "disable_web_page_preview": "true"})


def send_video(video, caption, chat=None):
    chat = chat or chat_id()
    head, rest = (caption, "") if len(caption) <= CAPTION_MAX else split_caption(caption)
    ready = fit(video)
    w, h, dur = probe(ready)
    r = _call("sendVideo", {"chat_id": chat, "caption": head, "parse_mode": "HTML", "supports_streaming": "true",
                            "width": w, "height": h, "duration": int(round(dur))}, files={"video": ready})
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
