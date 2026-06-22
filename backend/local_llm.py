"""
Local LLM client for Lunar AI.

All text intelligence (lecture, chat, explain/solve, semantic search embeddings)
runs on-device. The DEFAULT runtime is **llama.cpp** (via `llama-cpp-python`), so
the models are bundled right inside the desktop app — no Ollama, no downloads, no
setup. An Ollama backend is kept as an automatic fallback for development.

    chat model       : Qwen2.5-1.5B-Instruct  (GGUF)
    embedding model  : nomic-embed-text-v1.5  (GGUF)

Nothing here ever leaves the machine. No API keys.

Backend selection (env `LUNAR_LLM_BACKEND`):
    "llama"  – force in-process llama.cpp (the shipped default)
    "ollama" – force the Ollama HTTP backend (dev only)
    "auto"   – llama.cpp if it's importable and a chat GGUF is present, else Ollama
Default is "auto".
"""

import os
import re
import json
import glob
import asyncio
from concurrent.futures import ThreadPoolExecutor

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CHAT_MODEL = os.environ.get("LUNAR_CHAT_MODEL", "Qwen2.5-1.5B-Instruct")
EMBED_MODEL = os.environ.get("LUNAR_EMBED_MODEL", "nomic-embed-text-v1.5")

# Where the bundled GGUF models live. The desktop app sets LUNAR_MODEL_DIR to the
# packaged resources folder; in dev we fall back to <project_root>/models.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.environ.get("LUNAR_MODEL_DIR") or os.path.join(_PROJECT_ROOT, "models")

DEFAULT_NUM_CTX = int(os.environ.get("LUNAR_NUM_CTX", "4096"))
_NUM_THREAD = os.environ.get("LUNAR_NUM_THREAD")
NUM_THREAD = int(_NUM_THREAD) if _NUM_THREAD else (os.cpu_count() or 4)

# Ollama (dev fallback only)
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_CHAT_MODEL = os.environ.get("LUNAR_OLLAMA_CHAT_MODEL", "qwen2.5:1.5b")
OLLAMA_EMBED_MODEL = os.environ.get("LUNAR_OLLAMA_EMBED_MODEL", "nomic-embed-text")
KEEP_ALIVE = os.environ.get("LUNAR_KEEP_ALIVE", "30m")

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class LocalLLMError(RuntimeError):
    """Raised when the local AI engine cannot run or errors out."""


def _strip_think(text: str) -> str:
    """Defensively remove any <think>...</think> blocks a model may emit."""
    return _THINK_RE.sub("", text or "").strip()


# ---------------------------------------------------------------------------
# Model file discovery
# ---------------------------------------------------------------------------
def _find_gguf(*needles) -> str | None:
    """Find the first *.gguf in MODEL_DIR whose name contains any of `needles`."""
    try:
        files = sorted(glob.glob(os.path.join(MODEL_DIR, "**", "*.gguf"), recursive=True))
    except Exception:
        files = []
    for f in files:
        low = os.path.basename(f).lower()
        if any(n in low for n in needles):
            return f
    return None


def _chat_model_path() -> str | None:
    return os.environ.get("LUNAR_CHAT_GGUF") or _find_gguf("qwen", "chat", "instruct")


def _embed_model_path() -> str | None:
    return os.environ.get("LUNAR_EMBED_GGUF") or _find_gguf("nomic", "embed", "bge", "minilm")


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------
def _llama_available() -> bool:
    try:
        import llama_cpp  # noqa: F401
    except Exception:
        return False
    return _chat_model_path() is not None


def _select_backend() -> str:
    choice = os.environ.get("LUNAR_LLM_BACKEND", "auto").lower()
    if choice in ("llama", "llamacpp", "llama.cpp"):
        return "llama"
    if choice == "ollama":
        return "ollama"
    return "llama" if _llama_available() else "ollama"


BACKEND = _select_backend()


# ===========================================================================
# llama.cpp (in-process) backend
# ===========================================================================
_chat_llm = None
_embed_llm = None
_chat_lock = asyncio.Lock()
_embed_lock = asyncio.Lock()
# One worker thread per model: a single Llama instance is not safe for concurrent
# generation, so all chat calls run on one thread and all embeds on another.
_chat_exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lunar-chat")
_embed_exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lunar-embed")


def _load_chat_llm():
    from llama_cpp import Llama
    path = _chat_model_path()
    if not path:
        raise LocalLLMError(
            f"Chat model not found in {MODEL_DIR}. Expected a Qwen GGUF "
            "(run scripts/fetch_models.py, or set LUNAR_CHAT_GGUF)."
        )
    return Llama(
        model_path=path,
        n_ctx=DEFAULT_NUM_CTX,
        n_threads=NUM_THREAD,
        n_batch=int(os.environ.get("LUNAR_N_BATCH", "512")),
        n_gpu_layers=int(os.environ.get("LUNAR_N_GPU_LAYERS", "0")),
        chat_format=os.environ.get("LUNAR_CHAT_FORMAT", "chatml"),
        verbose=False,
    )


def _load_embed_llm():
    from llama_cpp import Llama
    path = _embed_model_path()
    if not path:
        raise LocalLLMError(
            f"Embedding model not found in {MODEL_DIR}. Expected a nomic-embed GGUF "
            "(run scripts/fetch_models.py, or set LUNAR_EMBED_GGUF)."
        )
    return Llama(
        model_path=path,
        embedding=True,
        n_ctx=int(os.environ.get("LUNAR_EMBED_NUM_CTX", "2048")),
        n_threads=NUM_THREAD,
        n_gpu_layers=int(os.environ.get("LUNAR_N_GPU_LAYERS", "0")),
        verbose=False,
    )


async def _ensure_chat_llm():
    global _chat_llm
    if _chat_llm is None:
        async with _chat_lock:
            if _chat_llm is None:
                loop = asyncio.get_running_loop()
                _chat_llm = await loop.run_in_executor(_chat_exec, _load_chat_llm)
    return _chat_llm


async def _ensure_embed_llm():
    global _embed_llm
    if _embed_llm is None:
        async with _embed_lock:
            if _embed_llm is None:
                loop = asyncio.get_running_loop()
                _embed_llm = await loop.run_in_executor(_embed_exec, _load_embed_llm)
    return _embed_llm


async def _llama_chat(messages, *, temperature, max_tokens, json_mode):
    llm = await _ensure_chat_llm()
    loop = asyncio.get_running_loop()

    def _run():
        kwargs = dict(messages=messages, temperature=temperature,
                      max_tokens=max_tokens or 768, stream=False)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        res = llm.create_chat_completion(**kwargs)
        return res["choices"][0]["message"].get("content", "")

    async with _chat_lock:
        try:
            content = await loop.run_in_executor(_chat_exec, _run)
        except Exception as exc:  # noqa: BLE001
            raise LocalLLMError(f"Local model failed: {exc}") from exc
    return _strip_think(content)


async def _llama_chat_stream(messages, *, temperature, max_tokens):
    llm = await _ensure_chat_llm()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    SENTINEL = object()

    def _worker():
        try:
            for chunk in llm.create_chat_completion(
                messages=messages, temperature=temperature,
                max_tokens=max_tokens or 768, stream=True,
            ):
                delta = (chunk.get("choices") or [{}])[0].get("delta", {}).get("content")
                if delta:
                    loop.call_soon_threadsafe(queue.put_nowait, delta)
        except Exception as exc:  # noqa: BLE001
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

    # Hold the lock for the whole stream so two generations never overlap on the
    # single Llama instance.
    async with _chat_lock:
        loop.run_in_executor(_chat_exec, _worker)
        while True:
            item = await queue.get()
            if item is SENTINEL:
                break
            if isinstance(item, Exception):
                raise LocalLLMError(f"Local model failed: {item}")
            yield item


async def _llama_embed(inputs):
    llm = await _ensure_embed_llm()
    loop = asyncio.get_running_loop()

    def _run():
        res = llm.create_embedding(input=inputs)
        return [d["embedding"] for d in res["data"]]

    async with _embed_lock:
        try:
            return await loop.run_in_executor(_embed_exec, _run)
        except Exception as exc:  # noqa: BLE001
            raise LocalLLMError(f"Local embedding failed: {exc}") from exc


# ===========================================================================
# Ollama (dev fallback) backend
# ===========================================================================
def _supports_think(model: str) -> bool:
    m = (model or "").lower()
    return "qwen3" in m or "r1" in m or "qwq" in m or "reason" in m


def _ollama_options(num_ctx, temperature, max_tokens):
    options = {"temperature": temperature, "num_ctx": num_ctx}
    if max_tokens is not None:
        options["num_predict"] = max_tokens
    if NUM_THREAD:
        options["num_thread"] = NUM_THREAD
    return options


async def _ollama_chat(messages, *, json_mode, num_ctx, temperature, max_tokens, timeout):
    payload = {
        "model": OLLAMA_CHAT_MODEL, "messages": messages, "stream": False,
        "keep_alive": KEEP_ALIVE, "options": _ollama_options(num_ctx, temperature, max_tokens),
    }
    if _supports_think(OLLAMA_CHAT_MODEL):
        payload["think"] = False
    if json_mode:
        payload["format"] = "json"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{OLLAMA_HOST}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.ConnectError as exc:
        raise LocalLLMError(
            f"Could not reach the local AI engine (Ollama) at {OLLAMA_HOST}."
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise LocalLLMError(
            f"Local AI engine returned an error: {exc.response.status_code} "
            f"{exc.response.text[:300]}"
        ) from exc
    return _strip_think(data.get("message", {}).get("content", ""))


async def _ollama_chat_stream(messages, *, num_ctx, temperature, max_tokens, timeout):
    payload = {
        "model": OLLAMA_CHAT_MODEL, "messages": messages, "stream": True,
        "keep_alive": KEEP_ALIVE, "options": _ollama_options(num_ctx, temperature, max_tokens),
    }
    if _supports_think(OLLAMA_CHAT_MODEL):
        payload["think"] = False
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", f"{OLLAMA_HOST}/api/chat", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    piece = obj.get("message", {}).get("content", "")
                    if piece:
                        yield piece
                    if obj.get("done"):
                        break
    except httpx.ConnectError as exc:
        raise LocalLLMError(
            f"Could not reach the local AI engine (Ollama) at {OLLAMA_HOST}."
        ) from exc


async def _ollama_embed(inputs, *, timeout):
    payload = {"model": OLLAMA_EMBED_MODEL, "input": inputs, "keep_alive": KEEP_ALIVE}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{OLLAMA_HOST}/api/embed", json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.ConnectError as exc:
        raise LocalLLMError(
            f"Could not reach the local embedding engine at {OLLAMA_HOST}."
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise LocalLLMError(
            f"Embedding engine returned an error: {exc.response.status_code} "
            f"{exc.response.text[:300]}"
        ) from exc
    return data.get("embeddings", [])


# ===========================================================================
# Public interface (backend-agnostic)
# ===========================================================================
async def chat(
    messages: list,
    *,
    json_mode: bool = False,
    num_ctx: int = DEFAULT_NUM_CTX,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    timeout: float = 600.0,
) -> str:
    """Send a chat completion and return the text reply (OpenAI-style messages)."""
    if BACKEND == "llama":
        return await _llama_chat(messages, temperature=temperature,
                                 max_tokens=max_tokens, json_mode=json_mode)
    return await _ollama_chat(messages, json_mode=json_mode, num_ctx=num_ctx,
                              temperature=temperature, max_tokens=max_tokens, timeout=timeout)


async def chat_stream(
    messages: list,
    *,
    num_ctx: int = DEFAULT_NUM_CTX,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    timeout: float = 600.0,
):
    """Async generator yielding token deltas as they are produced."""
    if BACKEND == "llama":
        async for piece in _llama_chat_stream(messages, temperature=temperature,
                                              max_tokens=max_tokens):
            yield piece
    else:
        async for piece in _ollama_chat_stream(messages, num_ctx=num_ctx,
                                               temperature=temperature,
                                               max_tokens=max_tokens, timeout=timeout):
            yield piece


def _extract_json(text: str, expect: str = "array"):
    """Best-effort extraction of a JSON value from a model response."""
    if not text:
        raise ValueError("Empty response from model")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*", "", cleaned).strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    candidates = [cleaned]
    if expect == "array":
        m = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if m:
            candidates.append(m.group(0))
    obj_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if obj_match:
        candidates.append(obj_match.group(0))
    last_err = None
    for cand in candidates:
        try:
            parsed = json.loads(cand)
        except json.JSONDecodeError as exc:
            last_err = exc
            continue
        if expect == "array":
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                list_values = [v for v in parsed.values() if isinstance(v, list)]
                if len(parsed) == 1 and len(list_values) == 1:
                    return list_values[0]
                return [parsed]
            continue
        return parsed
    raise ValueError(f"Could not parse JSON from response: {text[:400]}") from last_err


async def chat_json(
    messages: list,
    *,
    expect: str = "array",
    num_ctx: int = DEFAULT_NUM_CTX,
    temperature: float = 0.4,
    max_tokens: int | None = None,
):
    """Chat call that returns parsed JSON, with one repair retry on failure."""
    raw = await chat(messages, json_mode=True, num_ctx=num_ctx,
                     temperature=temperature, max_tokens=max_tokens)
    try:
        return _extract_json(raw, expect=expect)
    except ValueError:
        repair = messages + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": (
                "That was not valid JSON. Respond again with ONLY the "
                f"valid JSON {expect} and nothing else.")},
        ]
        raw2 = await chat(repair, json_mode=True, num_ctx=num_ctx,
                          temperature=0.1, max_tokens=max_tokens)
        return _extract_json(raw2, expect=expect)


async def embed(texts, *, timeout: float = 120.0) -> list:
    """Return embedding vectors for a string or list of strings."""
    single = isinstance(texts, str)
    inputs = [texts] if single else list(texts)
    if not inputs:
        return []
    if BACKEND == "llama":
        vectors = await _llama_embed(inputs)
    else:
        vectors = await _ollama_embed(inputs, timeout=timeout)
    return vectors[0] if single else vectors


async def health() -> dict:
    """Readiness probe used by the frontend status chip."""
    info = {"ok": False, "backend": BACKEND, "chat_model": CHAT_MODEL,
            "embed_model": EMBED_MODEL, "models": []}
    if BACKEND == "llama":
        chat_path = _chat_model_path()
        embed_path = _embed_model_path()
        info["models"] = [os.path.basename(p) for p in (chat_path, embed_path) if p]
        info["ok"] = bool(chat_path)
        if not chat_path:
            info["error"] = f"No chat GGUF found in {MODEL_DIR}."
        return info
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{OLLAMA_HOST}/api/tags")
            response.raise_for_status()
            tags = response.json().get("models", [])
            info["models"] = [t.get("name", "") for t in tags]
            info["ok"] = True
    except Exception as exc:  # noqa: BLE001 - health probe must never raise
        info["error"] = str(exc)
    return info
