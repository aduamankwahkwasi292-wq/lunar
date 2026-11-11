"""
MrSOLIS's online brain (2026-11-11): the student's own AI account, used as MrSOLIS's brain.

MrSOLIS is offline-first. It thinks with a brain on this computer (brain.py). A student with an account at an AI
company can add an API key in Settings → Brain; MrSOLIS then thinks with that AI instead — the same lessons, answers,
quizzes, Interactive mode and maths engines (CUSTOM-Mx still does the arithmetic), only a stronger brain, and all of
it in MrSOLIS's own window. With no internet, or when the account is out of credit or over its limit, MrSOLIS goes
back to its own brain (brain.chat / brain.chat_stream do that, when a brain is installed here).

The companies (the user: "SUPPORT DEEPSEEK, OpenAI COMPATIBLE POINTS, ANTHROPIC, GEMINI, NVIDIA FOR NOW"):
  - OpenAI-style chat completions over httpx — the protocol MrSOLIS already speaks to llama-server: OpenAI, DeepSeek,
    Google Gemini (Google's OpenAI-compatible endpoint), NVIDIA (build.nvidia.com), and any other OpenAI-compatible
    server ("Other": OpenRouter, Groq, LM Studio, Ollama...).
  - Anthropic (Claude): the official Anthropic Python SDK (`anthropic`, AsyncAnthropic).
Subscriptions: Anthropic forbids Claude Free/Pro/Max plans in other apps (API keys only). ChatGPT Plus/Pro plans come
through OpenAI's "Sign in with ChatGPT" (backend/siwc.py, provider "chatgpt"), which a paid app may offer only once
OpenAI accepts it: until then siwc.enabled() is False and the provider isn't shown — see CLAUDE.md.

The key is kept in DATA_DIR/online-brain.json, sealed with Windows DPAPI (only this Windows account can open it). It
never goes to the page (only its last four characters), is never logged, and is sent only to its own company.
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import os
import re
import sys
import threading
import time
from contextvars import ContextVar
from urllib.parse import urlparse

import httpx

# ══════════════════════════════════════════════════════════════════════
#   the companies
# ══════════════════════════════════════════════════════════════════════
# kind: "openai" = chat completions at {base}/chat/completions and {base}/models; "anthropic" = the Anthropic SDK.
# sees: whether its models can look at pictures by default (the student can change it per model).
# effort: send reasoning_effort "low" (reasoning models think briefly: lessons stream sooner and cost less).
PROVIDERS = {
    "deepseek": {"name": "DeepSeek", "short": "DeepSeek", "kind": "openai", "base": "https://api.deepseek.com",
                 "keys": "https://platform.deepseek.com/api_keys", "sees": False, "effort": False,
                 "prefer": ["deepseek-chat"]},
    "openai": {"name": "OpenAI", "short": "OpenAI", "kind": "openai", "base": "https://api.openai.com/v1",
               "keys": "https://platform.openai.com/api-keys", "sees": True, "effort": True, "prefer": []},
    "chatgpt": {"name": "ChatGPT plan (Plus or Pro)", "short": "ChatGPT", "kind": "chatgpt", "base": "https://api.openai.com/v1",
                "keys": "", "sees": True, "effort": False, "prefer": []},
    "anthropic": {"name": "Anthropic (Claude)", "short": "Claude", "kind": "anthropic", "base": "https://api.anthropic.com",
                  "keys": "https://console.anthropic.com/settings/keys", "sees": True, "effort": True,
                  "prefer": ["claude-opus-5-5"]},
    "gemini": {"name": "Google Gemini", "short": "Gemini", "kind": "openai",
               "base": "https://generativelanguage.googleapis.com/v1beta/openai",
               "keys": "https://aistudio.google.com/apikey", "sees": True, "effort": True,
               "prefer": ["gemini-flash-latest", "gemini-2.5-flash"]},
    "nvidia": {"name": "NVIDIA", "short": "NVIDIA", "kind": "openai", "base": "https://integrate.api.nvidia.com/v1",
               "keys": "https://build.nvidia.com", "sees": False, "effort": False,
               "prefer": ["meta/llama-3.3-70b-instruct", "nvidia/llama-3.3-nemotron-super-49b-v1.5",
                          "deepseek-ai/deepseek-v3.1"]},
    "custom": {"name": "Other (OpenAI-compatible)", "short": "your server", "kind": "openai", "base": "",
               "keys": "", "sees": False, "effort": False, "prefer": []},
}
ORDER = ["deepseek", "openai", "chatgpt", "anthropic", "gemini", "nvidia", "custom"]

# "Think" (the button by the chat box): set for one request by main.py's _ThinkFlag, only on the student's own
# questions. The online model thinks harder: effort "medium" instead of "low", DeepSeek's reasoner, enable_thinking.
THINK: ContextVar = ContextVar("mrsolis_think", default=False)


def _siwc():
    try:
        from backend import siwc
    except ImportError:                       # the frozen app's flat layout
        import siwc
    return siwc


def _offered(pid: str) -> bool:
    """ChatGPT plans only once OpenAI has accepted MrSOLIS (siwc.ENABLED; dev runs: MRSOLIS_CHATGPT_PLAN=1)."""
    return pid in PROVIDERS and (pid != "chatgpt" or _siwc().enabled())

# Claude models that get Anthropic's server-side refusal fallback (another Claude model carries on, in the same
# call, if this one declines on safety grounds): Anthropic's guidance for these models.
_CLAUDE_FALLBACKS = {"claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}

# A model list holds much that can't chat (embeddings, voices, pictures, moderation...): leave those out.
_NOT_CHAT = re.compile(r"(?i)(embed|rerank|tts|whisper|transcri|dall-e|imagen|image-|-image|veo|moderation|"
                       r"realtime|audio|speech|retriev|reward|guard|safety|nemoretriever|parse|\bocr\b|"
                       r"computer-use|sora|davinci|babbage|aqa|clip|deplot|kosmos|paligemma|vila|cosmos|"
                       r"nv-embed|bge-|e5-|arctic-embed|-search-)")
# Models that look at pictures, by name (for companies whose models mostly don't).
_SEES_NAME = re.compile(r"(?i)(vision|-vl\b|-vl-|vlm|multimodal|omni|llama-4|gemma-3|pixtral|llava|"
                        r"phi-4-multimodal|nemotron-nano-vl|qwen2\.5-vl|qwen3-vl|gpt-4o|gpt-4\.1|gpt-5|gpt-6)")
# Reasoning models some servers let write their thinking into the reply (<think>…</think>).
_THINKS_NAME = re.compile(r"(?i)(\br1\b|-r1|reasoner|think|qwq|magistral|nemotron.*(super|ultra)|qwen3)")


class CloudError(RuntimeError):
    """The online brain couldn't answer. `local_ok`: the brain on this computer may answer instead (no internet,
    out of credit, over the limit, the company's trouble) — not for a refused key or an unknown model."""

    def __init__(self, message: str, local_ok: bool = False):
        super().__init__(message)
        self.local_ok = local_ok


# ══════════════════════════════════════════════════════════════════════
#   where it's kept, and the sealed key
# ══════════════════════════════════════════════════════════════════════
_CFG: dict | None = None
_LOCK = threading.Lock()
LAST = {"ok": None, "error": "", "when": 0.0, "fallback": False, "ms": 0, "code": ""}   # the last call, for the card


def _data_dir() -> str:
    try:
        from backend import brain as _b
    except ImportError:                       # the frozen app's flat layout
        import brain as _b
    return _b.DATA_DIR


def _path() -> str:
    return os.path.join(_data_dir(), "online-brain.json")


def _load() -> dict:
    global _CFG
    if _CFG is None:
        try:
            with open(_path(), encoding="utf-8") as f:
                _CFG = json.load(f)
        except (OSError, ValueError):
            _CFG = {}
        if not isinstance(_CFG, dict):
            _CFG = {}
        _CFG.setdefault("on", False)
        _CFG.setdefault("provider", "deepseek")
        if not isinstance(_CFG.get("providers"), dict):
            _CFG["providers"] = {}
    return _CFG


def _write():
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_CFG, f, indent=1)
    os.replace(tmp, _path())


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _ENTROPY = b"MrSOLIS online brain"

    def _dpapi(data: bytes, seal: bool) -> bytes:
        """Windows DPAPI: only this Windows account (on this computer) can open what it seals."""
        src = ctypes.create_string_buffer(data, len(data))
        ent = ctypes.create_string_buffer(_ENTROPY, len(_ENTROPY))
        blob_in = _Blob(len(data), ctypes.cast(src, ctypes.POINTER(ctypes.c_char)))
        blob_ent = _Blob(len(_ENTROPY), ctypes.cast(ent, ctypes.POINTER(ctypes.c_char)))
        blob_out = _Blob()
        fn = ctypes.windll.crypt32.CryptProtectData if seal else ctypes.windll.crypt32.CryptUnprotectData
        if not fn(ctypes.byref(blob_in), None, ctypes.byref(blob_ent), None, None, 0x01, ctypes.byref(blob_out)):
            raise OSError("DPAPI refused")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))
else:
    def _dpapi(data: bytes, seal: bool) -> bytes:      # other systems: the file is private to the user (0600)
        return data


def _seal(key: str) -> str:
    raw = key.encode("utf-8")
    if sys.platform == "win32":
        return "dpapi:" + base64.b64encode(_dpapi(raw, True)).decode("ascii")
    return "b64:" + base64.b64encode(raw).decode("ascii")


def _unseal(sealed: str) -> str:
    try:
        scheme, _, b64 = sealed.partition(":")
        data = base64.b64decode(b64)
        if scheme == "dpapi":
            data = _dpapi(data, False)
        return data.decode("utf-8")
    except Exception:                 # another Windows account, or a damaged file: the student types the key again
        return ""


def _prov(pid: str) -> dict:
    return _load()["providers"].setdefault(pid, {})


def _key(pid: str) -> str:
    sealed = _prov(pid).get("key")
    return _unseal(sealed) if sealed else ""


def _base(pid: str) -> str:
    if pid == "custom":
        return (_prov(pid).get("base") or "").rstrip("/")
    return PROVIDERS[pid]["base"]


def _base_ok(base: str) -> bool:
    """https anywhere; plain http only on this computer or the home/school network (a key must not cross the
    internet unencrypted)."""
    u = urlparse(base)
    if u.scheme == "https" and u.hostname:
        return True
    if u.scheme != "http" or not u.hostname:
        return False
    host = u.hostname
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


# ══════════════════════════════════════════════════════════════════════
#   state, for the Settings card (never the key itself)
# ══════════════════════════════════════════════════════════════════════
def provider() -> str:
    pid = _load().get("provider")
    return pid if _offered(pid) else "deepseek"


def model() -> str:
    return _prov(provider()).get("model", "")


def on() -> bool:
    """True when the student's online brain is switched on and has what it needs (a key, a model)."""
    c = _load()
    if not c.get("on"):
        return False
    pid = provider()
    pr = _prov(pid)
    if not pr.get("model"):
        return False
    if pid == "custom":
        return bool(_base(pid))
    if pid == "chatgpt":
        return _siwc().plan_ok()
    return bool(pr.get("key"))


def guess_sees(pid: str, model_id: str) -> bool:
    if pid in ("anthropic", "gemini", "chatgpt"):
        return True
    if pid == "openai":
        return not re.search(r"(?i)^(o1-mini|o3-mini|gpt-3\.5|gpt-oss)", model_id or "")
    return bool(_SEES_NAME.search(model_id or ""))


def sees() -> bool:
    if not on():
        return False
    pid = provider()
    pr = _prov(pid)
    return bool(pr.get("sees", guess_sees(pid, pr.get("model", ""))))


def label() -> str:
    """For the status chip: "Online · Claude"."""
    return PROVIDERS[provider()]["short"]


def note(ok: bool, error: str = "", fallback: bool = False, ms: int = 0):
    LAST.update(ok=ok, error=error, when=time.time(), fallback=fallback, ms=ms)


def state() -> dict:
    c = _load()
    out = {"on": bool(c.get("on")), "ready": on(), "provider": provider(), "last": dict(LAST), "providers": []}
    if _offered("chatgpt"):
        out["chatgpt"] = _siwc().state()
    for pid in ORDER:
        if not _offered(pid):
            continue
        p = PROVIDERS[pid]
        pr = c["providers"].get(pid, {})
        out["providers"].append({
            "id": pid, "name": p["name"], "short": p["short"], "keys_url": p["keys"],
            "base": pr.get("base", "") if pid == "custom" else p["base"], "needs_base": pid == "custom",
            "has_key": bool(pr.get("key")) if pid != "chatgpt" else out["chatgpt"]["signed_in"],
            "key_hint": pr.get("hint", "") if pid != "chatgpt" else out["chatgpt"]["email"],
            "key_optional": pid == "custom", "signin": pid == "chatgpt",
            "model": pr.get("model", ""), "sees": bool(pr.get("sees", guess_sees(pid, pr.get("model", "")))),
        })
    return out


def save(ch: dict) -> dict:
    """Settings → Brain → Online brain: provider, key, base (Other), model, sees, on. Raises ValueError."""
    with _LOCK:
        c = _load()
        pid = ch.get("provider") or provider()
        if not _offered(pid):
            raise ValueError("Unknown AI company.")
        c["provider"] = pid
        pr = _prov(pid)
        if "base" in ch and pid == "custom":
            base = (ch.get("base") or "").strip().rstrip("/")
            if base and not _base_ok(base):
                raise ValueError("Use an https:// address (plain http:// only for a server on this computer or "
                                 "your own network).")
            pr["base"] = base
        if "key" in ch and ch["key"] is not None and pid != "chatgpt":
            key = ch["key"].strip()
            if key:
                if len(key) > 4096 or re.search(r"\s", key):
                    raise ValueError("That doesn't look like an API key — paste it again.")
                pr["key"] = _seal(key)
                pr["hint"] = "…" + key[-4:] if len(key) >= 12 else "saved"
            else:
                pr.pop("key", None)
                pr.pop("hint", None)
            _CLIENTS.clear()
        if "model" in ch and ch["model"] is not None:
            m = ch["model"].strip()[:200]
            if m != pr.get("model"):
                pr["model"] = m
                if ch.get("sees") is None:
                    pr["sees"] = guess_sees(pid, m)
        if ch.get("sees") is not None:
            pr["sees"] = bool(ch["sees"])
        if ch.get("on") is not None:
            c["on"] = bool(ch["on"])
        _write()
        if ch.get("on") is not None or "key" in ch or "model" in ch:
            note(None)
    return state()


# ══════════════════════════════════════════════════════════════════════
#   messages
# ══════════════════════════════════════════════════════════════════════
def _text_of(content) -> str:
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return content or ""


def _text_only(messages: list) -> list:
    """For a model that can't see: keep the words of any message that carries a picture."""
    return [{**m, "content": _text_of(m.get("content"))} if isinstance(m.get("content"), list) else m
            for m in messages]


def _json_hint(messages: list, schema) -> list:
    """Ask for JSON in words, for a company or model that can't hold the reply to a schema."""
    hint = ("\n\nReply with only a JSON object, no other text"
            + (f", matching this JSON schema: {json.dumps(schema, separators=(',', ':'))}" if schema else "") + ".")
    out = [dict(m) for m in messages]
    for m in reversed(out):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):
                m["content"] = c + [{"type": "text", "text": hint}]
            else:
                m["content"] = (c or "") + hint
            break
    return out


def _json_only(text: str) -> str:
    """The JSON object in a reply (some models wrap it in ``` fences or a sentence)."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*", "", t).strip()
        if t.endswith("```"):
            t = t[:-3].strip()
    if not t.startswith("{"):
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if m:
            t = m.group(0)
    return t


class _NoThink:
    """Drops a <think>…</think> block at the start of a reply: some servers let reasoning models write their
    thinking into the answer (most send it apart, as reasoning_content, which is never read)."""

    def __init__(self):
        self.buf, self.state = "", "start"

    def feed(self, piece: str) -> str:
        if self.state == "pass":
            return piece
        self.buf += piece
        if self.state == "start":
            head = self.buf.lstrip()
            if not head or ("<think>".startswith(head) and head != "<think>"):
                return ""                                        # nothing yet, or "<thi" so far: wait
            if not head.startswith("<think>"):
                out, self.buf, self.state = self.buf, "", "pass"
                return out
            self.state = "in"
        if "</think>" in self.buf:
            out = self.buf.split("</think>", 1)[1].lstrip()
            self.state, self.buf = "pass", ""
            return out
        return ""

    def end(self) -> str:
        out = "" if self.state == "in" else self.buf
        self.buf = ""
        return out


# ══════════════════════════════════════════════════════════════════════
#   OpenAI-compatible chat completions (OpenAI, DeepSeek, Gemini, NVIDIA, Other)
# ══════════════════════════════════════════════════════════════════════
# What a server turned down, learnt once per (server, model): "mct" use max_completion_tokens, "notemp" no
# temperature, "noeffort" no reasoning_effort, "noschema" no json_schema, "nojson" no json_object, "smallcap" the
# reply limit as asked.
_QUIRKS: dict = {}
_START = {"openai": {"mct"}}


def _headers(key: str) -> dict:
    h = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def _cap(pid: str, model_id: str, limit: int, quirks: set) -> int:
    """The reply limit sent: room to think for reasoning models (callers stop reading at their own length)."""
    if "smallcap" in quirks:
        return limit
    if PROVIDERS[pid]["effort"] or _THINKS_NAME.search(model_id):
        return limit + 3072
    return max(limit, 1024)


def _adapt(quirks: set, status: int, body: str, payload: dict) -> bool:
    """A server turned the request down for one of its settings: learn it, and say whether to try again."""
    if status not in (400, 422):
        return False
    b = body.lower()
    if "max_tokens" in b and ("max_completion_tokens" in b or "not supported" in b or "unsupported" in b) \
            and "mct" not in quirks:
        quirks.add("mct")
        return True
    if ("max_tokens" in b or "max_completion_tokens" in b) and re.search(r"too large|exceed|maximum|at most|less than", b) \
            and "smallcap" not in quirks:
        quirks.add("smallcap")
        return True
    if "temperature" in b and "temperature" in payload and "notemp" not in quirks:
        quirks.add("notemp")
        return True
    if ("reasoning_effort" in b or "reasoning effort" in b) and "reasoning_effort" in payload and "noeffort" not in quirks:
        quirks.add("noeffort")
        return True
    if "chat_template_kwargs" in b and "chat_template_kwargs" in payload and "nokwargs" not in quirks:
        quirks.add("nokwargs")
        return True
    rf = (payload.get("response_format") or {}).get("type")
    if rf == "json_schema" and ("response_format" in b or "json_schema" in b or "schema" in b) and "noschema" not in quirks:
        quirks.add("noschema")
        return True
    if rf == "json_object" and ("response_format" in b or "json" in b) and "nojson" not in quirks:
        quirks.add("nojson")
        return True
    return False


def _error_text(body: str) -> str:
    try:
        obj = json.loads(body)
        if isinstance(obj, list) and obj:
            obj = obj[0]
        err = obj.get("error", obj) if isinstance(obj, dict) else obj
        if isinstance(err, dict):
            return str(err.get("message") or err.get("detail") or err)[:240]
        return str(err)[:240]
    except (ValueError, AttributeError):
        return re.sub(r"\s+", " ", body)[:240]


def _who(pid: str, cap: bool = False) -> str:
    """The company's name in a message ("your AI server" for Other)."""
    n = "your AI server" if pid == "custom" else PROVIDERS[pid]["name"]
    return n[:1].upper() + n[1:] if cap else n


def _status_error(pid: str, model_id: str, status: int, body: str) -> CloudError:
    name = _who(pid, True)
    text = _error_text(body)
    low = text.lower()
    if status in (401, 403):
        return CloudError(f"{name} refused the API key ({text}). Check it in Settings → Brain.")
    if status == 404 or "model" in low and ("not found" in low or "does not exist" in low or "not exist" in low):
        return CloudError(f"{name} doesn't offer the model “{model_id}” to this key. Pick another in Settings → Brain.")
    if status == 402 or "insufficient" in low or "credit" in low or "billing" in low or "quota" in low:
        return CloudError(f"{name} says the account is out of credit ({text}).", local_ok=True)
    if status == 429:
        return CloudError(f"{name} says this account has reached its limit for now ({text}).", local_ok=True)
    if status >= 500:
        return CloudError(f"{name} is having trouble right now ({status}).", local_ok=True)
    return CloudError(f"{name} turned the request down: {text}")


async def _oa_stream(pid, model_id, messages, temperature, limit, info, json_mode, schema):
    think = THINK.get()
    if think and pid == "deepseek" and model_id == "deepseek-chat":
        model_id = "deepseek-reasoner"                   # DeepSeek's thinking mode of the same model
    base, key = _base(pid), _key(pid)
    quirks = _QUIRKS.setdefault((base, model_id), set(_START.get(pid, ())))
    name = _who(pid, True)
    timeout = httpx.Timeout(120.0, connect=12.0)
    for _ in range(6):
        msgs = messages
        p = {"model": model_id, "messages": msgs, "stream": True}
        p["max_completion_tokens" if "mct" in quirks else "max_tokens"] = \
            _cap(pid, model_id, limit, quirks) + (6144 if think and "smallcap" not in quirks else 0)
        if temperature is not None and "notemp" not in quirks:
            p["temperature"] = temperature
        if PROVIDERS[pid]["effort"] and "noeffort" not in quirks:
            p["reasoning_effort"] = "medium" if think else "low"
        if think and pid in ("nvidia", "custom") and "nokwargs" not in quirks:
            p["chat_template_kwargs"] = {"enable_thinking": True}     # Qwen3-style models on vLLM / NIM
        if schema and "noschema" not in quirks:
            p["response_format"] = {"type": "json_schema", "json_schema": {"name": "reply", "schema": schema}}
        elif (schema or json_mode) and "nojson" not in quirks:
            p["response_format"] = {"type": "json_object"}
        if (schema and "noschema" in quirks) or (json_mode and not schema):
            p["messages"] = _json_hint(msgs, schema)
        produced = False
        nothink = _NoThink()                             # (not `think`: that is the Think button's flag)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", base + "/chat/completions", headers=_headers(key), json=p) as r:
                    if r.status_code >= 400:
                        body = (await r.aread()).decode("utf-8", "ignore")
                        if _adapt(quirks, r.status_code, body, p):
                            continue
                        raise _status_error(pid, model_id, r.status_code, body)
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except ValueError:
                            continue
                        if isinstance(obj, dict) and obj.get("error"):
                            err = obj["error"]
                            msg = err.get("message") if isinstance(err, dict) else str(err)
                            raise CloudError(f"{name} stopped: {msg}"[:300], local_ok=not produced)
                        for ch in obj.get("choices") or []:
                            if ch.get("finish_reason") and info is not None:
                                info["finish"] = "length" if ch["finish_reason"] == "length" else "stop"
                            piece = (ch.get("delta") or {}).get("content")
                            if piece:
                                piece = nothink.feed(piece)
                                if piece:
                                    produced = True
                                    yield piece
                    rest = nothink.end()
                    if rest:
                        yield rest
                    return
        except httpx.HTTPError as e:
            raise CloudError(f"MrSOLIS couldn't reach {_who(pid)} — check the internet connection.",
                             local_ok=not produced) from e
    raise CloudError(f"{name} kept turning the request down.")


async def _oa_models(pid: str, key: str, base: str) -> list:
    name = _who(pid, True)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=12.0)) as client:
            r = await client.get(base.rstrip("/") + "/models", headers=_headers(key))
    except httpx.HTTPError as e:
        raise CloudError(f"MrSOLIS couldn't reach {_who(pid)} — check the internet connection"
                         + (" and the server address." if pid == "custom" else "."), local_ok=True) from e
    if r.status_code >= 400:
        raise _status_error(pid, "", r.status_code, r.text)
    try:
        data = r.json()
    except ValueError:
        raise CloudError(f"{name} didn't send a model list.")
    items = data.get("data") or data.get("models") or [] if isinstance(data, dict) else data
    out, seen = [], set()
    for it in items if isinstance(items, list) else []:
        mid = (it.get("id") or it.get("name") or it.get("slug") or "") if isinstance(it, dict) else str(it)
        mid = mid[len("models/"):] if mid.startswith("models/") else mid
        if not mid or mid in seen or _NOT_CHAT.search(mid):
            continue
        seen.add(mid)
        label = (it.get("display_name") if isinstance(it, dict) else None) or mid
        out.append({"id": mid, "name": label})
    out.sort(key=lambda m: m["id"].lower())
    return out


# ══════════════════════════════════════════════════════════════════════
#   Anthropic (Claude), through the official SDK
# ══════════════════════════════════════════════════════════════════════
_CLIENTS: dict = {}
_DATA_URL = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.*)$", re.DOTALL)
_CLAUDE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _claude_new(key: str, read: float):
    import anthropic
    return anthropic.AsyncAnthropic(api_key=key, max_retries=1, timeout=anthropic.Timeout(read, connect=12.0))


def _claude_client(key: str):
    c = _CLIENTS.get(key)
    if c is None:
        _CLIENTS.clear()
        c = _CLIENTS[key] = _claude_new(key, 180.0)
    return c


def _claude_blocks(content) -> list:
    if not isinstance(content, list):
        return [{"type": "text", "text": content}] if (content or "").strip() else []
    out = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and (part.get("text") or "").strip():
            out.append({"type": "text", "text": part["text"]})
        elif part.get("type") == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            m = _DATA_URL.match(url)
            if m and m.group(1).lower() in _CLAUDE_TYPES:
                out.append({"type": "image", "source": {"type": "base64", "media_type": m.group(1).lower(),
                                                        "data": m.group(2)}})
            elif url.startswith("https://"):
                out.append({"type": "image", "source": {"type": "url", "url": url}})
    return out


def _to_claude(messages: list):
    """OpenAI-style messages → Claude's: system prompts go to `system`; turns alternate, starting with the student."""
    system, out = [], []
    for m in messages:
        role = m.get("role")
        if role == "system":
            t = _text_of(m.get("content")).strip()
            if t:
                system.append(t)
            continue
        blocks = _claude_blocks(m.get("content"))
        if not blocks:
            continue
        role = "assistant" if role == "assistant" else "user"
        if out and out[-1]["role"] == role:
            out[-1]["content"] += blocks
        else:
            out.append({"role": role, "content": blocks})
    if not out or out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": [{"type": "text", "text": "Go on."}]})
    if out[-1]["role"] == "assistant":                   # Claude takes no half-written reply to finish
        out.append({"role": "user", "content": [{"type": "text", "text": "Continue from exactly where you left "
                                                                         "off. Do not repeat anything."}]})
    return "\n\n".join(system), out


def _claude_schema(s):
    """A schema Claude's structured outputs take: objects closed, and size limits said in words."""
    if not isinstance(s, dict):
        return s
    out, notes = {}, []
    for k, v in s.items():
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: _claude_schema(pv) for pk, pv in v.items()}
        elif k == "items":
            out[k] = _claude_schema(v)
        elif k in ("anyOf",) and isinstance(v, list):
            out[k] = [_claude_schema(x) for x in v]
        elif k in ("type", "required", "enum", "description", "const"):
            out[k] = v
        elif k in ("maxLength", "minLength", "maxItems", "minItems", "minimum", "maximum"):
            notes.append(f"{k} {v}")
    if out.get("type") == "object":
        out["additionalProperties"] = False
        out.setdefault("required", list((out.get("properties") or {}).keys()))
    if notes:
        out["description"] = ((out.get("description") or "") + " (" + ", ".join(notes) + ")").strip()
    return out


async def _claude_stream(model_id, messages, limit, info, json_mode, schema):
    import anthropic
    key = _key("anthropic")
    system, msgs = _to_claude(messages)
    quirks = _QUIRKS.setdefault(("anthropic", model_id), set())
    client = _claude_client(key)
    think = THINK.get()
    for _ in range(5):
        kw = {"model": model_id, "max_tokens": min(64000, max(limit, 1024) * 2 + (12288 if think else 4096)), "messages": msgs}
        if system:
            kw["system"] = system
        if "nocache" not in quirks:
            kw["cache_control"] = {"type": "ephemeral"}       # a slide's long prompt is reused by its questions
        oc = {}
        if "noeffort" not in quirks:
            oc["effort"] = "medium" if think else "low"       # a tutor's answers: quick; Think: more thought
        if schema and "noschema" not in quirks:
            oc["format"] = {"type": "json_schema", "schema": _claude_schema(schema)}
        elif schema or json_mode:
            kw["messages"] = _to_claude(_json_hint(messages, schema))[1]
        if oc:
            kw["output_config"] = oc
        fallbacks = model_id in _CLAUDE_FALLBACKS and "nofallback" not in quirks
        produced = False
        try:
            if fallbacks:
                cm = client.beta.messages.stream(**kw, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            else:
                cm = client.messages.stream(**kw)
            async with cm as stream:
                async for text in stream.text_stream:
                    if text:
                        produced = True
                        yield text
                final = await stream.get_final_message()
            stop = getattr(final, "stop_reason", None)
            if info is not None:
                info["finish"] = "length" if stop == "max_tokens" else "stop"
            if stop == "refusal" and not produced:
                yield "I can't help with that one — let's get back to your studies."
            return
        except anthropic.BadRequestError as e:
            msg = str(getattr(e, "message", e)).lower()
            if produced:
                raise CloudError(f"Claude stopped: {getattr(e, 'message', e)}")
            if "effort" in msg and "noeffort" not in quirks:
                quirks.add("noeffort")
                continue
            if schema and "noschema" not in quirks and ("format" in msg or "schema" in msg or "output_config" in msg):
                quirks.add("noschema")
                continue
            if fallbacks and "fallback" in msg:
                quirks.add("nofallback")
                continue
            if "cache_control" in msg and "nocache" not in quirks:
                quirks.add("nocache")
                continue
            if "credit balance" in msg or "billing" in msg:
                raise CloudError("Your Anthropic account is out of credit.", local_ok=True)
            raise CloudError(f"Claude turned the request down: {getattr(e, 'message', e)}"[:300])
        except anthropic.AuthenticationError:
            raise CloudError("Anthropic refused the API key. Check it in Settings → Brain.")
        except anthropic.PermissionDeniedError:
            raise CloudError("This Anthropic key isn't allowed to use that model. Pick another in Settings → Brain.")
        except anthropic.NotFoundError:
            raise CloudError(f"Anthropic doesn't offer the model “{model_id}” to this key. Pick another in Settings → Brain.")
        except anthropic.RateLimitError:
            raise CloudError("Anthropic says this account has reached its limit for now.", local_ok=not produced)
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                raise CloudError(f"Anthropic is having trouble right now ({e.status_code}).", local_ok=not produced)
            raise CloudError(f"Claude turned the request down ({e.status_code}).")
        except anthropic.APIConnectionError as e:          # includes timeouts
            raise CloudError("MrSOLIS couldn't reach Anthropic — check the internet connection.",
                             local_ok=not produced) from e
    raise CloudError("Anthropic kept turning the request down.")


async def _claude_models(key: str) -> list:
    import anthropic
    client = _claude_new(key, 25.0)
    out = []
    try:
        async for m in client.models.list(limit=100):
            out.append({"id": m.id, "name": getattr(m, "display_name", None) or m.id})
    except anthropic.AuthenticationError:
        raise CloudError("Anthropic refused the API key. Check it and try again.")
    except anthropic.APIStatusError as e:
        raise CloudError(f"Anthropic couldn't list its models ({e.status_code}).", local_ok=e.status_code >= 500)
    except anthropic.APIConnectionError as e:
        raise CloudError("MrSOLIS couldn't reach Anthropic — check the internet connection.", local_ok=True) from e
    return out


# ══════════════════════════════════════════════════════════════════════
#   what brain.py calls
# ══════════════════════════════════════════════════════════════════════
async def chat_stream(messages, *, temperature=0.7, max_tokens=None, info=None, json_mode=False, schema=None,
                      pid=None):
    """Yields the reply in pieces, like brain.chat_stream. Raises CloudError."""
    pid = pid or provider()
    pr = _prov(pid)
    model_id = pr.get("model", "")
    if not model_id:
        raise CloudError("Pick a model for the online brain in Settings → Brain.")
    if pid not in ("custom", "chatgpt") and not pr.get("key"):
        raise CloudError(f"Add your {PROVIDERS[pid]['name']} API key in Settings → Brain.")
    if not _offered(pid):
        raise CloudError("ChatGPT plans aren't available in MrSOLIS yet.")
    if not bool(pr.get("sees", guess_sees(pid, model_id))):
        messages = _text_only(messages)
    limit = int(max_tokens or 768)
    t0 = time.monotonic()
    first = True
    try:
        if PROVIDERS[pid]["kind"] == "anthropic":
            gen = _claude_stream(model_id, messages, limit, info, json_mode, schema)
        elif PROVIDERS[pid]["kind"] == "chatgpt":
            gen = _siwc().stream(model_id, messages, info, json_mode, schema)
        else:
            gen = _oa_stream(pid, model_id, messages, temperature, limit, info, json_mode, schema)
        async for piece in gen:
            if first:                                    # "answered in …": the wait for the first words
                first = False
                note(True, ms=int((time.monotonic() - t0) * 1000))
            yield piece
    except CloudError as e:
        note(False, str(e))
        raise


async def chat(messages, *, temperature=0.7, max_tokens=None, json_mode=False, schema=None, pid=None) -> str:
    parts = []
    async for piece in chat_stream(messages, temperature=temperature, max_tokens=max_tokens,
                                   json_mode=json_mode, schema=schema, pid=pid):
        parts.append(piece)
    text = "".join(parts)
    if "</think>" in text:                               # thinking written into the reply, opening tag left out
        text = text.split("</think>")[-1].lstrip()
    return _json_only(text) if (schema or json_mode) else text


async def list_models(pid: str, key: str | None = None, base: str | None = None) -> dict:
    """The models this key may use (chat models only), and the one to suggest."""
    if not _offered(pid):
        raise CloudError("Unknown AI company.")
    if pid == "chatgpt":
        models = await _siwc().models()
        if not models:
            raise CloudError("ChatGPT offered no models to this account.")
        return {"models": models, "suggest": models[0]["id"]}
    key = (key or "").strip() or _key(pid)
    if PROVIDERS[pid]["kind"] == "anthropic":
        if not key:
            raise CloudError("Paste your Anthropic API key first.")
        models = await _claude_models(key)
    else:
        base = (base or "").strip().rstrip("/") or _base(pid)
        if not base:
            raise CloudError("Type the server's address first (it usually ends in /v1).")
        if pid == "custom" and not _base_ok(base):
            raise CloudError("Use an https:// address (plain http:// only for a server on this computer or your own network).")
        if pid != "custom" and not key:
            raise CloudError(f"Paste your {PROVIDERS[pid]['name']} API key first.")
        models = await _oa_models(pid, key, base)
    if not models:
        raise CloudError(f"{_who(pid, True)} sent no models this key can chat with.")
    return {"models": models, "suggest": suggest(pid, [m["id"] for m in models])}


def suggest(pid: str, ids: list) -> str:
    """The model to pre-select: the company's usual one, else the newest-looking general model."""
    for want in PROVIDERS[pid]["prefer"]:
        if want in ids:
            return want
    if pid == "openai":
        gpt = [i for i in ids if re.match(r"gpt-\d", i) and not re.search(r"(?i)(nano|codex|pro|preview|\d{4}-\d\d)", i)]
        if gpt:
            ver = lambda i: [int(x) for x in re.findall(r"\d+", i.split("-")[1])] if len(i.split("-")) > 1 else [0]
            gpt.sort(key=lambda i: (ver(i), "mini" not in i), reverse=True)
            return gpt[0]
    if pid == "anthropic":
        return ids[0] if ids else ""                     # the API lists the newest first
    return ids[0] if ids else ""


async def test() -> dict:
    """Settings → "Test it": a five-word hello from the chosen model."""
    t0 = time.monotonic()
    reply = await chat([{"role": "system", "content": "You are MrSOLIS, a friendly study tutor."},
                        {"role": "user", "content": "Greet a student in at most eight words."}],
                       temperature=0.3, max_tokens=60)
    ms = int((time.monotonic() - t0) * 1000)
    reply = re.sub(r"\s+", " ", reply).strip()
    if not reply:
        raise CloudError("The model answered with nothing. Try another model.")
    return {"ok": True, "reply": reply[:200], "ms": ms}
