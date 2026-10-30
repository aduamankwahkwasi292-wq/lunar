"""No repeats within a practice session: the exact (normalised) question text, and optionally one question per fact.

2-AL also had a TF-IDF near-duplicate layer (scikit-learn), turned off for this pipeline because templated questions
that differ only in their numbers looked like duplicates; it is left out here.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

from . import store


def normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def question_hash(text: str) -> str:
    return hashlib.sha1(normalize(text).encode()).hexdigest()[:24]


class DedupFilter:
    def __init__(self, deck_id: str, near_dup_threshold: Optional[float] = None):
        self.deck_id = deck_id
        existing = store.get_existing(deck_id)
        self.seen_hashes = {e["hash"] for e in existing}
        self.seen_fact_keys = {e["fact_key"] for e in existing if e["fact_key"]}

    def is_duplicate(self, text: str, fact_key: Optional[str] = None, allow_multiple_per_fact: bool = False) -> bool:
        if question_hash(text) in self.seen_hashes:
            return True
        return bool(fact_key and not allow_multiple_per_fact and fact_key in self.seen_fact_keys)

    def register(self, text: str, fact_key: Optional[str] = None):
        h = question_hash(text)
        self.seen_hashes.add(h)
        if fact_key:
            self.seen_fact_keys.add(fact_key)
        store.register(self.deck_id, h, fact_key or "", text)
