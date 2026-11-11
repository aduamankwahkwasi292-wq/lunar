"""
MrSOLIS's brain: the model that teaches, chats, solves and *looks at* slides and photos.

The student picks one of a few small multimodal models (cards in Settings, and a chooser on
the first start after an update). It downloads once into DATA_DIR/brains/<id>/ and runs in
the official llama.cpp `llama-server` (CPU build, pinned — runtime/llama.cpp) as a sidecar on
127.0.0.1. Talking to it is the OpenAI chat API, so images go in as `image_url` parts.

Picked 2026-10-19 from the deep-research report (reports/Small multimodal model for MrSOLIS.md):
Qwen3.5-2B is the recommended brain; Qwen3.5-0.8B for the weakest laptops. The student said:
"users read their cards and pick their pref", with the cards' figures shown as estimates. Gemma 4
(the one that also hears) was left out on purpose. The middle card, Middler (Qwen3-VL-2B), was
dropped on 2026-10-29 (the user: "we'll find another model later for Middler").
"""

import asyncio
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time

import httpx

from backend.local_llm import MODEL_DIR

try:
    from backend import cloud               # the student's own AI account, when they add one (Settings → Brain)
except ImportError:                          # the frozen app's flat layout
    import cloud

DATA_DIR = os.environ.get("LUNAR_DATA_DIR") or os.path.join(os.path.dirname(MODEL_DIR), "data")
BRAIN_DIR = os.path.join(DATA_DIR, "brains")
HF = "https://huggingface.co"
# Our own fine-tuned brains. A repo of their own: in the app's repo every published release starts the
# installer build (.github/workflows/release.yml) and the auto-updater reads its releases.
RELEASES = "https://github.com/aduamankwahkwasi292-wq/mrsolis-brains/releases/download"

# The cards. Every number here is an ESTIMATE from published tests (Qwen's model cards,
# Unsloth's file listings, community CPU reports) — the app says so wherever it shows them.
# Speeds were checked 2026-10-19 on an i5-13420H, CPU only: Qwen3.5-2B wrote 12.5 tokens/s
# (~9 words/s) and took 17.6 s to start answering about a 1024x576 picture; the ranges reach
# down to slower 8 GB laptops. Once a brain runs, its card shows the speed measured here.
# ram_gb is the brain's own memory WITH CUSTOM-Kx (KX_FLAGS + the 8-bit picture reader), measured on that laptop
# (reports/CUSTOM-Kx initial report.md): Speedy levels off at about 1.1–1.2 GB over a 12-slide session, Smarts
# stays flat at about 2.2 GB over 10 slides (2.24 GB with a video). Before CUSTOM-Kx the cards said 2.5 and 3.5 GB
# (the user, 2026-10-29: "update the model memory requirement numbers to reflect the reduction").
# speed / smarts / slides are 1-5 dots, relative to each other. "name" is what the student sees
# (the user named them Speedy / Middler / Smarts, 2026-10-20; Middler dropped 2026-10-29). The real model's name must never reach the
# screen (the user's rule): "model_name" is for us only — status() leaves it out, and errors never quote URLs.
CATALOG = [
    {
        "id": "qwen3.5-0.8b", "name": "Speedy", "model_name": "Qwen3.5 0.8B", "tagline": "Fastest and lightest",
        "for": "Older or 4 GB–8 GB laptops, or when speed matters most",
        # Our fine-tune (2026-10-22, finetune/train_speedy.py on 2,600 MrSOLIS examples): on held-out decks it
        # checks quiz questions right 42/50 vs 33, never breaks quiz JSON or overruns a lesson limit; maths
        # unchanged. The picture reader (mmproj) is the original's — text-only training doesn't touch it.
        "repo": "unsloth/Qwen3.5-0.8B-GGUF", "revision": "6ab461498e2023f6e3c1baea90a8f0fe38ab64d0",
        "model": "MrSOLIS-Speedy-v1-Q4_K_M.gguf", "mmproj": "mmproj-F16.gguf",
        "model_url": f"{RELEASES}/speedy-v1/MrSOLIS-Speedy-v1-Q4_K_M.gguf",
        "sha256": {"MrSOLIS-Speedy-v1-Q4_K_M.gguf": "731b586c88cf6d263fbfc1954647f2b92b58123fc498b79d670f2ef30a471b80",
                   "mmproj-F16.gguf": "56e4c6cfe73b0c82e3e82bc518d7591997e61d81f723fc41a586f4fa69ea2453"},
        "download_gb": 0.73, "ram_gb": 1.2, "speed": 5, "smarts": 2, "slides": 3,
        "writing": "about 12–22 words a second", "picture": "about 5–12 seconds to look at a slide",
        "facts": ["Reads slides, photos and handwriting", "Trained for MrSOLIS: steadier lessons, quizzes and marking",
                  "Makes more mistakes on hard maths and facts"],
        "licence": "Apache 2.0", "sees": True,
    },
    # Middler (id "qwen3-vl-2b", Qwen3-VL 2B) sat here until 2026-10-29: dropped for now, a new model comes later.
    # A student who had picked it falls back to an installed brain (selected()); its files are left alone.
    {
        "id": "qwen3.5-2b", "name": "Smarts", "model_name": "Qwen3.5 2B", "tagline": "Smartest",
        "for": "8 GB laptops and up, when you can wait a little longer",
        "repo": "unsloth/Qwen3.5-2B-GGUF", "revision": "f6d5376be1edb4d416d56da11e5397a961aca8ae",
        "model": "Qwen3.5-2B-Q4_K_M.gguf", "mmproj": "mmproj-F16.gguf",
        "sha256": {"Qwen3.5-2B-Q4_K_M.gguf": "aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223",
                   "mmproj-F16.gguf": "7035e9cb8d7c6a9681d07eef9a364783e86ea4cd73faab2eabb4f43a101830c7"},
        "download_gb": 1.95, "ram_gb": 2.3, "speed": 3, "smarts": 5, "slides": 5,
        "writing": "about 5–10 words a second", "picture": "about 15–35 seconds to look at a slide",
        "facts": ["Best at reading slides, documents, charts and maths in pictures",
                  "Much smarter than today's MrSOLIS (about 70% better on knowledge tests)",
                  "Newest (2026)"],
        "licence": "Apache 2.0", "sees": True, "recommended": True,
    },
]
BY_ID = {b["id"]: b for b in CATALOG}


# CUSTOM-Kx: the leaner picture reader made on this computer from the downloaded one (backend/kx.py) — Smarts'
# 637 -> 345 MB of RAM with the same slide reading (measured 2026-10-24). LUNAR_KX=0 uses the download as is.
KX_MMPROJ = "mmproj-Kx-Q8_0.gguf"


def _files(b):
    d = os.path.join(BRAIN_DIR, b["id"])
    kx_path = os.path.join(d, KX_MMPROJ)
    use_kx = os.environ.get("LUNAR_KX", "1") != "0" and os.path.isfile(kx_path)
    return os.path.join(d, b["model"]), kx_path if use_kx else os.path.join(d, b["mmproj"])


def kx_upgrade(bid: str) -> bool:
    """Make the brain's leaner picture reader, once (about 13 s for Smarts). True when it is there."""
    b = BY_ID.get(bid)
    if not b or not b.get("sees") or os.environ.get("LUNAR_KX", "1") == "0":
        return False
    d = os.path.join(BRAIN_DIR, bid)
    src, dst = os.path.join(d, b["mmproj"]), os.path.join(d, KX_MMPROJ)
    if os.path.isfile(dst):
        return True
    if not os.path.isfile(src):
        return False
    try:
        from backend import kx
        kx.convert_mmproj(src, dst)
        return True
    except Exception:
        try:
            os.remove(dst + ".part")
        except OSError:
            pass
        return False


def _kx_tidy(b):
    """The engine has started with the leaner reader: free the 16-bit download's disk — only when the student's
    settings allow it (LUNAR_KX_TIDY=1). Off by default: on 2026-10-24 this deleted the user's 16-bit readers
    without asking, and that is the user's call."""
    if os.environ.get("LUNAR_KX_TIDY") != "1":
        return
    d = os.path.join(BRAIN_DIR, b["id"])
    if _files(b)[1] == os.path.join(d, KX_MMPROJ):
        try:
            os.remove(os.path.join(d, b["mmproj"]))
        except OSError:
            pass


def installed(bid: str) -> bool:
    b = BY_ID.get(bid)
    return bool(b) and all(os.path.isfile(p) for p in _files(b))


def installed_ids() -> list:
    return [b["id"] for b in CATALOG if installed(b["id"])]


# ══════════════════════════════════════════════════════════════════════
#   the llama-server sidecar
# ══════════════════════════════════════════════════════════════════════
def server_exe():
    """llama-server.exe: LUNAR_LLAMA_SERVER, else the pinned build next to the models."""
    env = os.environ.get("LUNAR_LLAMA_SERVER")
    if env and os.path.isfile(env):
        return env
    name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    base = os.path.dirname(MODEL_DIR)
    for d in (os.path.join(base, "runtime", "llama.cpp"), os.path.join(base, "llama.cpp")):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def _threads() -> int:
    env = os.environ.get("LUNAR_NUM_THREAD")
    if env and env.isdigit():
        return int(env)
    return max(2, min(8, (os.cpu_count() or 4) // 2))      # about the physical cores


# CUSTOM-Kx memory flags (finetune/kx, measured 2026-10-24 on an i5-13420H; see reports/CUSTOM-Kx initial report.md):
# - the engine's RAM prompt cache defaults to 8 GB: in a 20-slide session Speedy grew 1.3 -> 3.2 GB (~100 MB a
#   slide) and kept going. Capped at 256 MB it levels off at 1.46 GB, with the same speed — a few recent
#   states stay for chat <-> quiz-writer switches;
# - repacking copies the weights into private RAM while their file pages stay mapped: Speedy 209 MB, a 4B
#   brain 1.8 GB. Without it Speedy writes as fast or faster (26.5 vs 25 tok/s);
# - lazy mode leaves a brain's per-layer word tables (Gemma 4) on disk, read a row at a time.
KX_FLAGS = ["--cache-ram", os.environ.get("LUNAR_CACHE_RAM", "256"), "--no-repack", "--lazy-mode", "on"]


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _bind_to_us(proc):
    """Windows: the server dies with the backend (a job object) and isn't slowed by EcoQoS."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32")
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class EXT(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        job = k32.CreateJobObjectW(None, None)
        info = EXT()
        info.Basic.LimitFlags = 0x2000                       # KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        k32.AssignProcessToJobObject(job, wintypes.HANDLE(int(proc._handle)))

        class PPTS(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]
        st = PPTS(1, 0x1, 0x0)                               # execution-speed throttling off
        k32.SetProcessInformation(wintypes.HANDLE(int(proc._handle)), 4, ctypes.byref(st), ctypes.sizeof(st))
        return job                                           # keep the handle alive as long as we live
    except Exception:
        return None


class _Server:
    def __init__(self):
        self.proc = None
        self.port = None
        self.brain = None
        self.state = "off"           # off | starting | ready | error
        self.error = ""
        self._job = None
        self._lock = threading.Lock()
        self._starting = threading.Lock()   # one start at a time: the warm-up and a first chat must not race
        self.speed = {}              # brain id -> last measured {"gen": tok/s, "prompt": tok/s}
        # The engine answers only us (hardening, 2026-10-29): a key made for this run, so no website (llama-server
        # allows any origin) and no other program on the computer can use it.
        self.key = secrets.token_urlsafe(24)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.key}"}

    def stop(self):
        with self._lock:
            p, self.proc = self.proc, None
            self.state, self.brain = "off", None
        if p and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=10)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

    def start(self, bid: str):
        """Start (or switch to) a brain. Blocking until it answers /health, or fails."""
        with self._starting:
            return self._start(bid)

    def _start(self, bid: str):
        b = BY_ID.get(bid)
        exe = server_exe()
        if not b or not installed(bid) or not exe:
            self.state, self.error = "error", ("The brain isn't downloaded yet." if b else "Unknown brain.") \
                if exe else "The AI engine (llama-server) is missing."
            return False
        if self.brain == bid and self.proc and self.proc.poll() is None and self.state == "ready":
            return True
        self.stop()
        self.state, self.error = "starting", ""
        kx_upgrade(bid)                         # the first start after a download (or this update): ~13 s, once
        model, mmproj = _files(b)
        port = _free_port()
        os.makedirs(os.path.join(DATA_DIR, "logs"), exist_ok=True)
        log = os.path.join(DATA_DIR, "logs", "brain-server.log")
        args = [exe, "-m", model, "--mmproj", mmproj, "--host", "127.0.0.1", "--port", str(port),
                "-c", os.environ.get("LUNAR_NUM_CTX", "8192"), "-t", str(_threads()), "-ngl", "0",
                "-np", "1", "--reasoning", "off", "--no-webui", "--jinja", "--api-key", self.key,
                "--image-max-tokens", os.environ.get("LUNAR_IMAGE_TOKENS", "768"),
                *KX_FLAGS, "--log-file", log]
        with self._lock:
            self.state, self.error, self.brain, self.port = "starting", "", bid, port
            try:
                self.proc = subprocess.Popen(args, cwd=os.path.dirname(exe), stdin=subprocess.DEVNULL,
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                             creationflags=0x08000000 if sys.platform == "win32" else 0)
            except Exception as e:
                self.state, self.error = "error", f"Couldn't start the AI engine: {e}"
                return False
            self._job = _bind_to_us(self.proc)
        deadline = time.time() + 180
        while time.time() < deadline:
            if self.proc is None or self.proc.poll() is not None:
                self.state, self.error = "error", "The AI engine stopped while loading the brain (see logs/brain-server.log)."
                return False
            try:
                r = httpx.get(self.url + "/health", timeout=2, headers=self.headers)
                if r.status_code == 200:
                    self.state = "ready"
                    _kx_tidy(b)                 # it loaded with the leaner reader: free the 16-bit one's disk
                    return True
            except Exception:
                pass
            time.sleep(0.4)
        self.state, self.error = "error", "The AI engine took too long to load the brain."
        self.stop()
        return False


SERVER = _Server()


CHOICE = None          # the student's pick (Settings "brain"); main.py keeps this in step


def selected() -> str:
    """The brain to use: the student's choice, else the recommended / any installed one."""
    choice = CHOICE
    if choice and installed(choice):
        return choice
    have = installed_ids()
    if not have:
        return ""
    rec = next((b["id"] for b in CATALOG if b.get("recommended") and b["id"] in have), None)
    return rec or have[-1]


def online() -> bool:
    """True when the student's own AI account thinks for MrSOLIS (cloud.py, Settings → Brain → Online brain)."""
    return cloud.on()


def local_ok() -> bool:
    """A brain is installed on this computer and the engine exists."""
    return bool(selected()) and server_exe() is not None


def active() -> bool:
    """True when chat should go to a brain: the online one, or the one on this computer."""
    return online() or local_ok()


def local_sees() -> bool:
    b = BY_ID.get(selected())
    return bool(b and b.get("sees")) and local_ok()


def sees() -> bool:
    return cloud.sees() if online() else local_sees()


def _for_local(messages):
    """The online brain couldn't answer and this computer's brain takes over: a brain that can't see gets the words."""
    if local_sees():
        return messages
    return cloud._text_only(messages)


_start_lock = asyncio.Lock()


async def ensure_ready() -> str:
    """Start the selected brain if it isn't running; returns its base URL."""
    bid = selected()
    if SERVER.state == "ready" and SERVER.brain == bid and SERVER.proc and SERVER.proc.poll() is None:
        return SERVER.url
    async with _start_lock:
        if not (SERVER.state == "ready" and SERVER.brain == bid and SERVER.proc and SERVER.proc.poll() is None):
            ok = await asyncio.to_thread(SERVER.start, bid)
            if not ok:
                from backend.local_llm import LocalLLMError
                raise LocalLLMError(SERVER.error or "The brain couldn't start.")
    return SERVER.url


def warm():
    """At startup: load the brain in the background so the first lesson doesn't wait for it."""
    bid = selected()
    if online():                     # the online brain needs no loading; this one starts only if it's needed
        return
    if bid and server_exe():
        threading.Thread(target=SERVER.start, args=(bid,), daemon=True, name="brain-warm").start()


_SAMPLE = {"top_p": 0.8, "top_k": 20, "min_p": 0.0, "presence_penalty": 1.5}   # Qwen3.5 non-thinking advice


def _payload(messages, temperature, max_tokens, stream, json_mode=False, schema=None, grammar=None):
    p = {"messages": messages, "temperature": temperature, "stream": stream,
         "max_tokens": max_tokens or 768, **_SAMPLE}
    if stream:
        p["stream_options"] = {"include_usage": True}
        p["timings_per_token"] = False
    if schema:                     # llama-server turns the schema into a grammar: the reply is always valid
        p["response_format"] = {"type": "json_schema", "json_schema": {"name": "reply", "schema": schema}}
    elif json_mode:
        p["response_format"] = {"type": "json_object"}
    elif grammar:                  # a grammar of our own (GBNF): the class board's BOARD: / SAY: lines (boardclass.py)
        p["grammar"] = grammar
    return p


async def chat(messages, *, temperature=0.7, max_tokens=None, json_mode=False, schema=None, timeout=900.0) -> str:
    from backend.local_llm import LocalLLMError
    if online():
        try:
            return await cloud.chat(messages, temperature=temperature, max_tokens=max_tokens,
                                    json_mode=json_mode, schema=schema)
        except cloud.CloudError as e:
            if not (e.local_ok and local_ok()):
                raise LocalLLMError(str(e)) from e
            cloud.note(False, str(e), fallback=True)     # offline-first: this computer's brain answers instead
            messages = _for_local(messages)
    url = await ensure_ready()
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=SERVER.headers) as client:
            r = await client.post(url + "/v1/chat/completions",
                                  json=_payload(messages, temperature, max_tokens, False, json_mode, schema))
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise LocalLLMError(f"The brain failed: {e}") from e
    _note_speed(data.get("timings"))
    return ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "") or ""


async def chat_stream(messages, *, temperature=0.7, max_tokens=None, timeout=900.0, info=None, grammar=None):
    from backend.local_llm import LocalLLMError
    if online():
        produced = False
        try:
            async for piece in cloud.chat_stream(messages, temperature=temperature, max_tokens=max_tokens, info=info):
                produced = True
                yield piece
            return
        except cloud.CloudError as e:
            if produced or not (e.local_ok and local_ok()):
                raise LocalLLMError(str(e)) from e
            cloud.note(False, str(e), fallback=True)     # offline-first: this computer's brain answers instead
            messages = _for_local(messages)
    url = await ensure_ready()
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=SERVER.headers) as client:
            async with client.stream("POST", url + "/v1/chat/completions",
                                     json=_payload(messages, temperature, max_tokens, True, grammar=grammar)) as r:
                if r.status_code >= 400:
                    body = (await r.aread()).decode("utf-8", "ignore")[:300]
                    raise LocalLLMError(f"The brain returned an error: {r.status_code} {body}")
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("timings"):
                        _note_speed(obj["timings"])
                    for ch in obj.get("choices") or []:
                        if ch.get("finish_reason") and info is not None:
                            info["finish"] = ch["finish_reason"]      # "stop" = done, "length" = ran out
                        piece = (ch.get("delta") or {}).get("content")
                        if piece:
                            yield piece
    except httpx.HTTPError as e:
        raise LocalLLMError(f"The brain failed: {e}") from e


def _note_speed(t):
    """Keep the speeds this computer really manages, for the card ("measured on this computer")."""
    if not t or not SERVER.brain:
        return
    gen, pp, n = t.get("predicted_per_second"), t.get("prompt_per_second"), t.get("predicted_n") or 0
    if gen and n >= 20:
        SERVER.speed[SERVER.brain] = {"gen": round(gen, 1), "prompt": round(pp or 0, 1)}


# ══════════════════════════════════════════════════════════════════════
#   downloads (once per brain, resumable)
# ══════════════════════════════════════════════════════════════════════
DOWNLOAD = {"id": None, "done": 0, "total": 0, "state": "idle", "error": "", "cancel": False}


class _Damaged(Exception):
    """A downloaded file isn't the one we checked: its SHA-256 differs from the card's."""


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(bid: str):
    b = BY_ID[bid]
    d = os.path.join(BRAIN_DIR, bid)
    os.makedirs(d, exist_ok=True)
    # Pinned (hardening, 2026-10-29): a fixed revision of the repo, so the files can't change under us, and each
    # file's SHA-256, checked before it is used — a damaged or swapped file is thrown away, never loaded.
    rev = b.get("revision", "main")
    jobs = [(b["mmproj"], f"{HF}/{b['repo']}/resolve/{rev}/{b['mmproj']}"),
            (b["model"], b.get("model_url") or f"{HF}/{b['repo']}/resolve/{rev}/{b['model']}")]
    if os.path.isfile(os.path.join(d, KX_MMPROJ)):           # the leaner reader is already made from it
        jobs = jobs[1:]
    DOWNLOAD.update(id=bid, done=0, total=0, state="downloading", error="", cancel=False)
    try:
        sizes = []
        with httpx.Client(follow_redirects=True, timeout=60) as c:
            for name, url in jobs:
                r = c.head(url)
                sizes.append(int(r.headers.get("content-length") or r.headers.get("x-linked-size") or 0))
        DOWNLOAD["total"] = sum(sizes)
        done_before = 0
        for (name, url), size in zip(jobs, sizes):
            final = os.path.join(d, name)
            if os.path.isfile(final) and (not size or os.path.getsize(final) == size):
                done_before += os.path.getsize(final)
                DOWNLOAD["done"] = done_before
                continue
            part = final + ".part"
            # Students' connections drop (the user's did, at 311 of 533 MB): carry on from where it
            # stopped, by itself, a few times with growing pauses, before asking them to press Download.
            for attempt in range(6):
                have = os.path.getsize(part) if os.path.isfile(part) else 0
                if size and have >= size:
                    break
                headers = {"Range": f"bytes={have}-"} if have else {}
                try:
                    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, read=120)) as c:
                        with c.stream("GET", url, headers=headers) as r:
                            if r.status_code == 200 and have:        # the server ignored Range: start over
                                have = 0
                            r.raise_for_status()
                            with open(part, "ab" if have else "wb") as f:
                                for chunk in r.iter_bytes(1 << 20):
                                    if DOWNLOAD["cancel"]:
                                        DOWNLOAD.update(state="cancelled")
                                        return
                                    f.write(chunk)
                                    have += len(chunk)
                                    DOWNLOAD["done"] = done_before + have
                    break
                except httpx.TransportError:
                    if attempt == 5 or DOWNLOAD["cancel"]:
                        raise
                    time.sleep(min(30, 3 * 2 ** attempt))          # 3, 6, 12, 24, 30 s
            if size and os.path.getsize(part) != size:
                raise IOError("a file came down incomplete — try again")
            want = (b.get("sha256") or {}).get(name)
            if want and _sha256(part) != want:
                os.remove(part)
                raise _Damaged(name)
            os.replace(part, final)
            done_before += os.path.getsize(final)
        for f in os.listdir(d):                     # an older version of this brain: free its space
            if f.endswith((".gguf", ".part")) and f not in (b["model"], b["mmproj"], KX_MMPROJ):
                try:
                    os.remove(os.path.join(d, f))
                except OSError:
                    pass
        DOWNLOAD.update(state="done", done=DOWNLOAD["total"])
    except httpx.HTTPStatusError as e:              # never show the URL: it names the real model
        DOWNLOAD.update(state="error", error=f"the download server said {e.response.status_code}")
    except _Damaged:
        DOWNLOAD.update(state="error", error="a file came down damaged, so MrSOLIS threw it away")
    except (httpx.TransportError, OSError) as e:
        DOWNLOAD.update(state="error", error="the connection dropped" if isinstance(e, httpx.TransportError)
                        else "this computer couldn't save the file (is the disk full?)")
    except Exception:
        DOWNLOAD.update(state="error", error="something went wrong")


def start_download(bid: str) -> bool:
    if bid not in BY_ID or DOWNLOAD["state"] == "downloading":
        return False
    threading.Thread(target=_download, args=(bid,), daemon=True, name="brain-download").start()
    return True


def remove(bid: str):
    if SERVER.brain == bid:
        SERVER.stop()
    shutil.rmtree(os.path.join(BRAIN_DIR, bid), ignore_errors=True)


def status() -> dict:
    sel = selected()
    cards = []
    for b in CATALOG:
        card = {k: v for k, v in b.items() if k not in ("repo", "model", "mmproj", "model_name", "model_url", "revision", "sha256")}
        card["installed"] = installed(b["id"])
        card["selected"] = b["id"] == sel
        card["measured"] = SERVER.speed.get(b["id"])
        cards.append(card)
    return {"selected": sel, "engine": bool(server_exe()), "state": SERVER.state, "error": SERVER.error,
            "running": SERVER.brain, "cards": cards,
            "download": {k: v for k, v in DOWNLOAD.items() if k != "cancel"}}
