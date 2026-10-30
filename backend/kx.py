"""
CUSTOM-Kx in the app: a leaner picture reader (mmproj) for each brain, made on the student's computer.

The brains' picture readers come as 16-bit files (Smarts 637 MB, Speedy 196 MB) and the AI engine loads
them whole into private RAM. Their big matrices — the encoder's attention and MLP weights and Qwen's
merger — are rewritten here as Q8_0 (8-bit, one scale per 32 values); everything else is copied as is.
Measured 2026-10-24 on an i5-13420H with the app's flags (finetune/kx/kx_eval_vision.py: 8 real slides
from the training decks + 3 drawn ones):
  Smarts: 637 -> 345 MB; RAM after load 2,082 -> 1,790 MB, looking at a slide 2,301 -> 1,999 MB;
          slide reading identical (recall 0.965 on every slide), the same drawn facts, transcripts 7/8
          word for word (the 8th differs only in spacing).
  Gemma 4 E4B (with hearing): 946 -> 541 MB, the same reading, and its audio transcript word for word.
Same maths as llama.cpp's gguf-py Q8_0 (round half away from zero, fp16 scale). No libraries beyond numpy.
"""

import os
import re
import struct

import numpy as np

# GGUF value types -> struct format (strings and arrays are handled separately)
_SCALAR = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
F32, F16, Q8_0, BF16 = 0, 1, 8, 30
_BLOCK = {F32: (1, 4), F16: (1, 2), BF16: (1, 2), Q8_0: (32, 34)}
# the encoder's big matrices (Gemma 4 vision/audio, Qwen3-VL / Qwen3.5 vision) and Qwen's merger
LINEAR = re.compile(r"^([va]\.blk\.\d+\.(attn_(q|k|v|qkv|out|k_rel)|ffn_(up|down|gate)(_1)?|conv_pw1|conv_pw2)"
                    r"|mm\.\d+)\.weight$")
MARK = "mrsolis.kx"                    # written into the file so a converted reader is never converted twice


class _Reader:
    def __init__(self, f):
        self.f = f

    def read(self, fmt):
        n = struct.calcsize("<" + fmt)
        return struct.unpack("<" + fmt, self.f.read(n))[0]

    def string(self):
        return self.f.read(self.read("Q")).decode("utf-8")

    def skip_value(self, t):
        if t == 8:
            self.string()
        elif t == 9:
            et, n = self.read("I"), self.read("Q")
            for _ in range(n):
                self.skip_value(et)
        else:
            self.f.read(struct.calcsize("<" + _SCALAR[t]))


def _header(path):
    """(kv blob, {key: (type, start, end)}, tensors [(name, dims, type, offset)], data start, alignment)."""
    with open(path, "rb") as f:
        r = _Reader(f)
        if f.read(4) != b"GGUF":
            raise ValueError("not a GGUF file")
        version, n_t, n_kv = r.read("I"), r.read("Q"), r.read("Q")
        kv_start, keys, align = f.tell(), {}, 32
        for _ in range(n_kv):
            start = f.tell()
            key = r.string()
            t = r.read("I")
            vstart = f.tell()
            if key == "general.alignment" and t == 4:
                align = r.read("I")
            else:
                r.skip_value(t)
            keys[key] = (t, start, f.tell(), vstart)
        kv_end = f.tell()
        tensors = []
        for _ in range(n_t):
            name = r.string()
            dims = [r.read("Q") for _ in range(r.read("I"))]
            tensors.append((name, dims, r.read("I"), r.read("Q")))
        info_end = f.tell()
        f.seek(kv_start)
        blob = f.read(kv_end - kv_start)
    data_start = (info_end + align - 1) // align * align
    return version, n_kv, blob, keys, tensors, data_start, align


def is_converted(path) -> bool:
    try:
        return MARK in _header(path)[3]
    except (OSError, ValueError, KeyError, struct.error):
        return False


def _q8_0(x: np.ndarray) -> bytes:
    """float32 rows -> Q8_0 blocks (fp16 scale + 32 int8), exactly like gguf-py."""
    blocks = x.reshape(-1, 32).astype(np.float32)
    d = np.abs(blocks).max(axis=-1, keepdims=True) / 127
    with np.errstate(divide="ignore"):
        inv = np.where(d == 0, 0, 1 / d)
    q = blocks * inv
    q = (np.sign(q) * np.floor(np.abs(q) + 0.5)).astype(np.int8)          # round half away from zero
    out = np.empty((blocks.shape[0], 34), np.uint8)
    out[:, :2] = d.astype(np.float16).view(np.uint8)
    out[:, 2:] = q.view(np.uint8)
    return out.tobytes()


def _as_f32(raw: bytes, t: int) -> np.ndarray:
    if t == F32:
        return np.frombuffer(raw, np.float32)
    if t == F16:
        return np.frombuffer(raw, np.float16).astype(np.float32)
    return (np.frombuffer(raw, np.uint16).astype(np.uint32) << 16).view(np.float32)       # BF16


def convert_mmproj(src: str, dst: str) -> dict:
    """Write the Q8_0 picture reader for `src` to `dst` (via dst.part, renamed when complete)."""
    version, n_kv, blob, keys, tensors, data_start, align = _header(src)
    if MARK in keys:
        raise ValueError("already converted")
    plan = []
    for name, dims, t, off in tensors:
        n = int(np.prod(dims)) if dims else 1
        bs, ts = _BLOCK.get(t, (None, None))
        size = n // bs * ts if bs else None
        if size is None:
            raise ValueError(f"unsupported tensor type {t} in {name}")
        new = Q8_0 if LINEAR.match(name) and t in (F32, F16, BF16) and dims[0] % 32 == 0 else t
        plan.append((name, dims, t, off, size, new, n // 32 * 34 if new == Q8_0 and new != t else size))
    if all(p[2] == p[5] for p in plan):
        raise ValueError("nothing to convert")              # e.g. a reader that is Q8_0 already (Qwen3-VL's)
    mark = struct.pack("<Q", len(MARK)) + MARK.encode() + struct.pack("<I", 7) + struct.pack("<?", True)
    part = dst + ".part"
    before = after = 0
    with open(src, "rb") as fin, open(part, "wb") as out:
        out.write(b"GGUF" + struct.pack("<IQQ", version, len(tensors), n_kv + 1))
        out.write(blob + mark)
        offset = 0
        for name, dims, _t, _off, _size, new, new_size in plan:
            nb = name.encode()
            out.write(struct.pack("<Q", len(nb)) + nb + struct.pack("<I", len(dims)))
            out.write(b"".join(struct.pack("<Q", d) for d in dims) + struct.pack("<IQ", new, offset))
            offset += (new_size + align - 1) // align * align
        out.write(b"\0" * ((-out.tell()) % align))
        for name, dims, t, off, size, new, new_size in plan:
            fin.seek(data_start + off)
            raw = fin.read(size)
            data = _q8_0(_as_f32(raw, t)) if new != t else raw
            out.write(data + b"\0" * ((-len(data)) % align))
            before += size
            after += len(data)
    os.replace(part, dst)
    return {"before_mb": round(before / 2**20, 1), "after_mb": round(after / 2**20, 1)}
