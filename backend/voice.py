"""
Local voice engine for Lunar AI — on-device STT and TTS (replaces Deepgram).

  STT : faster-whisper ("base", int8 on CPU). Reads 16 kHz mono WAV bytes.
  TTS : Piper (neural, natural) when available, with an automatic fallback to
        the OS speech engine (pyttsx3 / Windows SAPI) so the voice system
        always works even if Piper isn't installed yet.

Everything runs locally. No API keys, no network.
"""

import io
import os
import wave
import tempfile
import threading

import numpy as np

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
PIPER_DIR = os.path.join(MODELS_DIR, "piper")

WHISPER_MODEL = os.environ.get("LUNAR_WHISPER_MODEL", "base")
PIPER_VOICE = os.environ.get("LUNAR_PIPER_VOICE", "en_US-amy-medium")

_whisper_model = None
_whisper_lock = threading.Lock()
_piper_voice = None
_piper_tried = False
_piper_lock = threading.Lock()


# ======================================================================
# Speech-to-text
# ======================================================================
def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        with _whisper_lock:
            if _whisper_model is None:
                from faster_whisper import WhisperModel

                _whisper_model = WhisperModel(
                    WHISPER_MODEL, device="cpu", compute_type="int8"
                )
    return _whisper_model


def _read_wav(wav_bytes: bytes) -> np.ndarray:
    """Decode WAV bytes to a mono float32 array at 16 kHz (no ffmpeg needed)."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        framerate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    if sample_width == 2:
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sample_width == 1:
        audio = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sample_width}")

    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)

    if framerate != 16000 and audio.size:
        # Simple linear resample to 16 kHz.
        target_len = int(round(audio.size * 16000 / framerate))
        if target_len > 0:
            audio = np.interp(
                np.linspace(0, audio.size - 1, target_len),
                np.arange(audio.size),
                audio,
            ).astype(np.float32)

    return audio


def transcribe(wav_bytes: bytes) -> str:
    """Transcribe WAV audio bytes to text using local Whisper."""
    audio = _read_wav(wav_bytes)
    if audio.size == 0:
        return ""
    model = _get_whisper()
    segments, _info = model.transcribe(
        audio, language="en", vad_filter=True, beam_size=1
    )
    return " ".join(seg.text.strip() for seg in segments).strip()


# ======================================================================
# Text-to-speech
# ======================================================================
def _get_piper():
    """Load the Piper voice once; return None if unavailable."""
    global _piper_voice, _piper_tried
    if _piper_tried:
        return _piper_voice
    with _piper_lock:
        if _piper_tried:
            return _piper_voice
        _piper_tried = True
        try:
            from piper.voice import PiperVoice

            model_path = os.path.join(PIPER_DIR, f"{PIPER_VOICE}.onnx")
            config_path = model_path + ".json"
            if not os.path.exists(model_path):
                _piper_voice = None
            else:
                cfg = config_path if os.path.exists(config_path) else None
                _piper_voice = PiperVoice.load(model_path, config_path=cfg)
        except Exception:
            _piper_voice = None
    return _piper_voice


def _piper_to_wav(voice, text: str) -> bytes:
    """Synthesize with Piper across its several API generations -> WAV bytes."""
    sample_rate = getattr(getattr(voice, "config", None), "sample_rate", 22050)
    pcm = bytearray()

    # Newest API: synthesize() yields AudioChunk objects.
    try:
        produced = False
        for chunk in voice.synthesize(text):
            produced = True
            data = getattr(chunk, "audio_int16_bytes", None)
            if data is None and hasattr(chunk, "audio_float_array"):
                arr = (np.asarray(chunk.audio_float_array) * 32767).astype(np.int16)
                data = arr.tobytes()
            if data:
                pcm.extend(data)
            sr = getattr(chunk, "sample_rate", None)
            if sr:
                sample_rate = sr
        if produced and pcm:
            return _pcm_to_wav(bytes(pcm), sample_rate)
    except (AttributeError, TypeError):
        pass

    # Older API: synthesize_stream_raw() yields raw PCM bytes.
    if hasattr(voice, "synthesize_stream_raw"):
        pcm = bytearray()
        for data in voice.synthesize_stream_raw(text):
            pcm.extend(data)
        return _pcm_to_wav(bytes(pcm), sample_rate)

    # Oldest API: synthesize(text, wave_write_obj).
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        voice.synthesize(text, wf)
    return buf.getvalue()


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _sapi_to_wav(text: str) -> bytes:
    """Fallback TTS using the OS speech engine (pyttsx3 / Windows SAPI)."""
    import pyttsx3

    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        engine = pyttsx3.init()
        engine.setProperty("rate", 175)
        engine.save_to_file(text, tmp_path)
        engine.runAndWait()
        engine.stop()
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def synthesize(text: str) -> bytes:
    """Convert text to WAV audio bytes using Piper, falling back to SAPI."""
    text = (text or "").strip()
    if not text:
        return b""
    voice = _get_piper()
    if voice is not None:
        try:
            return _piper_to_wav(voice, text)
        except Exception:
            pass  # fall through to the OS engine
    return _sapi_to_wav(text)


def engine_status() -> dict:
    """Report which TTS/STT engines are active (for the status chip)."""
    return {
        "stt": f"faster-whisper:{WHISPER_MODEL}",
        "tts": "piper" if _get_piper() is not None else "system",
    }
