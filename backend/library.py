"""
The student's library for MrSOLIS: everything that should survive a restart.

One JSON file in the app's data folder (``library.json``) holds:

    decks     every uploaded deck: file, slide titles, where the student got to, its subject
    subjects  the student's own groups of decks
    notes     saved lesson parts / highlights and the student's own notes, per deck
    quizzes   finished quiz results
    events    the study history (slides studied, questions asked, quizzes taken)
    settings  app preferences

Small and local: every change rewrites the file atomically under a lock.

Each deck carries a fingerprint of its file (``sha256``), so uploading a deck the
student already has reopens that one instead of making a second copy.
"""

import hashlib
import json
import os
import threading
import time
import uuid

_EVENT_CAP = 3000
DEFAULT_SETTINGS = {
    "lesson_length": "standard",   # short | standard | detailed
    "board_text": "normal",        # normal | large | xlarge
    "reduce_motion": False,
    "voice_speed": "normal",       # slow | normal | fast — how fast MrSOLIS speaks (Read aloud, Interactive mode)
    "brain": None,                 # the model the student picked (backend/brain.py CATALOG id)
    "look_at_slides": True,        # let the brain look at each slide's picture while teaching
}
VOICE_SPEEDS = {"slow": 0.85, "normal": 1.0, "fast": 1.15}


def _now() -> float:
    return round(time.time(), 3)


def file_fingerprint(path: str) -> str:
    """sha256 of a file's bytes — identical files, whatever their name, match."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class Library:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "library.json")
        self.slides_dir = os.path.join(data_dir, "study-cache", "slides")   # not "cache": Electron's browser Cache on Windows
        os.makedirs(self.slides_dir, exist_ok=True)
        self._lock = threading.RLock()
        self._data = self._load()

    # ── storage ───────────────────────────────────────────────────────
    def _load(self) -> dict:
        data = {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            pass
        except Exception:
            # a damaged file is kept aside rather than silently overwritten
            try:
                os.replace(self.path, self.path + f".broken-{int(time.time())}")
            except Exception:
                pass
        for key, empty in (("decks", {}), ("subjects", {}), ("notes", []), ("quizzes", []),
                           ("events", []), ("settings", {}), ("asked", {})):
            if not isinstance(data.get(key), type(empty)):
                data[key] = empty
        data["settings"] = {**DEFAULT_SETTINGS, **data["settings"]}
        return data

    def _save(self):
        tmp = self.path + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    # ── decks ─────────────────────────────────────────────────────────
    def add_deck(self, deck_id: str, filename: str, file_path: str, media_dir: str, titles: list,
                 sha256: str = None):
        with self._lock:
            self._data["decks"][deck_id] = {
                "id": deck_id, "filename": filename, "file_path": file_path, "media_dir": media_dir,
                "titles": titles, "count": len(titles), "added": _now(), "opened": _now(),
                "last_slide": 0, "seen": [], "subject_id": None, "sha256": sha256,
            }
            self._save()

    # ── one deck per file ─────────────────────────────────────────────
    def _fill_fingerprints(self):
        """Fingerprint decks stored before fingerprints existed (once each)."""
        changed = False
        for d in self._data["decks"].values():
            if not d.get("sha256") and os.path.isfile(d.get("file_path") or ""):
                try:
                    d["sha256"] = file_fingerprint(d["file_path"])
                    changed = True
                except OSError:
                    pass
        return changed

    def find_by_fingerprint(self, sha256: str):
        """The deck already made from this exact file, if its file is still there."""
        with self._lock:
            if self._fill_fingerprints():
                self._save()
            for d in self._data["decks"].values():
                if d.get("sha256") == sha256 and os.path.isfile(d.get("file_path") or ""):
                    return d
            return None

    def merge_duplicates(self) -> list:
        """Fold decks made from the same file into one; returns the folded-away decks.

        The deck that stays is the one filed under a subject (else the most studied,
        else the most recent). It gains the others' progress, notes, quiz scores and
        history, so nothing the student did is lost.
        """
        with self._lock:
            changed = self._fill_fingerprints()
            groups = {}
            for d in self._data["decks"].values():
                if d.get("sha256"):
                    groups.setdefault(d["sha256"], []).append(d)
            dropped = []
            for same in groups.values():
                if len(same) < 2:
                    continue
                same.sort(key=lambda d: (d.get("subject_id") is not None, len(d.get("seen") or []),
                                         d.get("opened", 0)), reverse=True)
                keep = same[0]
                for other in same[1:]:
                    keep["seen"] = sorted(set(keep.get("seen") or []) | set(other.get("seen") or []))
                    if other.get("opened", 0) > keep.get("opened", 0):
                        keep["opened"], keep["last_slide"] = other["opened"], other.get("last_slide", 0)
                    keep["added"] = min(keep.get("added", _now()), other.get("added", _now()))
                    keep["subject_id"] = keep.get("subject_id") or other.get("subject_id")
                    keep["title"] = keep.get("title") or other.get("title")
                    for item in self._data["notes"] + self._data["quizzes"] + self._data["events"]:
                        if item.get("deck_id") == other["id"]:
                            item["deck_id"] = keep["id"]
                    del self._data["decks"][other["id"]]
                    dropped.append(other)
            if changed or dropped:
                self._save()
            return dropped

    def deck(self, deck_id: str):
        return self._data["decks"].get(deck_id)

    def decks(self) -> list:
        return sorted(self._data["decks"].values(), key=lambda d: d.get("opened", 0), reverse=True)

    def touch_slide(self, deck_id: str, idx: int):
        with self._lock:
            d = self._data["decks"].get(deck_id)
            if not d:
                return
            d["opened"] = _now()
            d["last_slide"] = idx
            if idx not in d["seen"]:
                d["seen"].append(idx)
            self._event("slide", deck_id, slide=idx)
            self._save()

    def update_deck(self, deck_id: str, **fields):
        with self._lock:
            d = self._data["decks"].get(deck_id)
            if not d:
                return None
            for k in ("subject_id", "title"):
                if k in fields:
                    d[k] = fields[k]
            self._save()
            return d

    def remove_deck(self, deck_id: str):
        with self._lock:
            d = self._data["decks"].pop(deck_id, None)
            self._data["notes"] = [n for n in self._data["notes"] if n.get("deck_id") != deck_id]
            self._data["asked"].pop(deck_id, None)
            self._save()
            return d

    # ── quiz questions already asked (so a new quiz never repeats one) ──────
    def asked(self, deck_id: str) -> list:
        """[{"slide": i, "q": "...", "a": "..."}] — every question this deck's quizzes have shown, oldest first."""
        return list(self._data["asked"].get(deck_id) or [])

    def note_asked(self, deck_id: str, slide: int, question: str, answer: str = ""):
        with self._lock:
            items = self._data["asked"].setdefault(deck_id, [])
            items.append({"slide": slide, "q": question[:300], "a": answer[:300]})
            del items[:-400]                      # plenty for any deck; keeps library.json small
            self._save()

    def save_slides(self, deck_id: str, slides: list):
        path = os.path.join(self.slides_dir, f"{deck_id}.json")
        tmp = path + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(slides, f, ensure_ascii=False, default=str)
        os.replace(tmp, path)

    def load_slides(self, deck_id: str):
        try:
            with open(os.path.join(self.slides_dir, f"{deck_id}.json"), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def drop_slides(self, deck_id: str):
        try:
            os.remove(os.path.join(self.slides_dir, f"{deck_id}.json"))
        except Exception:
            pass

    # ── subjects ──────────────────────────────────────────────────────
    def subjects(self) -> list:
        return sorted(self._data["subjects"].values(), key=lambda s: s.get("name", "").lower())

    def add_subject(self, name: str) -> dict:
        with self._lock:
            sid = uuid.uuid4().hex[:12]
            s = {"id": sid, "name": name.strip()[:60] or "Untitled", "created": _now()}
            self._data["subjects"][sid] = s
            self._save()
            return s

    def rename_subject(self, sid: str, name: str):
        with self._lock:
            s = self._data["subjects"].get(sid)
            if s:
                s["name"] = name.strip()[:60] or s["name"]
                self._save()
            return s

    def remove_subject(self, sid: str):
        with self._lock:
            s = self._data["subjects"].pop(sid, None)
            for d in self._data["decks"].values():
                if d.get("subject_id") == sid:
                    d["subject_id"] = None
            self._save()
            return s

    # ── notes ─────────────────────────────────────────────────────────
    def notes(self, deck_id=None) -> list:
        ns = self._data["notes"]
        if deck_id:
            ns = [n for n in ns if n.get("deck_id") == deck_id]
        return sorted(ns, key=lambda n: n.get("created", 0))

    def add_note(self, deck_id, text: str, kind: str = "mine", slide=None) -> dict:
        with self._lock:
            n = {"id": uuid.uuid4().hex[:12], "deck_id": deck_id, "slide": slide,
                 "kind": kind if kind in ("mine", "saved", "highlight") else "mine",
                 "text": text.strip()[:20000], "created": _now()}
            self._data["notes"].append(n)
            self._event("note", deck_id, slide=slide)
            self._save()
            return n

    def update_note(self, note_id: str, text: str):
        with self._lock:
            for n in self._data["notes"]:
                if n["id"] == note_id:
                    n["text"] = text.strip()[:20000]
                    n["edited"] = _now()
                    self._save()
                    return n
            return None

    def remove_note(self, note_id: str) -> bool:
        with self._lock:
            before = len(self._data["notes"])
            self._data["notes"] = [n for n in self._data["notes"] if n["id"] != note_id]
            self._save()
            return len(self._data["notes"]) < before

    # ── quizzes ───────────────────────────────────────────────────────
    def add_quiz(self, deck_id: str, score: int, total: int, review: list) -> dict:
        with self._lock:
            q = {"id": uuid.uuid4().hex[:12], "deck_id": deck_id, "score": score, "total": total,
                 "review": review, "created": _now()}
            self._data["quizzes"].append(q)
            self._event("quiz", deck_id, score=score, total=total)
            self._save()
            return q

    def quizzes(self) -> list:
        return sorted(self._data["quizzes"], key=lambda q: q.get("created", 0), reverse=True)

    # ── history ───────────────────────────────────────────────────────
    def _event(self, kind: str, deck_id=None, **extra):
        ev = {"t": _now(), "type": kind, "deck_id": deck_id, **extra}
        self._data["events"].append(ev)
        if len(self._data["events"]) > _EVENT_CAP:
            del self._data["events"][: len(self._data["events"]) - _EVENT_CAP]

    def log(self, kind: str, deck_id=None, **extra):
        with self._lock:
            self._event(kind, deck_id, **extra)
            self._save()

    def events(self, limit: int = 600) -> list:
        return list(reversed(self._data["events"][-limit:]))

    def clear_history(self):
        with self._lock:
            self._data["events"] = []
            self._data["quizzes"] = []
            self._save()

    # ── settings ──────────────────────────────────────────────────────
    def settings(self) -> dict:
        return dict(self._data["settings"])

    def update_settings(self, changes: dict) -> dict:
        with self._lock:
            s = self._data["settings"]
            if changes.get("lesson_length") in ("short", "standard", "detailed"):
                s["lesson_length"] = changes["lesson_length"]
            if changes.get("board_text") in ("normal", "large", "xlarge"):
                s["board_text"] = changes["board_text"]
            if isinstance(changes.get("reduce_motion"), bool):
                s["reduce_motion"] = changes["reduce_motion"]
            if changes.get("voice_speed") in VOICE_SPEEDS:
                s["voice_speed"] = changes["voice_speed"]
            if isinstance(changes.get("brain"), str) and 0 < len(changes["brain"]) <= 40:
                s["brain"] = changes["brain"]
            elif "brain" in changes and changes["brain"] is None:     # its brain was removed
                s["brain"] = None
            if isinstance(changes.get("look_at_slides"), bool):
                s["look_at_slides"] = changes["look_at_slides"]
            self._save()
            return dict(s)
