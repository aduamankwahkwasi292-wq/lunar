"""
On-device voice for MrSOLIS — hearing and speaking, no network.

    hearing   NVIDIA Parakeet TDT 110M (English)   sherpa-onnx OfflineRecognizer (NeMo transducer)
    turns     Silero VAD                           tells when the student starts / stops talking
    speaking  Supertonic 2, male voice M2          sherpa-onnx OfflineTts

The models live in ``<model dir>/voice/`` (scripts/fetch_models.py downloads them and
the installer bundles them). Licences: Parakeet CC BY 4.0 (credit NVIDIA), Supertonic
OpenRAIL-M (Supertone), Silero MIT.

Chosen on 2026-10-17 by testing on the student's own (Ghanaian-accented) voice: Parakeet
heard every test sentence right where Moonshine Base turned "Newton's second law" into
"new things, I can love"; Supertonic starts speaking in ~0.5 s (Pocket TTS 3.3 s, Kitten 5.7 s).

``Listener`` turns a stream of 16 kHz float32 microphone audio into events:
``speech_start`` when the student starts talking, ``partial`` text while they talk,
and ``final`` text when they stop. ``speak()`` turns a sentence into WAV bytes.
"""

import io
import os
import re
import glob
import threading
import wave

import numpy as np

from backend.local_llm import MODEL_DIR

VOICE_DIR = os.environ.get("LUNAR_VOICE_DIR") or os.path.join(MODEL_DIR, "voice")
SAMPLE_RATE = 16000                    # what the microphone stream is sent as
_THREADS = max(1, min(4, (os.cpu_count() or 4) // 2))


def _first(pattern: str):
    hits = sorted(glob.glob(os.path.join(VOICE_DIR, pattern)))
    return hits[0] if hits else None


def _paths() -> dict:
    stt = _first("sherpa-onnx-nemo-parakeet*")
    tts = _first("sherpa-onnx-supertonic-tts-*")
    j = lambda d, f: d and os.path.join(d, f)
    return {
        "stt_encoder": j(stt, "encoder.int8.onnx"),
        "stt_decoder": j(stt, "decoder.int8.onnx"),
        "stt_joiner": j(stt, "joiner.int8.onnx"),
        "stt_tokens": j(stt, "tokens.txt"),
        "tts_duration": j(tts, "duration_predictor.int8.onnx"),
        "tts_encoder": j(tts, "text_encoder.int8.onnx"),
        "tts_estimator": j(tts, "vector_estimator.int8.onnx"),
        "tts_vocoder": j(tts, "vocoder.int8.onnx"),
        "tts_json": j(tts, "tts.json"),
        "tts_indexer": j(tts, "unicode_indexer.bin"),
        "tts_voices": j(tts, "voice.bin"),
        "vad": os.path.join(VOICE_DIR, "silero_vad.onnx"),
    }


def _ok(*paths) -> bool:
    return all(p and os.path.exists(p) for p in paths)


def status() -> dict:
    p = _paths()
    hear = _ok(p["stt_encoder"], p["stt_decoder"], p["stt_joiner"], p["stt_tokens"], p["vad"])
    speak = _ok(*(p[k] for k in p if k.startswith("tts_")))
    return {"hear": hear, "speak": speak}


# ── models (loaded once, on first use) ────────────────────────────────
_recognizer = None
_tts = None
_rec_lock = threading.Lock()
_tts_lock = threading.Lock()


def _get_recognizer():
    global _recognizer
    with _rec_lock:
        if _recognizer is None:
            import sherpa_onnx
            p = _paths()
            _recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=p["stt_encoder"], decoder=p["stt_decoder"], joiner=p["stt_joiner"],
                tokens=p["stt_tokens"], model_type="nemo_transducer", num_threads=_THREADS)
        return _recognizer


def _get_tts():
    global _tts
    with _tts_lock:
        if _tts is None:
            import sherpa_onnx
            p = _paths()
            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    supertonic=sherpa_onnx.OfflineTtsSupertonicModelConfig(
                        duration_predictor=p["tts_duration"], text_encoder=p["tts_encoder"],
                        vector_estimator=p["tts_estimator"], vocoder=p["tts_vocoder"],
                        tts_json=p["tts_json"], unicode_indexer=p["tts_indexer"],
                        voice_style=p["tts_voices"]),
                    num_threads=2))
            _tts = sherpa_onnx.OfflineTts(config)
        return _tts


def warm():
    """Load the models in the background so the first word isn't slow."""
    st = status()
    try:
        if st["hear"]:
            _get_recognizer()
        if st["speak"]:
            _get_tts()
    except Exception:
        pass


# ── hearing ───────────────────────────────────────────────────────────
_MAX_PIECE = int(20 * SAMPLE_RATE)     # keeps memory and wait time bounded on very long turns


def _pieces(samples: np.ndarray) -> list:
    """Split long audio into < 20 s pieces, cutting at the quietest moment (a pause between words)."""
    out, start, n = [], 0, len(samples)
    while n - start > _MAX_PIECE:
        cut = quiet_cut(samples, start + _MAX_PIECE - int(2.5 * SAMPLE_RATE), start + _MAX_PIECE)
        out.append(samples[start:cut])
        start = cut
    out.append(samples[start:])
    return out


def transcribe(samples: np.ndarray) -> str:
    """Text for 16 kHz float32 mono audio (any length)."""
    if samples is None or len(samples) < SAMPLE_RATE * 0.25:
        return ""
    samples = np.asarray(samples, dtype=np.float32)
    # trim silent edges (long stretches of pure silence make the model return nothing)
    loud = np.nonzero(np.abs(samples) > max(1e-3, 0.02 * float(np.abs(samples).max())))[0]
    if not len(loud):
        return ""
    pad = int(0.25 * SAMPLE_RATE)
    samples = samples[max(0, loud[0] - pad): loud[-1] + pad]
    texts = [recognize(piece) for piece in _pieces(samples) if len(piece) >= SAMPLE_RATE * 0.2]
    text = re.sub(r"\s+", " ", " ".join(texts)).strip()
    return text if re.search(r"[A-Za-z0-9]", text) else ""


def recognize(piece: np.ndarray) -> str:
    """Text for one piece of 16 kHz float32 audio up to ~20 s (longer pieces: `transcribe`)."""
    rec = _get_recognizer()
    with _rec_lock:
        stream = rec.create_stream()
        stream.accept_waveform(SAMPLE_RATE, np.asarray(piece, dtype=np.float32))
        rec.decode_stream(stream)
        return (stream.result.text or "").strip()


def quiet_cut(samples: np.ndarray, lo: int, hi: int) -> int:
    """The quietest moment between samples lo and hi (a pause between words) — where to cut long audio."""
    frame = SAMPLE_RATE // 10                                 # 100 ms
    energy = [float(np.mean(samples[i:i + frame] ** 2)) for i in range(lo, hi - frame, frame // 2)]
    return lo + int(np.argmin(energy)) * (frame // 2) + frame // 2 if energy else hi


def _looks_looped(text: str, seconds: float) -> bool:
    """Cut-off audio can make the model repeat itself ("…for you ask not what your country…")."""
    words = re.findall(r"[A-Za-z0-9']+", text.lower())
    if len(words) > seconds * 4 + 3:                 # nobody says >4 words a second
        return True
    for n in (3, 4, 5):                               # the same phrase twice in a row
        for i in range(len(words) - 2 * n + 1):
            if words[i:i + n] == words[i + n:i + 2 * n]:
                return True
    return False


class Listener:
    """One microphone session: feed audio, get speech_start / partial / final events."""

    WINDOW = 512                       # Silero works on 32 ms windows at 16 kHz
    PRE_ROLL = 31                      # ~1 s kept from before speech is detected: the detector
                                       # notices ~0.3-0.5 s late, and 0.3 s lost "What is the…"
    PARTIAL_EVERY = int(1.2 * SAMPLE_RATE)

    def __init__(self, pause: float = 0.6):
        import sherpa_onnx
        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = _paths()["vad"]
        cfg.silero_vad.threshold = 0.5
        cfg.silero_vad.min_silence_duration = pause       # how long a pause ends a sentence
        cfg.silero_vad.min_speech_duration = 0.25
        cfg.silero_vad.max_speech_duration = 25
        cfg.silero_vad.window_size = self.WINDOW
        cfg.sample_rate = SAMPLE_RATE
        cfg.num_threads = 1
        self.vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)
        self.pending = np.zeros(0, dtype=np.float32)
        self.recent = []                  # last few windows (pre-roll)
        self.speech = []                  # windows of the sentence being spoken
        self.speaking = False
        self.since_partial = 0

    def feed(self, samples: np.ndarray, partials: bool = True) -> list:
        """Process new audio. `partials=False` skips the words-so-far pass (when running behind)."""
        events = []
        self.pending = np.concatenate([self.pending, samples.astype(np.float32, copy=False)])
        while len(self.pending) >= self.WINDOW:
            win, self.pending = self.pending[:self.WINDOW], self.pending[self.WINDOW:]
            self.vad.accept_waveform(win)
            now = self.vad.is_speech_detected()
            if now and not self.speaking:
                self.speaking = True
                self.speech = list(self.recent)
                self.since_partial = 0
                events.append({"type": "speech_start"})
            if self.speaking:
                self.speech.append(win)
                self.since_partial += len(win)
            self.recent = (self.recent + [win])[-self.PRE_ROLL:]
            while not self.vad.empty():               # a finished sentence
                seg = np.asarray(self.vad.front.samples, dtype=np.float32)
                self.vad.pop()
                # our own copy keeps a short lead-in before the first word, which the
                # detector's trimmed segment can clip ("What is…" → "is…")
                heard = np.concatenate(self.speech) if self.speech else seg
                text = transcribe(heard)
                if text:
                    events.append({"type": "final", "text": text})
                else:
                    events.append({"type": "noise"})
                self.speaking = False
                self.speech = []
        # words so far, while the student is still talking
        if partials and self.speaking and self.since_partial >= self.PARTIAL_EVERY \
                and len(self.speech) * self.WINDOW > SAMPLE_RATE * 0.6:
            self.since_partial = 0
            audio = np.concatenate(self.speech)
            text = transcribe(audio)
            if text and not _looks_looped(text, len(audio) / SAMPLE_RATE):
                events.append({"type": "partial", "text": text})
        return events

    def finish(self) -> list:
        """The student stopped the mic mid-sentence: hear what's been said so far, properly."""
        if not self.speaking or not self.speech:
            return []
        text = transcribe(np.concatenate(self.speech))
        self.speaking, self.speech = False, []
        return [{"type": "final", "text": text}] if text else []


# ── speaking ──────────────────────────────────────────────────────────
_UNITS = [                                     # after a number: "10 N" → "10 newtons"
    (r"m/s(?:²|\^2)", "metres per second squared"), (r"m/s", "metres per second"),
    (r"km/h", "kilometres per hour"), (r"kN", "kilonewtons"), (r"N", "newtons"), (r"kJ", "kilojoules"),
    (r"J", "joules"), (r"kW", "kilowatts"), (r"W", "watts"), (r"Hz", "hertz"), (r"kPa", "kilopascals"),
    (r"Pa", "pascals"), (r"mA", "milliamps"), (r"kΩ", "kilohms"), (r"ms", "milliseconds"),
    (r"km", "kilometres"), (r"cm", "centimetres"), (r"mm", "millimetres"), (r"m", "metres"),
    (r"s", "seconds"),
]
_GREEK = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon", "ζ": "zeta", "η": "eta",
          "θ": "theta", "κ": "kappa", "λ": "lambda", "ν": "nu", "ξ": "xi", "ρ": "rho", "σ": "sigma", "τ": "tau",
          "φ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega", "Γ": "Gamma", "Θ": "Theta", "Λ": "Lambda",
          "Σ": "Sigma", "Φ": "Phi"}           # Δ, π, Ω and μ have their own readings below
_SAY = [(r"(?<=\d)\s*" + u + r"(?![\w/])", " " + w) for u, w in _UNITS] + [
    (r"\*\*|__|`+", ""),                       # markdown emphasis / code
    (r"^\s{0,3}#{1,6}\s*", ""),                # headings
    (r"^\s*[-•*]\s+", ""),                     # bullets
    (r"\\[()\[\]]", " "),                      # LaTeX maths brackets \( \) \[ \]
    (r"_\{([^{}]*)\}", r"_\1"), (r"\^\{([^{}]*)\}", r"^\1"),          # P_{out} → P_out, x^{2} → x^2
    (r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r" \1 over \2 "),
    (r"\\(?:var)?(" + "|".join([*_GREEK.values(), "Delta", "Omega", "Pi", "pi", "mu"]) + r")(?![A-Za-z])", r" \1 "),   # \eta_0 → eta 0
    (r"\\[a-zA-Z]+|[{}$]", " "),               # stray LaTeX
    ("[" + "".join(_GREEK) + "]", lambda m: " " + _GREEK[m.group()] + " "),   # η → eta
    (r"(\w)_(\w)", r"\1 \2"),                  # F_net → F net
    (r"_", " "),
    (r"\^2\b|²", " squared"), (r"\^3\b|³", " cubed"), (r"\^(\d+)", r" to the power \1"),
    (r"×|·|⋅", " times "), (r"÷", " divided by "), (r"≈", " is about "),
    (r"≤", " is at most "), (r"≥", " is at least "), (r"≠", " is not equal to "),
    (r"→|⇒", " gives "), (r"√", " the square root of "), (r"Δ", " delta "), (r"π", " pi "),
    (r"Ω", " ohms "), (r"(?<=\d)\s*[μµ](?=[A-Za-z])", " micro "), (r"[μµ]", " mu "),   # 5 μF / μ = 0.3
    (r"°", " degrees "), (r"%", " percent "),
    (r"(?<=[A-Za-z])/(?=[A-Za-z])", " per "),  # m/s → m per s
    (r"(?<=\d)\s*/\s*(?=\d)", " over "),
    (r"\s=\s|=", " equals "), (r"\s\+\s", " plus "), (r"(?<=\d)\s-\s(?=\d)", " minus "),
    (r"\s+", " "), (r" ([,.;:!?])", r"\1"),
]


def speakable(text: str) -> str:
    """Board text → something a voice can read aloud."""
    out = text or ""
    for pattern, repl in _SAY:
        out = re.sub(pattern, repl, out, flags=re.M)
    return out.strip()


VOICE_ID = 6        # Supertonic speakers 0-4 are female F1-F5, 5-9 male M1-M5; the student picked M2
BASE_SPEED = 1.05   # Supertonic's own pace is a touch slow for a tutor
STEPS = 5           # quality/speed trade-off: 5 steps ≈ 10× faster than real time on an i5-13420H


def speak(text: str, speed: float = 1.0) -> bytes:
    """WAV bytes (16-bit mono) of the voice reading `text`."""
    import sherpa_onnx
    say = speakable(text)
    if not re.search(r"[A-Za-z0-9]", say):
        return b""
    tts = _get_tts()
    gen = sherpa_onnx.GenerationConfig()
    gen.sid, gen.num_steps = VOICE_ID, STEPS
    gen.speed = BASE_SPEED * max(0.6, min(1.6, speed))
    gen.extra["lang"] = "en"
    with _tts_lock:
        audio = tts.generate(say[:600], gen)
    pcm = np.clip(np.asarray(audio.samples, dtype=np.float32), -1, 1)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(audio.sample_rate)
        wf.writeframes((pcm * 32767).astype("<i2").tobytes())
    return buf.getvalue()
