"""The questions already given in each practice session, so a session never repeats one.

In memory only: a practice session lasts while the SQE window is open, and nothing is written to the data folder.
The oldest sessions are dropped beyond MAX_SESSIONS. (2-AL kept this in SQLite.)
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Dict, List

MAX_SESSIONS = 200
_MEM: "OrderedDict[str, List[Dict]]" = OrderedDict()
_LOCK = threading.Lock()


def get_existing(deck_id: str) -> List[Dict]:
    with _LOCK:
        return list(_MEM.get(deck_id, []))


def register(deck_id: str, question_hash: str, fact_key: str, question_text: str) -> None:
    with _LOCK:
        rows = _MEM.setdefault(deck_id, [])
        _MEM.move_to_end(deck_id)
        if not any(r["hash"] == question_hash for r in rows):
            rows.append({"hash": question_hash, "fact_key": fact_key or "", "text": question_text})
        while len(_MEM) > MAX_SESSIONS:
            _MEM.popitem(last=False)


def clear_deck(deck_id: str) -> None:
    with _LOCK:
        _MEM.pop(deck_id, None)


def count_for_deck(deck_id: str) -> int:
    with _LOCK:
        return len(_MEM.get(deck_id, []))
