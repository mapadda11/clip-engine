"""Step 0 feasibility test: download, transcribe on CPU, find moments, render. Stdlib only.

Usage (inside the workflow): feasibility.py download|youtube|bench|engine|summary
Every stage adds its result to $WORK/out/timings.json.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

WORK = Path(os.environ.get("WORK", "work"))
OUT = WORK / "out"
VOD = WORK / "vod.mp4"
GC = WORK / "gaming-clip"
TIMINGS = OUT / "timings.json"
YOUTUBE_PROBE = "https://www.youtube.com/watch?v=V3FT_GmHDA0"  # CC-BY test video used on the Mac


def record(**kw):
    data = json.loads(TIMINGS.read_text()) if TIMINGS.exists() else {}
    data.update(kw)
    TIMINGS.write_text(json.dumps(data, indent=2))
    print(json.dumps(kw, indent=2))


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], **kw)


def duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def kick_source(url):
    """yt-dlp's kick:vod extractor gets NOT_FOUND since Kick changed its video API (22 Nov 2026).
    The channel's video list still gives each VOD's HLS link, so look the VOD up there."""
    m = re.match(r"https?://(?:www\.)?kick\.com/([^/]+)/videos/([0-9a-f-]{36})", url)
    if not m:
        return url, "as given"
    channel, uuid = m.groups()
    req = urllib.request.Request(f"https://kick.com/api/v2/channels/{channel}/videos",
                                 headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            for v in json.load(r):
                if (v.get("video") or {}).get("uuid") == uuid and v.get("source"):
                    return v["source"], "kick channel api"
    except Exception as e:  # noqa: BLE001 - recorded, then yt-dlp gets the plain URL
        print("kick api:", e)
        return url, f"kick api failed: {e}"
    return url, "not in channel list"


def download():
    url = os.environ["VOD_URL"]
    t = time.time()
    src, how = kick_source(url)
    r = run(["yt-dlp", "-N", "8", "--no-playlist", "-f", "best[height<=1080]/best", "--merge-output-format", "mp4",
             "-o", VOD, src], capture_output=True, text=True)
    secs = time.time() - t
    tail = (r.stderr or r.stdout)[-600:]
    ok = r.returncode == 0 and VOD.exists()
    record(download={"ok": ok, "seconds": round(secs), "url": url, "via": how,
                     "size_mb": round(VOD.stat().st_size / 1e6) if ok else 0,
                     "hours": round(duration(VOD) / 3600, 2) if ok else 0,
                     "error": "" if ok else tail})
    if not ok:
        sys.exit("Kick download failed:\n" + tail)


def youtube():
    r = run(["yt-dlp", "--simulate", "--no-playlist", "-f", "bv*+ba/b", YOUTUBE_PROBE], capture_output=True, text=True)
    out = (r.stderr + r.stdout)[-400:]
    record(youtube={"ok": r.returncode == 0, "detail": out.strip().splitlines()[-1] if out.strip() else ""})


def bench():
    wav = WORK / "sample.wav"
    run(["ffmpeg", "-v", "error", "-y", "-ss", "1200", "-t", "600", "-i", VOD, "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", wav], check=True)
    result = {}
    for model in ("base.en", "small.en"):
        t = time.time()
        # Same flags gaming-clip uses (word timing needs flash attention off).
        run([os.environ["WHISPER_BIN"], "-m", WORK / "models" / f"ggml-{model}.bin", "-f", wav, "-l", "en",
             "-ojf", "-of", WORK / f"bench-{model}", "-pp", "-nfa", "-dtw", model], check=True,
            stdout=subprocess.DEVNULL)
        secs = time.time() - t
        result[model] = {"seconds_for_10_min": round(secs), "min_per_hour": round(secs / 10, 1)}
        shutil.copy(WORK / f"bench-{model}.json", OUT / f"bench-{model}.json")
    record(bench=result)


def clip(*args, json_out=True):
    cmd = ["bun", "run", "--silent", "clip", *args] + (["--json"] if json_out else [])
    r = run(cmd, cwd=GC, stdout=subprocess.PIPE, text=True, check=True)
    return json.loads(r.stdout or "null")


def engine():
    n = int(os.environ.get("CLIPS", "3"))
    t = time.time()
    pid = clip("new", VOD, "--clips", max(10, n * 3), "--min", 15, "--max", 35, "--lang", "en")[0]["id"]
    ingest = time.time() - t
    pdir = WORK / "ws" / "projects" / pid
    project = json.loads((pdir / "project.json").read_text())
    clips = sorted(project.get("clips", []), key=lambda c: -(c.get("score") or 0))
    ids = ",".join(c["id"] for c in clips[:n])
    clip("clips", "select", pid, ids)
    clip("settings", pid, "--clips", "all", "--layout", "split", "--subtitles", "on", "--style", "pop",
         "--caption-y", "0.38")
    t = time.time()
    clip("render", pid, "--clips", ids)
    render = time.time() - t
    for f in (pdir / "clips").glob("*"):
        shutil.copy(f, OUT / f.name)
    shutil.copy(pdir / "transcript.json", OUT / "transcript.json")
    shutil.copy(pdir / "project.json", OUT / "project.json")
    hours = duration(VOD) / 3600
    record(engine={"model": os.environ.get("WHISPER_MODEL"), "ingest_seconds": round(ingest),
                   "render_seconds": round(render), "candidates": len(clips), "rendered": n,
                   "webcam": (project.get("webcam") or {}).get("rect"), "stages": project.get("stages"),
                   "vod_hours": round(hours, 2)})


def summary():
    d = json.loads(TIMINGS.read_text()) if TIMINGS.exists() else {}
    dl, yt, b, e = d.get("download", {}), d.get("youtube", {}), d.get("bench", {}), d.get("engine", {})
    print("## Feasibility result\n")
    print("| Check | Result |\n|---|---|")
    print(f"| Kick download | {'ok' if dl.get('ok') else 'FAILED'}: {dl.get('hours')} h, {dl.get('size_mb')} MB in {dl.get('seconds')} s |")
    print(f"| YouTube from runner | {'works' if yt.get('ok') else 'blocked'}: {yt.get('detail', '')[:120]} |")
    for m, v in b.items():
        print(f"| whisper {m} (CPU) | {v['min_per_hour']} min per hour of video |")
    if e:
        print(f"| Engine ({e.get('model')}) | ingest {e.get('ingest_seconds')} s, render {e.get('rendered')} clips {e.get('render_seconds')} s, {e.get('candidates')} candidates |")


if __name__ == "__main__":
    {"download": download, "youtube": youtube, "bench": bench, "engine": engine, "summary": summary}[sys.argv[1]]()
