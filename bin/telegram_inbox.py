"""Read his messages to the clip bot and act on them. Run every few minutes by telegram-inbox.yml.

Only messages from his own chat (TELEGRAM_CHAT_ID) count; anyone else gets nothing back.
Commands (case doesn't matter):
  clip <Kick VOD link> [number]   make clips from that stream (default 10), sent here when done
  clip latest [number]            the same for Dom's newest finished stream
  status                          is a run going, and how far
  stop                            cancel a run that's going
  help                            this list
Stateless: Telegram keeps unread messages for 24 h; asking with offset = last id + 1 marks them read.
Needs GH_TOKEN (the workflow's own token) to start or cancel glue-run.yml.
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import send_telegram as T  # noqa: E402

REPO = os.environ.get("GITHUB_REPOSITORY", "mapadda11/clip-engine")
CHANNEL = "dasgasd3m"  # the one joined campaign's streamer (RUCKUS); other channels are refused for now
KICK_VOD = re.compile(r"kick\.com/([A-Za-z0-9_-]+)/videos/([0-9a-f-]{36})")
MAX_CLIPS = 30
HELP = ("Clip robot commands:\n"
        "<code>clip latest</code>  clips from Dom's newest stream\n"
        "<code>clip LINK</code>  clips from a Kick VOD link (add a number for how many, default 10)\n"
        "<code>status</code>  is a run going\n"
        "<code>stop</code>  cancel the run\n"
        "Runs take about 60 to 90 min. Sunday's batch still runs by itself.")


def gh(*args):
    r = subprocess.run(["gh", *args, "-R", REPO], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[-300:])
    return r.stdout


def kick_list(channel=CHANNEL):
    req = urllib.request.Request("https://kick.com/api/v2/channels/%s/videos" % channel,
                                 headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def runs(status):
    return json.loads(gh("run", "list", "-w", "glue-run.yml", "-s", status, "-L", "5",
                         "--json", "databaseId,createdAt,displayTitle"))


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def do_clip(words, listing=kick_list, start=None):
    """Reply text for a clip command; starts glue-run when the request is good."""
    n = next((int(w) for w in words if w.isdigit()), 10)
    n = max(1, min(n, MAX_CLIPS))
    link = next((w for w in words if "kick.com" in w), None)
    if link:
        m = KICK_VOD.search(link)
        if not m:
            return "That doesn't look like a Kick VOD link (kick.com/…/videos/…). Try <code>clip latest</code>."
        if m.group(1).lower() != CHANNEL:
            return "Only Dom's streams for now (the RUCKUS campaign). That link is %s's." % esc(m.group(1))
        url, title = "https://kick.com/%s/videos/%s" % m.groups(), None
        for v in listing():
            if (v.get("video") or {}).get("uuid") == m.group(2):
                title = v.get("session_title")
        if title is None:
            return "I can't find that stream in Dom's list. It may be deleted or still live."
    elif "latest" in words:
        done = [v for v in listing() if not v.get("is_live") and v.get("source")]
        if not done:
            return "Dom has no finished streams on Kick right now."
        v = done[0]
        url, title = "https://kick.com/%s/videos/%s" % (CHANNEL, v["video"]["uuid"]), v.get("session_title")
    else:
        return "Send <code>clip latest</code>, or <code>clip</code> and a Kick VOD link."
    if runs("in_progress") or runs("queued"):
        return "A run is already going. Send <code>status</code>, or <code>stop</code> to cancel it."
    (start or (lambda u, k: gh("workflow", "run", "glue-run.yml", "-f", "vod_url=" + u, "-f", "max=%d" % k,
                               "-f", "send=yes")))(url, n)
    return "On it, sir: %d clips from <b>%s</b>. About 60 to 90 min; they'll arrive here, best first." % (n, esc(title))


def do_status():
    going = runs("in_progress") + runs("queued")
    if not going:
        return "Nothing running. Send <code>clip latest</code> to start one."
    r = going[0]
    jobs = json.loads(gh("run", "view", str(r["databaseId"]), "--json", "jobs"))["jobs"]
    step = next((s["name"] for j in jobs for s in j.get("steps", []) if s.get("status") == "in_progress"), "starting")
    return "Running since %s UTC. Now: %s." % (r["createdAt"][11:16], esc(step))


def do_stop():
    going = runs("in_progress") + runs("queued")
    for r in going:
        gh("run", "cancel", str(r["databaseId"]))
    return "Stopped." if going else "Nothing was running."


def reply_for(text):
    words = text.strip().lower().split() if text else []
    if not words:
        return None
    cmd = words[0].lstrip("/")
    if cmd == "clip":
        return do_clip(words[1:])
    if cmd == "status":
        return do_status()
    if cmd == "stop":
        return do_stop()
    return HELP


def main():
    mine = T.chat_id()
    ups = T._call("getUpdates", {"timeout": 0}).get("result") or []
    for u in ups:
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != mine:
            continue  # strangers who find the bot get no reply
        try:
            text = reply_for(msg.get("text"))
        except Exception as e:  # noqa: BLE001 - tell him rather than fail silently
            text = "Something went wrong: %s" % esc(str(e)[:200])
        if text:
            T.send_text(text)
    if ups:
        T._call("getUpdates", {"offset": ups[-1]["update_id"] + 1, "timeout": 0})  # mark read
    print("%d updates" % len(ups))


if __name__ == "__main__":
    main()
