"""Plain words, plans he OKs, and standing orders on the clip bot (task 25 step 8b, 25 Nov 2026).

The rules live in alfred-hq clips/bin/orders.py; this file connects them to Telegram and to glue-run.yml.
    reply(text)  the bot's answer to "pause 2" / "ok" / plain words, or None when it isn't one of those
    tick()       called on every poll of telegram-inbox.yml: starts a batch for a standing order he OK'd when
                 its count for today is short and no run is going. Nothing else ever starts a run by itself.
"""
import csv
import datetime as dt
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
CLIPS = Path(os.environ.get("ALFRED_HQ", "alfred-hq")) / "clips"
sys.path.insert(0, str(CLIPS / "bin"))


def _now():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Europe/London")).replace(tzinfo=None)
    except Exception:  # noqa: BLE001
        return dt.datetime.utcnow()


def _repo():
    import crew_cmds
    import telegram_inbox as I
    return crew_cmds.Repo(call=I._github)


def _save(repo, rows, why):
    import orders as O
    repo.put(O.FILE, O.dump(rows), why)


def back_vod(camp, kick=None, gql=None):
    """The newest finished stream of this campaign's streamer that has no clip in used.csv yet."""
    import telegram_inbox as I
    import used as U
    done = {r.get("video") for r in U.read(path=CLIPS / "used.csv")}
    ch = camp["channel"]
    if camp["platform"] == "twitch":
        user = (gql or I.twitch_gql)('query{user(login:"%s"){videos(first:30,type:ARCHIVE){edges{node{id status}}}}}' % ch)
        for e in (((user.get("user") or {}).get("videos") or {}).get("edges")) or []:
            v = e.get("node") or {}
            if v.get("status") != "RECORDING" and v.get("id") not in done:
                return "https://www.twitch.tv/videos/%s" % v["id"]
        return None
    for v in (kick or I.kick_list)(ch):
        uid = (v.get("video") or {}).get("uuid")
        if not v.get("is_live") and v.get("source") and uid and uid not in done:
            return "https://kick.com/%s/videos/%s" % (ch, uid)
    return None


def start(r, n, dispatch=None, camps=None):
    """Start glue-run for an order row. Returns a sentence for him."""
    import telegram_inbox as I
    camps = I.campaigns() if camps is None else camps
    camp = camps.get(r["campaign"])
    if r["source"] == "link":
        url = r["link"]
    elif not camp:
        return "Order %s: there's no campaign called %s." % (r["id"], r["campaign"])
    elif r["source"] == "back":
        url = back_vod(camp)
    else:
        url = (I.latest(camp) or [None])[0]
    if not url:
        return "Order %s: no stream left to clip for %s (every one is in used.csv)." % (r["id"], r["campaign"])
    fmt = r.get("format") or ""
    if fmt.startswith("his-"):
        if fmt != "his-4":
            return ("Order %s: format %s isn't built yet. OK its layout first (send previews togi), then Claude builds "
                    "it." % (r["id"], fmt[4:]))
        fmt = "F8"
    real = "yes" if camp and camp.get("ready") else "no"
    (dispatch or (lambda: I.gh("workflow", "run", "glue-run.yml", "-f", "vod_url=" + url, "-f", "max=%d" % n,
                               "-f", "send=yes", "-f", "campaign=" + r["campaign"], "-f", "real=" + real,
                               "-f", "options=" + ("format:" + fmt if fmt else ""))))()
    return "Order %s: making %d %s clips from %s. They'll come here for your ok." % (r["id"], n, r["campaign"], url)


def reply(text, repo=None, now=None, dispatch=None, camps=None):
    import orders as O
    import telegram_inbox as I
    now = now or _now()
    is_control, is_ok = O.CONTROL.match(text or ""), O.OK.match(text or "")
    names = None
    if not (is_control or is_ok):
        camps = I.campaigns() if camps is None else camps
        names = list(camps)
        plan = O.parse(text, names)
        if not plan:
            return None
    repo = repo or _repo()
    rows = O.load(repo.get(O.FILE))
    if is_control:
        rows, out = O.control(rows, text, now)
        _save(repo, rows, "He replied: %s" % text.strip()[:40])
        return out
    if is_ok:
        rows, r = O.confirm(rows, now)
        if not r:
            return None
        if r["status"] == "once":
            out = start(r, int(r["n"] or 10), dispatch, camps)
            r["status"] = "done"
        else:
            out = "Standing order %s is on. I'll start batches until %s clips are made each day." % (r["id"], r["per_day"])
        _save(repo, rows, "He OK'd order %s" % r["id"])
        return out
    rows, nid = O.propose(rows, plan, text, now)
    _save(repo, rows, "Plan %d waiting for his ok" % nid)
    return O.describe(plan) + " (order %d)" % nid


def made_today(today, path=None):
    out = {}
    try:
        with open(path or CLIPS / "queue.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("date") == today:
                    out[r.get("campaign", "")] = out.get(r.get("campaign", ""), 0) + 1
    except OSError:
        pass
    return out


def tick(busy=None, dispatch=None, camps=None, path=None, now=None, send=None):
    """One poll: start at most one batch for a standing order that's short today. Returns what it did or None."""
    import orders as O
    import telegram_inbox as I
    try:
        rows = O.load((path or CLIPS / "orders.csv").read_text(encoding="utf-8"))
    except OSError:
        return None
    today = (now or _now()).date().isoformat()
    want = O.wanted(rows, made_today(today), today)
    if not want:
        return None
    if (busy or (lambda: I.runs("in_progress") or I.runs("queued")))():
        return None
    r = want[0]
    left = int(r["per_day"]) - made_today(today).get(r["campaign"], 0)
    out = start(r, max(1, min(10, left)), dispatch, camps)
    (send or I.T.send_text)(out)
    return out
