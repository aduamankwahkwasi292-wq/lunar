"""
Videos for MrSOLIS — he watches and listens, offline (the user asked for it on 2026-10-24).

A video (or a recorded lecture, audio only) the student attaches in the chat box is prepared once:
  1. listening: ffmpeg pulls the soundtrack out as 16 kHz mono and Parakeet (backend/voice.py) writes
     what is said, piece by piece (< 20 s, cut at pauses), each with its start time;
  2. watching: ffmpeg grabs frames spread over the video (one about every 15 s, at most 48) and keeps
     those that look different from the last one kept — a lecture slide that stays up is one frame.
Each question then shows the brain a few frames, each after its time, plus what was said (see
`classroom.video_chat_stream`). The brains that see (Speedy and Smarts — Qwen3.5) take
pictures but have no ears: the transcript is how they "hear" a video.

Prepared videos are cached in <data>/study-cache/videos/<id>/ (meta.json + frame_NN.jpg), keyed by the
file's path, size and time, so asking about the same file again is instant.

ffmpeg and ffprobe: LUNAR_FFMPEG_DIR, else runtime/ffmpeg/ next to the AI engine, else the PATH.
Measured 2026-10-24 (i5-13420H): Smarts watched a 10 s clip sent as one 1 fps video in 42.6 s
(kx_video_test.py); here the frames are fewer and smaller so a question costs less.
"""

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import numpy as np

from backend import voice
from backend.local_llm import MODEL_DIR

CACHE_DIR = os.path.join(os.path.dirname(MODEL_DIR), "study-cache", "videos")    # main.py points it at the data dir
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
VIDEO_EXT = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".3gp", ".wmv", ".flv", ".mpg", ".mpeg", ".ts")
AUDIO_EXT = (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".opus", ".flac", ".wma", ".amr")
FRAME_W = 640                   # a frame is about 240 picture tokens for the Qwen brains at this size
CANDIDATES = 48                 # frames looked at per video, at most
KEEP = 24                       # frames kept after dropping look-alikes
SR = voice.SAMPLE_RATE
PIECE = 20 * SR                 # Parakeet takes up to ~20 s at a time
VERSION = 1                     # bump to re-prepare cached videos after a change here


# ── ffmpeg ─────────────────────────────────────────────────────────────
def _exe(d, name):
    p = os.path.join(d, name + (".exe" if sys.platform == "win32" else ""))
    return p if os.path.isfile(p) else None


def tools():
    """(ffmpeg, ffprobe) paths, or (None, None) when this computer has no ffmpeg."""
    dirs = [os.environ.get("LUNAR_FFMPEG_DIR")]
    base = os.path.dirname(MODEL_DIR)
    dirs += [os.path.join(base, "runtime", "ffmpeg"), os.path.join(base, "runtime", "ffmpeg", "bin")]
    for d in dirs:
        if d and _exe(d, "ffmpeg"):
            return _exe(d, "ffmpeg"), _exe(d, "ffprobe")
    ff = shutil.which("ffmpeg")
    if not ff:
        return None, None
    return ff, shutil.which("ffprobe")


def available() -> bool:
    return tools()[0] is not None


def probe(path: str) -> dict:
    """Length, picture size and which streams a media file has."""
    ff, fp = tools()
    if fp:
        out = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                              "-of", "json", path], capture_output=True, text=True, timeout=60,
                             creationflags=NO_WINDOW).stdout
        d = json.loads(out or "{}")
        streams = d.get("streams") or []
        vid = next((s for s in streams if s.get("codec_type") == "video" and s.get("width")), None)
        return {"duration": float((d.get("format") or {}).get("duration") or 0),
                "video": bool(vid), "audio": any(s.get("codec_type") == "audio" for s in streams),
                "width": (vid or {}).get("width", 0), "height": (vid or {}).get("height", 0)}
    # no ffprobe: read ffmpeg's own description of the file
    err = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True, timeout=60,
                         creationflags=NO_WINDOW).stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    size = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", err)
    return {"duration": int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0,
            "video": bool(size), "audio": "Audio:" in err,
            "width": int(size[1]) if size else 0, "height": int(size[2]) if size else 0}


# ── jobs ───────────────────────────────────────────────────────────────
JOBS = {}                        # id -> {"state", "progress", "error", "name", "path", "meta"}
_LOCK = threading.Lock()         # one video prepared at a time: it is heavy work for a laptop


def video_id(path: str) -> str:
    st = os.stat(path)
    key = f"{os.path.abspath(path).lower()}|{st.st_size}|{int(st.st_mtime)}|v{VERSION}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _dir(vid: str) -> str:
    return os.path.join(CACHE_DIR, vid)


def load(vid: str):
    """The prepared video (meta.json), or None."""
    try:
        with open(os.path.join(_dir(vid), "meta.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def frame_path(vid: str, n: int):
    meta = load(vid)
    if not meta or not (0 <= n < len(meta["frames"])):
        return None
    return os.path.join(_dir(vid), meta["frames"][n]["file"])


def status(vid: str) -> dict:
    job = JOBS.get(vid)
    meta = load(vid)
    if meta and (not job or job["state"] == "ready"):
        return {"id": vid, "state": "ready", "progress": 1.0, "name": meta["name"], "duration": meta["duration"],
                "frames": len(meta["frames"]), "words": sum(len(s["text"].split()) for s in meta["segments"]),
                "heard": meta["heard"], "seen": meta["seen"]}
    if not job:
        return {"id": vid, "state": "missing"}
    return {"id": vid, "state": job["state"], "progress": round(job["progress"], 3), "name": job["name"],
            "error": job.get("error", ""), "duration": job.get("duration", 0)}


def prepare(path: str, name: str = "") -> dict:
    """Start preparing a video (no-op when it is ready or already being prepared). Returns its status."""
    if not os.path.isfile(path):
        raise FileNotFoundError("That video file isn't there any more.")
    if not path.lower().endswith(VIDEO_EXT + AUDIO_EXT):
        raise ValueError("That isn't a video or sound file MrSOLIS can open.")
    if not available():
        raise RuntimeError("MrSOLIS needs ffmpeg to watch videos, and it isn't on this computer.")
    vid = video_id(path)
    if load(vid) is None and JOBS.get(vid, {}).get("state") not in ("waiting", "probing", "listening", "watching"):
        JOBS[vid] = {"state": "waiting", "progress": 0.0, "name": name or os.path.basename(path), "path": path}
        threading.Thread(target=_run, args=(vid,), daemon=True, name=f"video-{vid}").start()
    return status(vid)


def wait(vid: str, timeout: float = 3600) -> dict:
    """Block until the video is ready (or failed). For callers in a worker thread."""
    end = time.time() + timeout
    while time.time() < end:
        st = status(vid)
        if st["state"] in ("ready", "error", "missing"):
            return st
        time.sleep(0.3)
    return status(vid)


def _run(vid: str):
    job = JOBS[vid]
    with _LOCK:
        try:
            job["state"] = "probing"
            info = probe(job["path"])
            dur = info["duration"]
            if dur <= 0:
                raise RuntimeError("MrSOLIS couldn't tell how long this video is — it may be damaged.")
            job["duration"] = dur
            out = _dir(vid)
            os.makedirs(out, exist_ok=True)
            hear = info["audio"] and voice.status()["hear"]
            # progress: listening is most of the work when there is sound
            share = 0.8 if hear and info["video"] else (1.0 if hear else 0.0)
            segments = _listen(job, job["path"], dur, share) if hear else []
            frames = _watch(job, job["path"], dur, out, share) if info["video"] else []
            meta = {"id": vid, "name": job["name"], "path": job["path"], "duration": round(dur, 2),
                    "seen": info["video"], "heard": hear, "sound": info["audio"],
                    "segments": segments, "frames": frames, "made": time.time(), "version": VERSION}
            with open(os.path.join(out, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=1)
            job.update(state="ready", progress=1.0)
        except Exception as e:                                  # say what happened, in plain words
            msg = str(e) if isinstance(e, (RuntimeError, ValueError, FileNotFoundError)) else \
                "MrSOLIS couldn't open this video."
            job.update(state="error", error=msg)


def _listen(job, path, dur, share):
    """What is said, as [{"t": start s, "end": s, "text"}], streamed from ffmpeg piece by piece."""
    ff = tools()[0]
    job["state"] = "listening"
    p = subprocess.Popen([ff, "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                         creationflags=NO_WINDOW)
    segs, buf, base, done = [], np.zeros(0, np.float32), 0, False
    try:
        while not done or len(buf):
            if not done and len(buf) < PIECE + int(2.5 * SR):
                raw = p.stdout.read(10 * SR * 2)                # 10 s at a time
                if raw:
                    buf = np.concatenate([buf, np.frombuffer(raw[: len(raw) // 2 * 2], np.int16) / 32768.0])
                    buf = buf.astype(np.float32, copy=False)
                    continue
                done = True
            cut = len(buf) if done and len(buf) <= PIECE else voice.quiet_cut(buf, PIECE - int(2.5 * SR), PIECE)
            piece = buf[:cut]
            if len(piece) >= 0.3 * SR and float(np.sqrt(np.mean(piece ** 2))) > 0.003:   # not silence
                text = voice.recognize(piece)
                if re.search(r"[A-Za-z0-9]", text):
                    segs.append({"t": round(base / SR, 1), "end": round((base + cut) / SR, 1), "text": text})
            buf, base = buf[cut:], base + cut
            job["progress"] = min(share, share * base / (dur * SR))
    finally:
        p.kill()
    return segs


def _watch(job, path, dur, out, start):
    """Frames spread over the video, each kept only if it looks different from the last one kept."""
    from PIL import Image
    ff = tools()[0]
    job["state"] = "watching"
    n = max(min(6, math.ceil(dur / 2)), min(CANDIDATES, math.ceil(dur / 15)), 1)   # short clips: a few frames anyway
    kept, last = [], None
    for i in range(n):
        t = (i + 0.5) * dur / n
        f = os.path.join(out, f"frame_{len(kept):02d}.jpg")
        subprocess.run([ff, "-v", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                        "-vf", f"scale='min({FRAME_W},iw)':-2", "-q:v", "4", "-y", f],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=60, creationflags=NO_WINDOW)
        job["progress"] = start + (1 - start) * (i + 1) / n
        if not os.path.isfile(f):
            continue
        with Image.open(f) as im:
            small = np.asarray(im.convert("L").resize((128, 72)), np.float32)
        # the same picture as before? Slides that differ only in their words look alike when shrunk, so
        # count the pixels that changed clearly (new text, a new diagram) rather than the average change
        if last is not None and float(np.mean(np.abs(small - last) > 40)) < 0.01:
            os.remove(f)
            continue
        kept.append({"t": round(t, 1), "file": os.path.basename(f)})
        last = small
    if len(kept) > KEEP:                                       # many scene changes: keep an even spread
        pick = {round(k * (len(kept) - 1) / (KEEP - 1)) for k in range(KEEP)}
        for i, fr in enumerate(kept):
            if i not in pick:
                os.remove(os.path.join(out, fr["file"]))
        kept = [fr for i, fr in enumerate(kept) if i in pick]
    return kept


# ── what to show the brain for one question ──────────────────────────────
_STOP = set("""a an the and or but if of to in on at for with by from as is are was were be been being this that these
those it its what which who whom whose when where why how do does did can could should would will shall may might
about into over under than then there their they them he she we you your our his her i me my mine video lecture
talk says said say tell explain please mrsolis part show shows shown""".split())


def stamp(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _tokens(text: str) -> int:
    return int(len(text.split()) * 1.4) + 4


def overview(meta: dict, budget: int, n_frames: int):
    """The part of a video shown with EVERY question (so the brain's prompt cache can keep it):
    all of what is said when it fits in `budget` tokens, else evenly spread pieces; and up to `n_frames`
    frames spread over the video. Returns (segments, frames, complete)."""
    segs = meta["segments"]
    total = sum(_tokens(s["text"]) for s in segs)
    if total <= budget:
        chosen, complete = segs, True
    else:                                                     # an even spread of pieces that fits
        k = max(1, int(budget // (total / len(segs))))
        idx = sorted({round(i * (len(segs) - 1) / max(1, k - 1)) for i in range(k)})
        chosen, used, complete = [], 0, False
        for i in idx:
            if used + _tokens(segs[i]["text"]) > budget:
                break
            chosen.append(segs[i])
            used += _tokens(segs[i]["text"])
    return chosen, pick_frames(meta, n_frames), complete


def pick_frames(meta: dict, n: int) -> list:
    """Up to n of the kept frames, spread evenly over the video."""
    frames = meta["frames"]
    if len(frames) > n:
        frames = [frames[round(k * (len(frames) - 1) / max(1, n - 1))] for k in range(n)]
    return frames


def frame_urls(meta: dict, n: int) -> list:
    """[(seconds, JPEG data URL)] for the frames `pick_frames` chooses — what the brain is shown."""
    import base64
    out = []
    for fr in pick_frames(meta, n):
        try:
            with open(os.path.join(_dir(meta["id"]), fr["file"]), "rb") as f:
                out.append((fr["t"], "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("ascii")))
        except OSError:
            pass
    return out


def matching(meta: dict, question: str, exclude: list, budget: int) -> list:
    """Pieces of what is said that share words with the question (for long videos), in time order."""
    words = {w for w in re.findall(r"[a-z0-9']+", question.lower()) if len(w) > 2 and w not in _STOP}
    if not words or budget <= 0:
        return []
    have = {s["t"] for s in exclude}
    scored = []
    for s in meta["segments"]:
        if s["t"] in have:
            continue
        text = set(re.findall(r"[a-z0-9']+", s["text"].lower()))
        hits = sum(1 for w in words if w in text or any(t.startswith(w[:5]) for t in text if len(w) >= 6))
        if hits:
            scored.append((hits, s))
    out, used = [], 0
    for hits, s in sorted(scored, key=lambda x: -x[0]):
        if used + _tokens(s["text"]) > budget:
            continue
        out.append(s)
        used += _tokens(s["text"])
    return sorted(out, key=lambda s: s["t"])
