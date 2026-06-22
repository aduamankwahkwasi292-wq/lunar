"""
Classroom tutor for Lunar — explains one slide at a time, then quizzes.

The LLM (qwen2.5:1.5b) is used ONLY for what it's good at: explaining the current
slide and chatting about it, always grounded in that slide's text. It never
invents quiz questions or answers — those are produced deterministically in
`backend/questions.py` (cloze-free, slide-grounded, sympy-checked maths).
"""

import re

from backend import local_llm

# Keep slide text small so the prompt stays tiny and inference stays quick.
_MAX_SLIDE_CHARS = 2400


def _slide(text: str) -> str:
    text = (text or "").strip()
    return text[:_MAX_SLIDE_CHARS]


# ======================================================================
# Reference / dedication filtering (kept off the board, never quizzed)
# ======================================================================
_REF_LINE = re.compile(
    r"^\s*("
    r"references?|bibliography|works cited|further reading|"
    r"acknowledge?ments?|dedication|dedicated to\b|"
    r"(lecturer|instructor|professor|presented by|prepared by|compiled by|"
    r"submitted (to|by)|authors?)\s*[:\-]|"
    r"department of|faculty of|school of|university of|college of)",
    re.I,
)
_DEDICATION = re.compile(
    r"\b(to my (parents|mum|mom|dad|mother|father|family|wife|husband|friends)|"
    r"i (would like to|want to|wish to) thank|special thanks|with gratitude|"
    r"in memory of)\b",
    re.I,
)
_CITATION = re.compile(r"\(\d{4}[a-z]?\)")  # "(2019)" style year, used with a comma


def _is_reference_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if _REF_LINE.match(s) or _DEDICATION.search(s):
        return True
    # Bibliography entry: a year-in-parentheses plus a comma (author list).
    if _CITATION.search(s) and "," in s and len(s) < 300 and "http" not in s.lower():
        return True
    return False


def clean_board_text(text: str) -> str:
    """Return the slide text verbatim with only reference/dedication lines removed."""
    lines = (text or "").splitlines()
    kept = [ln for ln in lines if not _is_reference_line(ln)]
    out = "\n".join(kept)
    # Collapse runs of blank lines left behind by removed entries.
    return re.sub(r"\n{3,}", "\n\n", out).strip()


# ======================================================================
# Streaming with a completeness guarantee
# ======================================================================
_SENTENCE_END = re.compile(r"[.!?…][)\]\"'”’]?\s*$")


async def _stream_complete(messages, *, temperature, max_tokens,
                           max_continuations: int = 2, cont_tokens: int = 220):
    """Stream a chat completion, auto-continuing if the model gets cut off.

    Small models on CPU regularly hit the token budget mid-sentence. After each
    round we check whether the output ends on sentence-final punctuation; if not
    (and we have continuations left) we ask the model to continue from exactly
    where it stopped, so the reply always finishes cleanly.
    """
    full = ""
    convo = list(messages)
    rounds = 0
    while True:
        budget = max_tokens if rounds == 0 else cont_tokens
        chunk = ""
        async for piece in local_llm.chat_stream(convo, temperature=temperature, max_tokens=budget):
            chunk += piece
            full += piece
            yield piece
        rounds += 1
        if not chunk.strip():
            return
        if _SENTENCE_END.search(full) or rounds > max_continuations:
            return
        convo = list(messages) + [
            {"role": "assistant", "content": full},
            {"role": "user", "content": "Continue from exactly where you left off and finish. "
                                        "Do not repeat anything you already wrote."},
        ]


# ======================================================================
# Explanation — Lunar teaches the slide under the verbatim board image
# ======================================================================
async def teach_slide_stream(slide_text: str, slide_no: int, total: int):
    """Stream Lunar's tutoring explanation of the slide (shown under the image)."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are Lunar, a professor teaching from a slide the student can "
                "already SEE on the board. Teach it in 3 to 5 short paragraphs: explain "
                "the key ideas and the intuition, walk through any worked example or "
                "formula on the slide, then end with a one-sentence takeaway. Be a real "
                "tutor (not a dry summary), but stay FOCUSED and keep it tight enough to "
                "FINISH — your last sentence must be complete, never cut off mid-thought. "
                "Use ONLY what is on this slide; add no outside facts and do not just "
                "repeat the slide word for word. Do not ask the student a question.\n"
                "Write maths in plain, readable text, NEVER LaTeX: no backslash commands, "
                "no \\(...\\) or \\[...\\] or $...$, no \\frac or \\leq. Write '≤', '≥', "
                "'×', '√', superscripts like 'n^2', and fractions like '(a+b)/c'. NEVER try "
                "to draw a number line, graph, table, diagram or ASCII art — describe it in "
                "a sentence instead (e.g. 'on the number line, all points left of 0')."
            ),
        },
        {
            "role": "user",
            "content": f"Slide {slide_no} of {total}:\n\"\"\"\n{_slide(slide_text)}\n\"\"\"\n\nGive your detailed lecture.",
        },
    ]
    async for piece in _stream_complete(messages, temperature=0.5, max_tokens=768,
                                        max_continuations=2, cont_tokens=256):
        yield piece


# ======================================================================
# Free chat (questions about the slide; explaining the current quiz Q)
# ======================================================================
def _history_block(history, limit: int = 4) -> str:
    lines = []
    for item in (history or [])[-limit:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role in ("user", "assistant") and content:
            who = "Student" if role == "user" else "Lunar"
            lines.append(f"{who}: {content[:240]}")
    return "\n".join(lines)


async def chat_stream(slide_text: str, user_message: str, history=None, focus=None):
    """Stream Lunar's reply to whatever the student says, on the current slide.

    `focus` (optional) is the quiz question + answer the student is currently on,
    so "explain this question" elaborates on THAT exact question instead of
    drifting to a new one.
    """
    convo = _history_block(history)
    user = ""
    if convo:
        user += "Recent conversation:\n" + convo + "\n\n"
    if focus and focus.get("q"):
        user += (
            "The student is currently on this quiz question:\n"
            f"Question: {focus.get('q')}\n"
            f"Correct answer: {focus.get('a', '')}\n"
            "If they ask you to explain or go over it, explain THIS exact question "
            "and why that is the answer — do NOT make up a different question.\n\n"
        )
    user += (
        f"Current slide:\n\"\"\"\n{_slide(slide_text)}\n\"\"\"\n\n"
        f'Student just said: "{user_message}"\n\nReply as Lunar.'
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are Lunar, a warm, patient tutor on the current slide. Use ONLY "
                "this slide.\n"
                "- If the student says they don't understand or asks you to go over "
                "it but does NOT say which part, ask them which specific part or term "
                "is confusing — do not re-explain everything yet.\n"
                "- If they name what confuses them, explain THAT part clearly and "
                "simply, in a different way than before, with a small example if it "
                "helps.\n"
                "- For any other question, answer it using only the slide.\n"
                "If something isn't on this slide, say it's covered on another slide. "
                "Never repeat your previous wording verbatim. Be concise and kind. "
                "Write maths in plain text (≤ ≥ × √, 'n^2', '(a+b)/c'), never LaTeX, and "
                "never draw number lines, graphs, tables, diagrams or ASCII art — describe "
                "them in words."
            ),
        },
        {"role": "user", "content": user},
    ]
    async for piece in _stream_complete(messages, temperature=0.6, max_tokens=420,
                                        max_continuations=2, cont_tokens=200):
        yield piece


# ======================================================================
# Highlight → Explain / Solve a portion of the slide or lecture
# ======================================================================
async def explain_stream(slide_text: str, selection: str, mode: str = "explain", history=None):
    """Explain (or solve) the portion the student highlighted, grounded in the slide."""
    sel = (selection or "").strip()[:1200]
    if mode == "solve":
        system = (
            "You are Lunar, a warm tutor. The student highlighted a QUESTION or exercise. "
            "Solve it step by step using ONLY the methods, formulas and facts on this slide — "
            "show your working clearly, then briefly explain the key idea behind the steps. If "
            "the slide doesn't give enough to solve it, say so and explain what the question is "
            "asking. Write maths in plain text (≤ ≥ × √, 'n^2', '(a+b)/c'), NEVER LaTeX, and never draw number lines/graphs/diagrams/ASCII art (describe them in words). Finish "
            "completely."
        )
        ask = f"Solve this, showing each step, then explain:\n\"\"\"\n{sel}\n\"\"\""
    else:
        system = (
            "You are Lunar, a warm tutor. Explain the highlighted portion clearly and simply "
            "in a SHORT, FOCUSED way (a few sentences) — using ONLY this slide, with a tiny "
            "example if it helps. Get to the point and finish completely. Write maths in plain "
            "text (≤ ≥ × √, 'n^2', '(a+b)/c'), NEVER LaTeX, and never draw number "
            "lines/graphs/diagrams/ASCII art (describe them in words)."
        )
        ask = f"Explain this part simply:\n\"\"\"\n{sel}\n\"\"\""
    convo = _history_block(history)
    user = ("Recent conversation:\n" + convo + "\n\n") if convo else ""
    user += f"Current slide:\n\"\"\"\n{_slide(slide_text)}\n\"\"\"\n\n{ask}\n\nReply as Lunar."
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    budget = 480 if mode == "solve" else 320
    async for piece in _stream_complete(messages, temperature=0.5, max_tokens=budget,
                                        max_continuations=2, cont_tokens=220):
        yield piece
