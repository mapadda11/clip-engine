"""Read his messages to the clip bot and act on them. Run every few minutes by telegram-inbox.yml.

Only messages from his own chat (TELEGRAM_CHAT_ID) count; anyone else gets nothing back.
Commands (case doesn't matter):
  clip latest <campaign> [number] clips from that campaign's streamer's newest finished stream (default 10)
  clip latest [number]            the same, when only one campaign is joined
  clip <VOD link> [campaign] [n]  clips from that stream (Kick or Twitch), sent here when done
  campaigns                       the campaigns the clipper knows, joined or not
  status                          is a run going, and how far
  stop                            cancel a run that's going
  help                            this list
Stateless: Telegram keeps unread messages for 24 h; asking with offset = last id + 1 marks them read.
Needs GH_TOKEN (the workflow's own token) to start or cancel glue-run.yml.
Campaigns (23 Nov): one settings file each in alfred-hq clips/campaigns/settings/ (checked out read-only
by the workflow); adding a campaign is a new file there, no code here.
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import send_telegram as T  # noqa: E402

REPO = os.environ.get("GITHUB_REPOSITORY", "mapadda11/clip-engine")
KICK_VOD = re.compile(r"kick\.com/([A-Za-z0-9_-]+)/videos/([0-9a-f-]{36})")
TWITCH_VOD = re.compile(r"twitch\.tv/videos/(\d+)")
TWITCH_CID = "kimne78kx3ncx6brgo4mv6wki5h1ko"  # Twitch's public web client id
MAX_CLIPS = 30
GLUE = Path(os.environ.get("ALFRED_HQ", "alfred-hq")) / "clips" / "bin"
HELP = ("Clip robot commands:\n"
        "<code>clip latest ruckus</code>  clips from that campaign's newest stream (any campaign name)\n"
        "<code>clip community kai 10</code>  10 clips cut from the moments viewers clipped most (fast, about 20 min)\n"
        "<code>clip LINK</code>  clips from a Kick or Twitch VOD link (add a number for how many, default 10)\n"
        "Add <code>grade</code> to a clip command to see the rejects too (labelled, not for posting)\n"
        "<code>3: 7/10 start faster</code>  grade clip 3 (reply to the clip itself if you can)\n"
        "<code>pings kai 18:00 19:30</code>  after scheduling: I ping you as each clip goes live, with the submit link\n"
        "<code>campaigns</code>  the campaigns I know\n"
        "<code>status</code>  is a run going\n"
        "<code>stop</code>  cancel the run\n"
        "Runs take about 60 to 90 min. Sunday's batch still runs by itself.")


def gh(*args):
    r = subprocess.run(["gh", *args, "-R", REPO], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[-300:])
    return r.stdout


def campaigns():
    """{name: campaign} from alfred-hq's settings files (the same reader the clipper uses)."""
    sys.path.insert(0, str(GLUE))
    import cliplib as L
    return {stem: L.camp_from_settings(st) for stem, st in L.campaign_settings().items()}


def joined(c):
    return "campaign:joined" in c["labels"] and c["state"] == "OPEN"


def kick_list(channel):
    req = urllib.request.Request("https://kick.com/api/v2/channels/%s/videos" % channel,
                                 headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def twitch_gql(query):
    req = urllib.request.Request("https://gql.twitch.tv/gql", data=json.dumps({"query": query}).encode(),
                                 headers={"Client-ID": TWITCH_CID, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("data") or {}


def latest(camp, kick=kick_list, gql=twitch_gql):
    """(url, title) of the campaign streamer's newest finished stream, or None."""
    ch = camp["channel"]
    if camp["platform"] == "twitch":
        user = gql('query{user(login:"%s"){videos(first:1,type:ARCHIVE){edges{node{id title status}}}}}' % ch)
        edges = (((user.get("user") or {}).get("videos") or {}).get("edges")) or [{}]
        v = edges[0].get("node")
        if v and v.get("status") != "RECORDING":
            return "https://www.twitch.tv/videos/%s" % v["id"], v.get("title")
        return None
    done = [v for v in kick(ch) if not v.get("is_live") and v.get("source")]
    if not done:
        return None
    return "https://kick.com/%s/videos/%s" % (ch, done[0]["video"]["uuid"]), done[0].get("session_title")


def link_channel(link, kick=kick_list, gql=twitch_gql):
    """(channel, title) for a Kick or Twitch VOD link, or None when it isn't one."""
    m = KICK_VOD.search(link)
    if m:
        for v in kick(m.group(1)):
            if (v.get("video") or {}).get("uuid") == m.group(2):
                return m.group(1).lower(), v.get("session_title")
        return m.group(1).lower(), None
    m = TWITCH_VOD.search(link)
    if m:
        v = gql('query{video(id:"%s"){title owner{login}}}' % m.group(1)).get("video") or {}
        return ((v.get("owner") or {}).get("login") or "").lower(), v.get("title")
    return None


def do_campaigns(camps=None):
    camps = campaigns() if camps is None else camps
    if not camps:
        return "No campaign settings found (alfred-hq clips/campaigns/settings/)."
    return "Campaigns:\n" + "\n".join(
        "<b>%s</b>: %s, %s%s" % (esc(k), esc(c["channel"] or "no channel yet"), c["platform"],
                                 "" if joined(c) else " (not joined)") for k, c in camps.items())


def runs(status):
    return json.loads(gh("run", "list", "-w", "glue-run.yml", "-s", status, "-L", "5",
                         "--json", "databaseId,createdAt,displayTitle"))


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def do_clip(words, camps=None, kick=kick_list, gql=twitch_gql, start=None):
    """Reply text for a clip command; starts glue-run when the request is good."""
    camps = campaigns() if camps is None else camps
    n = next((int(w) for w in words if w.isdigit()), 10)
    n = max(1, min(n, MAX_CLIPS))
    named = next((k for w in words for k, c in camps.items() if w in (k, c["title"].lower())), None)
    link = next((w for w in words if "kick.com" in w or "twitch.tv" in w), None)
    if link:
        found = link_channel(link, kick, gql)
        if not found:
            return "That doesn't look like a Kick or Twitch VOD link. Try <code>clip latest CAMPAIGN</code>."
        ch, title = found
        if title is None:
            return "I can't find that stream. It may be deleted or still live."
        named = named or next((k for k, c in camps.items() if c["channel"].lower() == ch), None)
        if not named:
            return "No campaign has %s as its streamer. Send <code>campaigns</code> to see them." % esc(ch)
        camp = camps[named]
        if not camp["any_streamer"] and camp["channel"].lower() != ch:
            return "%s isn't %s's streamer (%s is)." % (esc(ch), esc(camp["title"]), esc(camp["channel"]))
        url = link
    elif "latest" in words or "community" in words:  # task 17: "clip community kai 10" = newest VOD, community path
        if not named:
            ready = [k for k, c in camps.items() if joined(c)]
            if len(ready) != 1:
                return "Which campaign? Send <code>clip latest NAME</code>.\n" + do_campaigns(camps)
            named = ready[0]
        camp = camps[named]
        if camp["any_streamer"]:
            return "%s takes any streamer: send <code>clip LINK %s</code> with the stream you want." % (
                esc(camp["title"]), esc(named))
        if not camp["channel"]:
            return "%s has no channel in its settings yet." % esc(camp["title"])
        got = latest(camp, kick, gql)
        if not got:
            return "%s has no finished streams right now." % esc(camp["channel"])
        url, title = got
    else:
        return "Send <code>clip latest CAMPAIGN</code>, or <code>clip</code> and a VOD link."
    if not joined(camp):
        return "You haven't joined %s yet (or it has ended). Set <code>joined: yes</code> in its settings first." % esc(
            camp["title"])
    if runs("in_progress") or runs("queued"):
        return "A run is already going. Send <code>status</code>, or <code>stop</code> to cancel it."
    grade = "grade" in words  # 24 Nov grading mode: the rejects come too, labelled
    import datetime
    opts = ("community lenient bar:6 release:%s-%s" % (named, datetime.date.today().isoformat())
            if "community" in words else "")  # task 17 Phase C: moments viewers clipped, 4 hard rules, Viewer bar 6
    (start or (lambda u, k, c: gh("workflow", "run", "glue-run.yml", "-f", "vod_url=" + u, "-f", "max=%d" % k,
                                  "-f", "send=yes", "-f", "campaign=" + c,
                                  "-f", "real=" + ("yes" if camp.get("ready") else "no"),
                                  "-f", "grade=" + ("yes" if grade else "no"), "-f", "model=base.en" if opts else "model=small.en",
                                  "-f", "options=" + opts)))(url, n, named)
    return "On it, sir: %d %s clips from <b>%s</b>. %s; they'll arrive here, best first." % (
        n, esc(camp["title"]), esc(title or url), "About 20 min (community clips)" if opts else "About 60 to 90 min")


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


TAGS = re.compile(r"\[((?:kind|hook|run)=[^\]]*)\]")


def save_grade(text, replied_to="", put=None, today=None):
    """'3: 7/10 start faster' -> one line under ## Grades in alfred-hq clips/formula.md (grades.py).
    A reply to the clip's own message carries its [kind= hook= run=] tags. Needs ALFRED_HQ_TOKEN with
    Contents: write on alfred-hq."""
    import base64
    import datetime
    sys.path.insert(0, str(GLUE))
    import grades as G
    n, score, note = G.parse(text)
    m = TAGS.search(replied_to or "")
    tags = dict(kv.split("=", 1) for kv in (m.group(1).split() if m else []) if "=" in kv)
    line = G.line(today or datetime.date.today().isoformat(), n, score, note, tags)
    api = "https://api.github.com/repos/mapadda11/alfred-hq/contents/clips/formula.md"
    call = put or _github
    cur = call("GET", api)
    body = G.add(base64.b64decode(cur["content"]).decode("utf-8"), line)
    call("PUT", api, {"message": "Add his grade for clip %d" % n, "sha": cur["sha"],
                      "content": base64.b64encode(body.encode("utf-8")).decode()})
    try:  # task 17 (B3): his grade also goes next to the Viewer's score in clips/viewer-log.csv, if it exists
        api2 = "https://api.github.com/repos/mapadda11/alfred-hq/contents/clips/viewer-log.csv"
        cur2 = call("GET", api2)
        row = "%s,%s-%d,%s,,,,,,,,,,%g,%s\n" % (today or datetime.date.today().isoformat(), tags.get("run", "?"), n,
                                                tags.get("run", ""), score, (note or "").replace(",", ";"))
        body2 = base64.b64decode(cur2["content"]).decode("utf-8").rstrip("\n") + "\n" + row
        call("PUT", api2, {"message": "Add his grade for clip %d to the viewer log" % n, "sha": cur2["sha"],
                           "content": base64.b64encode(body2.encode("utf-8")).decode()})
    except Exception:  # noqa: BLE001 - the formula line is what counts; the viewer log is a bonus
        pass
    return "Saved, sir: clip %d, %g/10%s. The next run uses it." % (n, score, (" (" + esc(note) + ")") if note else "")


def _github(method, url, data=None):
    tok = os.environ.get("ALFRED_HQ_TOKEN", "")
    req = urllib.request.Request(url, method=method, data=json.dumps(data).encode() if data else None,
                                 headers={"Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (403, 404) and method == "PUT":
            raise RuntimeError("the alfred-hq key can't write yet (it needs Contents: Read and write)")
        raise


def reply_for(text, replied_to=""):
    words = text.strip().lower().split() if text else []
    if not words:
        return None
    sys.path.insert(0, str(GLUE))
    import grades as G
    if G.parse(text):
        return save_grade(text, replied_to)
    cmd = words[0].lstrip("/")
    if cmd == "clip":
        return do_clip(words[1:])
    if cmd == "campaigns":
        return do_campaigns()
    if cmd in ("pings", "ping", "times"):
        return do_pings(words[1:])
    if cmd == "status":
        return do_status()
    if cmd == "stop":
        return do_stop()
    return HELP


PING_TZ = os.environ.get("PING_TZ", "Europe/London")
TIME = re.compile(r"^(\d{1,2})(?::|\.)?(\d{2})?\s*(am|pm)?$")


def ping_times(words, now=None):
    """[(clip number, aware datetime)] for "18:00 19:30 9pm" in his time zone; a time already gone today
    means tomorrow."""
    import datetime
    from zoneinfo import ZoneInfo
    now = now or datetime.datetime.now(ZoneInfo(PING_TZ))
    out = []
    for w in words:
        m = TIME.match(w)
        if not m:
            continue
        h, mi = int(m.group(1)) % 24, int(m.group(2) or 0)
        h += 12 if m.group(3) == "pm" and h < 12 else 0
        h -= 12 if m.group(3) == "am" and h == 12 else 0
        at = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        at += datetime.timedelta(days=1) if at <= now else datetime.timedelta(0)
        out.append((len(out) + 1, at))
    return out


def do_pings(words, camps=None, post=None, now=None):
    """'pings kai 18:00 19:30 21:00': at each time the bot sends "Clip N is live: submit now" with the
    campaign's submit link (the Worker keeps and sends them; worker/bot-worker.js)."""
    camps = campaigns() if camps is None else camps
    named = next((k for w in words for k, c in camps.items() if w in (k, c["title"].lower())), None)
    if not named:
        ready = [k for k, c in camps.items() if joined(c)]
        named = ready[0] if len(ready) == 1 else None
    if not named:
        return "Which campaign? Send <code>pings kai 18:00 19:30</code>."
    times = ping_times(words, now)
    if not times:
        return "Send the publish times, e.g. <code>pings %s 18:00 19:30 21:00</code>." % esc(named)
    link = camps[named].get("url") or ""
    items = [{"at": int(at.timestamp()),
              "text": "<b>Clip %d is live</b> (%s): submit now, 30 min rule.\n%s" % (n, esc(camps[named]["title"]), esc(link))}
             for n, at in times]
    (post or _post_pings)(items)
    return "Pings set, sir: " + ", ".join("clip %d at %s" % (n, at.strftime("%H:%M %a")) for n, at in times) + "."


def _post_pings(items):
    url, key = os.environ.get("WORKER_URL", ""), os.environ.get("PING_KEY", "")
    if not (url and key):
        raise RuntimeError("pings need the webhook set up first (alfred-hq docs/telegram-webhook.md)")
    req = urllib.request.Request(url.rstrip("/") + "/pings", data=json.dumps(items).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30).read()


def handle(text, replied_to=""):
    try:
        out = reply_for(text, replied_to)
    except (Exception, SystemExit) as e:  # noqa: BLE001 - tell him rather than fail silently
        out = "Something went wrong: %s" % esc(str(e)[:200])
    if out:
        try:
            T.send_text(out)
        except (Exception, SystemExit) as e:  # noqa: BLE001 - never stop before the messages are marked read
            print("reply failed: %s" % str(e)[:200])


def main():
    pushed = os.environ.get("UPDATE")  # 24 Nov: the webhook Worker sends one message straight here
    if pushed:
        u = json.loads(pushed)
        handle(u.get("text"), u.get("reply_caption") or "")
        print("1 pushed update")
        return
    mine = T.chat_id()
    try:
        ups = T._call("getUpdates", {"timeout": 0}).get("result") or []
    except Exception as e:  # noqa: BLE001 - with the webhook on, Telegram refuses getUpdates (409): nothing to do
        print("getUpdates unavailable (%s); the webhook handles messages." % str(e)[:80])
        return
    for u in ups:
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != mine:
            continue  # strangers who find the bot get no reply
        handle(msg.get("text"), (msg.get("reply_to_message") or {}).get("caption") or "")
    if ups:
        T._call("getUpdates", {"offset": ups[-1]["update_id"] + 1, "timeout": 0})  # mark read
    print("%d updates" % len(ups))


if __name__ == "__main__":
    main()
