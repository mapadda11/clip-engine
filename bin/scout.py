"""Scout (26 Nov 2026, his step 2: clips arrive on their own). scout.yml runs this every 2 hours.

For each streamer in STREAMERS (Lacy on Twitch, Togi on Kick), never more than one clip run each at a time:
  1. new VOD: a finished stream not clipped yet (alfred-hq clips/vods.csv, clips/used.csv, recent run titles)
     -> one batch on it.
  2. top-up: otherwise, if fewer than FRESH clips of that streamer reached the Clip Desk today (UK) and none are on
     the way -> the next unused older VOD, so 8 fresh Lacy and 8 fresh Togi clips wait by 15:30 UK.
A batch = glue-run (options "scout") aiming for MAKE clips: approvals.finish puts the best 8 on the desk as new, the
rest under "low", and sends one Telegram ping. A failed run retries once (glue-run.yml), then one message says why.
Each VOD it starts is written to alfred-hq clips/vods.csv, so no stream is clipped twice.
Never more than DAILY_CAP scout runs per streamer a day, so a stream that keeps making 0 clips can't loop.
The run's summary (one line per streamer) is what the Crew room shows as the Scout's last result.
"""
import csv
import io
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import telegram_inbox as I  # noqa: E402

STREAMERS = ("lacy", "togi")
FRESH = 8        # his rule: at least 8 fresh clips of each streamer waiting by 15:30 UK
MAKE = 14        # clips a batch aims for; the best 8 go on the desk as new, the rest "low"
DAILY_CAP = 3    # scout runs per streamer per UK day
TOPUP_FROM = 6   # UK hour from which a short day is topped up from an older VOD
CLIPS = Path(os.environ.get("ALFRED_HQ", "alfred-hq")) / "clips"
VODS = "clips/vods.csv"
VOD_FIELDS = ["date", "campaign", "vod", "url", "why"]
ON_DESK = ("waiting", "rehook", "ready", "scheduled", "posted")  # reached the desk; his ok or posting keeps it counted
GOING = ("queued", "in_progress", "waiting", "requested", "pending")


def uk_now():
    import datetime as dt
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Europe/London")).replace(tzinfo=None)
    except Exception:  # noqa: BLE001
        return dt.datetime.utcnow()


def read_csv(text):
    return list(csv.DictReader(io.StringIO(text or "")))


def local(name):
    try:
        return (CLIPS / name).read_text(encoding="utf-8")
    except OSError:
        return ""


def vod_id(url):
    """The VOD id used in used.csv: Twitch's number, Kick's uuid."""
    return (url or "").rstrip("/").split("/")[-1]


def fresh(camp, today, queue):
    """Clips of this streamer that reached the Clip Desk today (UK)."""
    return sum(1 for r in queue if r.get("campaign") == camp and r.get("date") == today and r.get("status") in ON_DESK)


def title_of(r):
    """(campaign, vod url, options) from a glue-run title "clip CAMPAIGN URL OPTIONS..." (glue-run run-name)."""
    w = (r.get("displayTitle") or "").split()
    if len(w) >= 3 and w[0] == "clip":
        return w[1], w[2], w[3:]
    return None, None, []


def busy(camp, runs):
    """A run for this streamer is going, or one whose streamer can't be told (an old untitled run)."""
    for r in runs:
        if r.get("status") in GOING:
            c, _, _ = title_of(r)
            if c in (camp, None):
                return True
    return False


def started_today(camp, runs, today_utc):
    return sum(1 for r in runs if title_of(r)[0] == camp and "scout" in title_of(r)[2] and "retry" not in title_of(r)[2]
               and (r.get("createdAt") or "")[:10] == today_utc)


def finished_vods(camp, kick=None, gql=None):
    """This streamer's finished streams, newest first, as URLs."""
    ch = camp["channel"]
    if camp["platform"] == "twitch":
        user = (gql or I.twitch_gql)('query{user(login:"%s"){videos(first:30,type:ARCHIVE){edges{node{id status}}}}}' % ch)
        edges = (((user.get("user") or {}).get("videos") or {}).get("edges")) or []
        if not edges and gql is None:  # 26 Nov review: Lacy came back empty on the runner; say what Twitch answered
            import urllib.request
            q = json.dumps({"query": 'query{user(login:"%s"){videos(first:3,type:ARCHIVE){edges{node{id status}}}}}' % ch})
            req = urllib.request.Request("https://gql.twitch.tv/gql", data=q.encode(), headers={
                "Client-ID": I.TWITCH_CID, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    print("twitch answered for %s: %s" % (ch, r.read()[:300]))
            except Exception as e:  # noqa: BLE001
                print("twitch failed for %s: %s" % (ch, str(e)[:200]))
        return ["https://www.twitch.tv/videos/%s" % e["node"]["id"] for e in edges
                if (e.get("node") or {}).get("id") and e["node"].get("status") != "RECORDING"]
    out = []
    for v in (kick or I.kick_list)(ch):
        uid = (v.get("video") or {}).get("uuid")
        if not v.get("is_live") and v.get("source") and uid:
            out.append("https://kick.com/%s/videos/%s" % (ch, uid))
    return out


def decide(camp, name, vods, done, runs, queue, now, today_utc):
    """(url, why) to start, or (None, reason) for this streamer. Pure: everything it needs is passed in."""
    today = now.date().isoformat()
    have = fresh(name, today, queue)
    if busy(name, runs):
        return None, "a run is already going (%d fresh on the desk today)" % have
    if started_today(name, runs, today_utc) >= DAILY_CAP:
        return None, "already started %d runs today, the daily cap (%d fresh)" % (DAILY_CAP, have)
    taken = set(done) | {vod_id(title_of(r)[1]) for r in runs if title_of(r)[1]}
    left = [u for u in vods if vod_id(u) not in taken]
    if not vods:
        return None, "no finished streams found (%d fresh)" % have
    if vods[0] in left:
        return vods[0], "new stream"
    if have >= FRESH:
        return None, "no new stream; %d fresh on the desk today, enough" % have
    if now.hour < TOPUP_FROM:
        return None, "no new stream; %d fresh, top-up starts at %02d:00 UK" % (have, TOPUP_FROM)
    if not left:
        return None, "only %d fresh and every stream on the list is clipped" % have
    return left[0], "only %d fresh today: next unused older stream" % have


def start(name, url, why, dispatch=None):
    (dispatch or (lambda: I.gh("workflow", "run", "glue-run.yml", "-f", "vod_url=" + url, "-f", "max=%d" % MAKE,
                               "-f", "send=yes", "-f", "campaign=" + name, "-f", "real=yes",
                               "-f", "options=scout")))()


def remember(rows, repo):
    """Add the started VODs to alfred-hq clips/vods.csv (re-read just before writing)."""
    have = read_csv(repo.get(VODS))
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=VOD_FIELDS, lineterminator="\n")
    w.writeheader()
    for r in have + rows:
        w.writerow({k: r.get(k, "") for k in VOD_FIELDS})
    repo.put(VODS, out.getvalue(), "Scout started %s" % ", ".join("%s %s" % (r["campaign"], r["vod"]) for r in rows))


def main():
    now = uk_now()
    import datetime as dt
    today_utc = dt.datetime.utcnow().date().isoformat()
    camps = I.campaigns()
    runs = json.loads(I.gh("run", "list", "-w", "glue-run.yml", "-L", "100",
                           "--json", "databaseId,status,conclusion,createdAt,displayTitle"))
    queue = read_csv(local("queue.csv"))
    done = {r.get("vod") for r in read_csv(local("vods.csv"))} | {r.get("video") for r in read_csv(local("used.csv"))}
    lines, started, bad = [], [], 0
    for name in STREAMERS:
        camp = camps.get(name)
        if not camp or not camp.get("channel"):
            lines.append("%s: no settings file or channel" % name)
            bad += 1
            continue
        try:
            vods = finished_vods(camp)
        except Exception as e:  # noqa: BLE001 - one streamer's site failing must not stop the other
            lines.append("%s: couldn't read %s (%s)" % (name, camp["platform"], str(e)[:120]))
            bad += 1
            continue
        url, why = decide(camp, name, vods, done, runs, queue, now, today_utc)
        if url:
            start(name, url, why)
            started.append({"date": now.date().isoformat(), "campaign": name, "vod": vod_id(url), "url": url, "why": why})
            lines.append("%s: started a batch of %d on %s (%s)" % (name, MAKE, url, why))
        else:
            lines.append("%s: nothing to start, %s" % (name, why))
    if started:
        sys.path.insert(0, str(CLIPS / "bin"))
        import crew_cmds
        try:
            remember(started, crew_cmds.Repo(call=I._github))
        except Exception as e:  # noqa: BLE001
            lines.append("couldn't save clips/vods.csv (%s)" % str(e)[:120])
            bad += 1
    text = "\n".join(lines)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("Scout %s UK\n\n%s\n" % (now.strftime("%H:%M"), re.sub(r"^", "- ", text, flags=re.M)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
