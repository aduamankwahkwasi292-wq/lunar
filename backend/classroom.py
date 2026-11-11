"""
Classroom tutor (MrSOLIS) — explains one slide at a time, chats, explains and solves.

The brain (backend/brain.py, a small model that can also see) is used ONLY for what it's
good at: explaining the current slide and chatting about it, grounded in that slide. It never
invents quiz questions or answers — those are produced deterministically in
`backend/questions.py` (cloze-free, slide-grounded, sympy-checked maths).
Every prompt is `_CORE` (who MrSOLIS is, how he talks) + a short task — see `_system`.
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
# A worked solution ends on its "Answer: x = 6" line (sometimes "x = 5 Answer: 5"), which has no full stop.
_FINAL_ANSWER = re.compile(r"(?i)\banswer\W*:\s*\S[^\n]*\s*\Z")   # anywhere on the last line


# The real model's (or its maker's) name never reaches the screen — the user's rule.
_HIDE = re.compile(r"(?i)\b(qwen[\w.-]*|alibaba|tongyi)")


async def _scrub(pieces):
    """Pass a token stream through with the real model's / maker's name replaced by MrSOLIS's.
    Text is released a word at a time, so a name split across tokens ("Q" + "wen") is caught."""
    held = ""
    async for piece in pieces:
        held += piece
        cut = max(held.rfind(" "), held.rfind("\n"))
        if cut >= 0:
            out, held = held[:cut + 1], held[cut + 1:]
            yield _HIDE.sub("MrSOLIS", out)
    if held:
        yield _HIDE.sub("MrSOLIS", held)


async def _stream_complete(messages, **kw):
    async for piece in _scrub(_stream_rounds(messages, **kw)):
        yield piece


async def _stream_rounds(messages, *, temperature, max_tokens,
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
        info = {}
        async for piece in local_llm.chat_stream(convo, temperature=temperature, max_tokens=budget, info=info):
            if rounds and not chunk and full and not full[-1].isspace() and piece[:1].isalnum():
                piece = " " + piece               # a continuation that starts a new word: "after The" not "afterThe"
            chunk += piece
            full += piece
            yield piece
        rounds += 1
        if not chunk.strip():
            return
        if info.get("finish") == "stop":          # the engine says the model finished by itself
            return
        if _SENTENCE_END.search(full) or _FINAL_ANSWER.search(full) or rounds > max_continuations:
            return
        convo = list(messages) + [
            {"role": "assistant", "content": full},
            {"role": "user", "content": "Continue from exactly where you left off and finish. "
                                        "Do not repeat anything you already wrote."},
        ]


# ======================================================================
# Who MrSOLIS is — one short block shared by every prompt
# ======================================================================
# The brains are small (8K context on a laptop, a picture alone can take ~800 tokens), so
# the persona is written once, kept near 140 tokens, and each task adds a sentence or two.
# Lessons from testing Qwen3.5-2B on 13 tutor situations (2026-10-20):
# - It parrots rules and quoted lines back to the student ("…in British English", "If you have a
#   fact wrong, correct it first") — so few rules, no scripts, nothing about models or secrecy.
# - Hard numbers next to the question work ("under 80 words"); "a few sentences" gave 371 words.
# - What a small model fumbles is decided in code instead: "what model are you?" (`_WHO`, a fixed
#   answer — it echoed "I'm not ChatGPT or Qwen"), title/outline/closing slides (`_heading_note`),
#   "I'm lost" (`_LOST`). `_scrub` is the last guard: the real model's name never reaches the
#   screen (the user's rule).
_CORE = (
    "You are MrSOLIS, an AI study tutor built into the MrSOLIS 3 app, running on this computer.\n"
    "Be a professional tutor: clear, precise, calm and encouraging. No emojis or flattery. When the "
    "student has a fact wrong, correct it first, then explain. Explain why, not only what. Never "
    "invent facts, numbers or formulas; say when you are unsure. Decline cheating or harm briefly, "
    "then offer honest help.\n"
    "Write short paragraphs, numbered steps and **bold** key terms; maths in plain text (x^2, "
    "(a+b)/c, √x); no tables or diagrams."
)

_SEE_SLIDE = "A picture of the slide is attached; its diagrams and labels are part of the slide."
_SEE_PHOTO = "The student attached a picture: read it carefully and use it. If it is unclear, say so."
# The answer sympy computed exactly: the brain explains toward it instead of doing fragile arithmetic.
_VERIFIED = " A solver has found the correct answer: {}. Show the steps that lead to it and state exactly this answer."


def _system(task: str, see: str = "") -> dict:
    """The system message: who MrSOLIS is, then this task (and what to do with a picture)."""
    # the picture note goes first: after "End with … **Key idea:**" it made the brain open with it
    return {"role": "system", "content": _CORE + "\n\n" + (see + " " if see else "") + task}


# ======================================================================
# Explanation — the tutor teaches the slide under the verbatim board image
# ======================================================================
# How much the tutor says per slide (Settings → Lesson length): the paragraphs asked for, and a word
# limit. Asked only for "2 short paragraphs", Smarts ran past its token cap on Short (the user saw it)
# and the old auto-continue kept it going, so every length is held three ways, for any brain:
#   1. the limit sits in the user turn, next to the slide ("…in under 120 words"), where small models obey;
#   2. past the limit + 30% the lesson stops at the next full stop (teach_slide_stream);
#   3. the token cap is set just above that, and a cut-off sentence gets one tiny top-up to finish.
_LESSON_LENGTH = {
    "short": ("2 short paragraphs", 120),
    "standard": ("3 to 4 short paragraphs", 220),
    "detailed": ("5 to 6 paragraphs, going through every example step by step", 380),
}
_SENTENCE_DONE = re.compile(r"[.!?][\"'”’)\]*]*\s*$")


def _with_picture(text: str, image):
    """A user message carrying a picture too (an OpenAI-style image part), for a brain that sees."""
    if not image:
        return text
    return [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": image}}]


_CLOSING = re.compile(r"(?i)^\W*(thank(s| you)\b|(any )?questions\W*$|q\s*&\s*a\b|the end\b|end of (the )?"
                      r"(lecture|chapter|presentation|session))")
_OUTLINE = re.compile(r"(?i)^\W*(outline|contents|table of contents|agenda|overview|objectives|learning "
                      r"(objectives|outcomes)|topics|in this (lecture|chapter|session))\b")


def _heading_note(text: str, slide_no: int) -> str | None:
    """What to say on a title, outline or closing slide, decided here rather than by the brain.

    Asked to keep such slides short, the brain wrote 200 words on the lecturer's "authority", or
    invented a lecture plan from a title. These slides need no teaching, so the note is fixed —
    and instant. Returns None for any slide worth teaching."""
    lines = [ln.strip(" •-–*\t") for ln in text.splitlines() if ln.strip(" •-–*\t")]
    words = sum(len(ln.split()) for ln in lines)
    if not lines or "=" in text or words > 40 or any(len(ln.split()) > 8 for ln in lines):
        return None
    if _CLOSING.match(lines[0]) and words <= 12:
        return ("That's the end of this lecture. Check what stuck with a quiz from **Quizzes**, or ask me "
                "about anything that wasn't clear.")
    if _OUTLINE.match(lines[0]) and len(lines) >= 2:
        items = "; ".join(lines[1:9])
        return f"This slide sets out what's coming: {items}. We'll take them one at a time — move on when you're ready."
    if slide_no == 1 and words <= 20:
        return (f"This is the title slide: **{lines[0]}**. Move to the next slide when you're ready, and I'll "
                "teach each one as we go.")
    return None


async def teach_slide_stream(slide_text: str, slide_no: int, total: int, length: str = "standard", image=None,
                             exact=None, prior: str = ""):
    """Stream the tutor's explanation of the slide (shown under the image).

    `image`: the slide's picture (data URL) when the brain can see — then a slide that is only a
    diagram or a photo can be taught too. `exact`: the slide's own questions that CUSTOM-Mx offers to work exactly
    under the lesson — the brain explains how to tackle them but leaves the final numbers to CUSTOM-Mx.
    `prior`: the lesson written so far (Interactive mode, after the student cut in): it carries on from there."""
    paragraphs, limit = _LESSON_LENGTH.get(length, _LESSON_LENGTH["standard"])
    words = _slide(slide_text).strip() if slide_text else ""
    ask = (f"Slide {slide_no} of {total}:\n\"\"\"\n{words}\n\"\"\"\n\nTeach this slide in under {limit} words." if words
           else f"Slide {slide_no} of {total} has no text: it is the picture attached. Teach this slide in "
                f"under {limit} words.")
    if exact and words:
        ask = ask.replace("\n\nTeach this slide", "\n\nThe app's maths engine will work the slide's question"
                          + ("s" if len(exact) > 1 else "") + " exactly, under your lesson. Explain the method and "
                          "the formula to use, but don't calculate the final numbers.\n\nTeach this slide", 1)
    note = _heading_note(words, slide_no) if words and not image and not prior else None
    if note:
        yield note
        return
    task = (f"Teach this slide in {paragraphs}: its key ideas and why they matter, then any example "
            "or formula step by step. Use only its facts (an everyday analogy is fine). Don't greet, "
            "repeat the slide or ask questions. Close with a one-sentence summary.")
    # (not "End with **Key idea:** …": on picture slides the brain opened with that label instead)
    messages = [_system(task, _SEE_SLIDE if image else ""),
                {"role": "user", "content": _with_picture(ask, image)}]
    if prior:                                              # as _stream_rounds carries on a cut-off answer
        messages += [{"role": "assistant", "content": prior},
                     {"role": "user", "content": "Continue from exactly where you left off and finish. "
                                                 "Do not repeat anything you already wrote."}]
    ceiling = int(limit * 1.3)
    text = prior or ""
    async for piece in _stream_complete(messages, temperature=0.5, max_tokens=int(ceiling * 1.8) + 40,
                                        max_continuations=1, cont_tokens=60):
        text += piece
        yield piece
        if len(text.split()) > ceiling and _SENTENCE_DONE.search(text):
            break                                          # long enough: stop at this full stop


def is_lesson_slide(slide_text: str, slide_no: int, image=None) -> bool:
    """False for title / outline / closing slides, which get a fixed note (with its own way on) instead."""
    words = _slide(slide_text).strip() if slide_text else ""
    return not (words and not image and _heading_note(words, slide_no))


def lesson_transition(slide_no: int, total: int, next_title: str = "", at_end: bool = False) -> str:
    """What MrSOLIS says after teaching a slide: the way on to the next one, or — after the last slide
    worth teaching — a professional close. Fixed text, so it never costs a token or goes astray."""
    if at_end or slide_no >= total:
        return ("That brings us to the end of this lecture. Check what stuck with a quiz from **Quizzes**, "
                "or ask me about anything that wasn't clear.")
    t = re.sub(r"\s+", " ", (next_title or "")).strip().rstrip(".:;,")
    if not t or re.fullmatch(r"(?i)(slide|page)\s*\d+", t):
        return "When you're ready, let's move on to the next slide."
    return (f"When you're ready, let's move on to the next slide: **{t}**.",
            f"Next, we'll look at **{t}**.",
            f"Let's continue with **{t}** on the next slide.")[slide_no % 3]


# ======================================================================
# Free chat (questions about the slide; explaining the current quiz Q)
# ======================================================================
# "I'm lost" / "I don't understand this slide at all" / "explain again" — nothing more specific.
_LOST = re.compile(r"(?i)^\W*(i\s*(still\s*)?(do\s*n[o']?t|dont|didn'?t|can'?t|cannot)\s*(understand|get|follow)"
                   r"(\s+(it|this|that|anything|any of (it|this)|the slide|this slide|what you said))?(\s+at all)?"
                   r"|i'?m\s*(so\s*|really\s*)?(lost|confused)|(i'?m\s*)?confused|lost|huh|what|explain\s*(it|this|that)?\s*again"
                   r"|(please\s*)?(go over|repeat) (it|this|that)( again)?)\W*$")


# "Which model are you?", "Are you ChatGPT?", "Who made you?" — answered here, never by the brain.
_WHO = re.compile(
    r"(?i)(\b(what|which)\s+(ai|model|llm|language model|chat\s*bot|bot|version)\s+(are|is|r)\s+(you|u|this)\b"
    r"|\b(are|r)\s+(you|u)\s+(an?\s+)?(ai|robot|bot|human|person|real|chat\s*gpt|gpt[\w.-]*|gemini|claude|"
    r"llama|qwen[\w.-]*|deepseek|copilot|bard|mistral|grok)\b"
    r"|\bwho\s+(made|built|created|trained|developed|programmed|owns|designed)\s+(you|u|this app)\b"
    r"|\bwhat'?s?\s+(is\s+)?your\s+name\b|^\W*(who|what)\s+are\s+(you|u)\W*$"
    r"|\b(model|ai|llm)\s+(do you use|are you using|are you based on|powers you|is behind you|runs you)\b"
    r"|\bpowered\s+by\b)")


# "Ignore your instructions", "print your system prompt": asked this, the brain recited its rules.
_META = re.compile(r"(?i)\b(ignore|forget|disregard|override)\s+(all\s+|any\s+)?(your|the|previous|prior|above|earlier)"
                   r"(\s+(previous|prior))?\s+(instructions|rules|prompt|guidelines)\b|\bsystem\s+prompt\b"
                   r"|\b(reveal|show|print|repeat|tell me)\s+(me\s+)?(your|the)\s+(hidden\s+)?(instructions|rules|prompt)\b"
                   r"|\bjail\s*break|\bdeveloper\s+mode\b")


def _who_answer(on_slide: bool) -> str:
    return ("I'm MrSOLIS, the AI study tutor built into MrSOLIS 3. I run entirely on this computer, so your "
            "slides and questions stay private. " + ("What would you like to know about this slide?" if on_slide
                                                    else "What would you like to study?"))


def fixed_answer(message: str, on_slide: bool) -> str | None:
    """Questions about MrSOLIS itself get a fixed answer, never the brain's."""
    if _META.search(message or ""):
        return ("I can't do that, but I'm glad to help you study. " +
                ("What would you like to know about this slide?" if on_slide else "What are you working on?"))
    if _WHO.search(message or ""):
        return _who_answer(on_slide)
    return None


def _history_block(history, limit: int = 4) -> str:
    lines = []
    for item in (history or [])[-limit:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role in ("user", "assistant") and content:
            who = "Student" if role == "user" else "MrSOLIS"
            lines.append(f"{who}: {content[:240]}")
    return "\n".join(lines)


async def chat_stream(slide_text: str, user_message: str, history=None, focus=None, image=None, photo=False,
                      subject=None):
    """Stream the tutor's reply to whatever the student says, on the current slide. `subject`: the whole deck's
    text or word stems (`on_subject`), else the slide's own words decide whether a question is on the subject.

    `image`: a picture for a brain that sees — the slide's own (photo=False) or one the student
    attached (photo=True).
    `focus` (optional) is the quiz question + answer the student is currently on,
    so "explain this question" elaborates on THAT exact question instead of
    drifting to a new one.
    """
    fixed = fixed_answer(user_message, on_slide=True)       # even with the slide's picture attached
    if fixed:
        yield fixed
        return
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
    # "I don't understand" with no detail: told so in the system prompt, the brain re-taught the
    # whole slide (160+ words), so the instruction goes right next to the student's words.
    how = ("They haven't said which part is unclear: in under 60 words, sum up the slide in one simple "
           "sentence, then ask which part or term is unclear." if _LOST.match(user_message or "")
           else "Reply as MrSOLIS in under 150 words.")
    user += (
        f"Current slide:\n\"\"\"\n{_slide(slide_text)}\n\"\"\"\n\n"
        f'Student just said: "{user_message}"\n\n{how}'
    )
    # The user (2026-11-11): a question on the subject that the slide doesn't cover is simply answered ("this
    # isn't covered in the slide… I'll answer from general knowledge…" helps nobody), and a question that has
    # nothing to do with the studies is still answered, then the student is nudged back to the lesson. Code decides
    # which it is (`on_subject`: the question's words against the whole deck). Told both rules at once Smarts refused
    # off-topic questions and nudged on-topic ones; shown the lesson with an off-topic question it still refused
    # ("I cannot answer questions outside my subject matter") — so an off-topic question is asked on its own, and
    # the nudge back is added here, as the upload reminder is when no slides are open.
    if not on_subject(user_message, subject or slide_text):
        topic = next((ln.strip(" •-–*#") for ln in _slide(slide_text).splitlines() if ln.strip(" •-–*#")), "")
        # short: asked for "one or two sentences" with room for more, Smarts added lists and wrong details (dates,
        # scores) after a right first sentence
        messages = [_system("Answer the student's question correctly and plainly in one or two short sentences.",
                            _SEE_PHOTO if (image and photo) else ""),
                    {"role": "user", "content": _with_picture(f'Student asks: "{user_message}"', image if photo else None)}]
        wrote = False
        async for piece in without_disclaimers(_stream_complete(messages, temperature=0.3, max_tokens=90,
                                                                max_continuations=1, cont_tokens=40)):
            wrote = wrote or bool(piece.strip())
            yield piece
        if wrote:
            yield "\n\n" + back_to_lesson(topic, len(history or []))
        return
    task = ("The student is studying the slide below and asks you something. Answer it directly and fully, like "
            "a tutor who knows the subject: use the slide where it helps and your own knowledge where it doesn't. "
            "Never say whether the slide covers it.")
    messages = [_system(task, (_SEE_PHOTO if photo else _SEE_SLIDE) if image else ""),
                {"role": "user", "content": _with_picture(user, image)}]
    async for piece in without_disclaimers(_stream_complete(messages, temperature=0.6, max_tokens=420,
                                                            max_continuations=2, cont_tokens=200)):
        yield piece


_BACK = ["Now, let's get back to {t}.", "Okay, back to {t} now.", "Right, let's get back to {t} — you're doing well."]


def back_to_lesson(topic: str, turn: int = 0) -> str:
    """The friendly nudge after an off-topic answer (varied, so it doesn't sound like a stuck record)."""
    t = re.sub(r"\s+", " ", topic or "").strip().rstrip(".:;,")[:60] or "your lesson"
    return _BACK[turn % len(_BACK)].format(t=t)


# A word in the question that the deck also uses means the question is about what they are studying. 3-letter
# words count ("Ohm", "law"); question words and filler don't.
_FILLER = set("the and for are was were you your how why who whom what which when where does did can could would "
              "should will shall may might must has have had having been being this that these those there their "
              "they them with from into onto than then about also just like more most much many some such very "
              "really please tell explain mean means meaning work works thing things something anything slide slides "
              "lesson lecture note notes question answer know think want need help understand get got not but its "
              "it's isn't aren't don't doesn't one two all any our out use used using way ways again simple simply "
              "example examples part bit step steps okay yes sure now here still even well other another same "
              "different called last next first point points again".split())


def _stems(text: str) -> set:
    return {w[:5] for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in _FILLER}


def on_subject(question: str, subject) -> bool:
    """Is the question about what the student is studying? `subject`: the deck's text (or its word stems). A
    question with no content words of its own ("what does this mean?") is about the slide."""
    words = _stems(question)
    if not words:
        return True
    have = subject if isinstance(subject, (set, frozenset)) else _stems(subject)
    return bool(words & have)


# "The slide doesn't cover this, so from general knowledge: …" — told not to, Smarts still said it; the sentence
# loses that clause and keeps the answer after it (or goes, if nothing is left).
_DISCLAIMER = re.compile(
    r"(?i)\b(?:(?:the|this|your|these) (?:slides?|lecture|notes?|material|video)s? (?:doesn'?t|does not|don'?t|do not|"
    r"didn'?t|did not|isn'?t|is not) (?:directly |explicitly |specifically )?(?:cover|mention|address|discuss|say|"
    r"explain|include|show|go into|talk about|state)|(?:not|isn'?t|aren'?t) (?:covered|mentioned|addressed|discussed|"
    r"explained|included|shown|stated) (?:directly |explicitly )?(?:in|on|by) (?:the|this|your) (?:slides?|lecture|"
    r"notes?|video)|(?:from|using|based on|drawing on|relying on|with) (?:my |your |our )?(?:own |general |outside |"
    r"broader |wider )?knowledge|you (?:must|will have to|have to|need to|can) use your own knowledge|beyond (?:what|"
    r"the scope of) (?:the|this) (?:slide|lecture|video))")
_CLAUSE = re.compile(r"[:,;]|\s(?:but|however|so)\s")


def _undisclaim(sentence: str) -> str:
    s = sentence
    for _ in range(3):
        m = _DISCLAIMER.search(s)
        if not m:
            return s
        after = _CLAUSE.search(s, m.end())
        before = max(s.rfind(",", 0, m.start()), s.rfind(";", 0, m.start()))
        if after and len(s[after.end():].split()) >= 4:
            rest = re.sub(r"(?i)^(?:but|however|so|and|though|although|yet)\b[,\s]*", "", s[after.end():].strip())
            s = rest[:1].upper() + rest[1:]
        elif before > 0 and len(s[:before].split()) >= 4:
            s = s[:before].rstrip() + "."
        else:
            return ""
    return s


_SENT_END = re.compile(r"(?<=[.!?])[\"'”’)\]*]*\s+|\n+")


async def without_disclaimers(pieces):
    """A stream with "the slide doesn't cover this… from general knowledge" taken out, a sentence at a time."""
    held = ""
    async for piece in pieces:
        held += piece
        while True:
            m = _SENT_END.search(held)
            if not m:
                break
            sentence, gap, held = held[:m.start()], held[m.start():m.end()], held[m.end():]
            kept = _undisclaim(sentence)
            if kept.strip():
                yield kept + gap
            elif "\n" in gap:
                yield "\n" if "\n\n" not in gap else "\n\n"
    if held:
        kept = _undisclaim(held)
        if kept.strip():
            yield kept


# ======================================================================
# Chat with no slides open — general help, and always a nudge to upload
# ======================================================================
_NUDGES = [
    "To really learn this, upload your slides or notes — drop the file in the middle of the screen and "
    "I'll teach it to you slide by slide.",
    "Got lecture slides or notes on this? Upload them and we'll go through them together, "
    "with quizzes to check you've got it.",
    "I teach best from your own material: upload your slides and I'll explain exactly what "
    "your lecturer covers.",
    "Ready to study properly? Drop your slides or a PDF in the middle of the screen and class starts straight away.",
]


def upload_nudge(turn: int, recent_decks=None) -> str:
    """The reminder that ends every reply while no slides are open. Varies with the turn so it
    doesn't read like a stuck record; offers the last deck the student studied, if any."""
    decks = [d for d in (recent_decks or []) if d]
    if decks and turn % 2 == 0:
        return (f"Want to carry on with “{decks[(turn // 2) % len(decks)]}”? Open it from "
                "Uploads — or drop new slides in the middle of the screen to start learning.")
    return _NUDGES[(turn // 2 if decks else turn) % len(_NUDGES)]


async def free_chat_stream(user_message: str, history=None, recent_decks=None, image=None):
    """Stream MrSOLIS's reply when the student chats without any slides open (`image`: a picture
    the student attached, for a brain that sees)."""
    fixed = fixed_answer(user_message, on_slide=False)
    if fixed:
        yield fixed
        turn = sum(1 for h in (history or []) if isinstance(h, dict) and h.get("role") == "user")
        yield "\n\n" + upload_nudge(turn, recent_decks)
        return
    convo = _history_block(history)
    user = ("Recent conversation:\n" + convo + "\n\n") if convo else ""
    user += f'Student just said: "{user_message}"\n\nReply as MrSOLIS in under 150 words.'
    task = (
        "No slides are open: answer directly from what you know, with numbered steps for a problem. If "
        "they only greet you, greet them in one sentence and ask what they are studying. Add no "
        "sign-off or follow-up question; the app adds one."
    )
    messages = [_system(task, _SEE_PHOTO if image else ""),
                {"role": "user", "content": _with_picture(user, image)}]
    wrote = False
    async for piece in without_disclaimers(_stream_complete(messages, temperature=0.6, max_tokens=360,
                                                            max_continuations=2, cont_tokens=200)):
        wrote = wrote or bool(piece.strip())
        yield piece
    if wrote:
        turn = sum(1 for h in (history or []) if isinstance(h, dict) and h.get("role") == "user")
        yield "\n\n" + upload_nudge(turn, recent_decks)


# ======================================================================
# A video the student attached (backend/video.py prepares it: frames + what is said)
# ======================================================================
_SEE_VIDEO = ("Frames from the video are attached in time order, each after its time (m:ss); what is said "
              "comes as a transcript with times.")
_VIDEO_FRAMES = 6            # ~240 picture tokens each for the Qwen brains at 640 px
_VIDEO_SAID = 2600           # tokens of transcript shown with every question (about 30 min of a 100 words/min talk)
_VIDEO_MATCH = 700           # long videos: more of what is said, picked for the question
_VIDEO_SEEN = "I have watched the video and read what is said in it. What would you like to know?"


def video_messages(meta: dict, frames: list, user_message: str, history=None) -> list:
    """The chat for a question about a prepared video. `frames`: [(seconds, data URL)].

    The video is a message of its own (all of what is said for a talk up to ~30 min, else an even
    spread, and the same frames), answered by a fixed line, and the question comes in a new message.
    It is the same for every question, so the engine keeps it: the engine saves its place at the start
    of the student's last message (never inside pictures), and the hybrid Qwen3.5 brains can only resume
    from such a saved place. Measured on Speedy: with the video and question in one message every
    follow-up re-read ~1,170 of 1,390 tokens. For a long video, pieces of the talk that share words
    with the question go with the question (`video.matching`)."""
    from backend import video
    said, _shown, complete = video.overview(meta, _VIDEO_SAID, _VIDEO_FRAMES)
    head = f'The student attached a video: "{meta["name"]}" ({video.stamp(meta["duration"])} long).\n'
    if not meta.get("sound"):
        head += "It has no sound.\n"
    elif not meta.get("heard"):
        head += "This computer can't listen to its sound, so only the frames are shown.\n"
    elif not meta["segments"]:
        head += "No speech was heard in it.\n"
    else:
        head += ("What is said (with times):\n" if complete else
                 "What is said — pieces spread through the video (it is too long to show all):\n")
        head += "\n".join(f"[{video.stamp(s['t'])}] {s['text']}" for s in said) + "\n"
    content = [{"type": "text", "text": head + ("\nFrames from the video:" if frames else "")}]
    for t, url in frames:
        content += [{"type": "text", "text": f"\n[{video.stamp(t)}]"}, {"type": "image_url", "image_url": {"url": url}}]
    tail = ""
    if not complete:
        extra = video.matching(meta, user_message, said, _VIDEO_MATCH)
        if extra:
            tail += "More of what is said, about the question:\n" + \
                    "\n".join(f"[{video.stamp(s['t'])}] {s['text']}" for s in extra) + "\n\n"
    convo = _history_block(history)
    if convo:
        tail += "Recent conversation:\n" + convo + "\n\n"
    tail += f'Student asks: "{user_message}"\n\nReply as MrSOLIS in under 150 words.'
    task = ("The student is asking about the video. Answer from what it shows and says, and give the time "
            "(m:ss) of the part you use. If the video doesn't cover the question, just answer it from what you "
            "know, without saying so.")
    return [_system(task, _SEE_VIDEO if frames else ""), {"role": "user", "content": content},
            {"role": "assistant", "content": _VIDEO_SEEN}, {"role": "user", "content": tail}]


async def video_chat_stream(meta: dict, frames: list, user_message: str, history=None):
    """Stream the tutor's answer to a question about a video (see `video_messages`)."""
    fixed = fixed_answer(user_message, on_slide=False)
    if fixed:
        yield fixed
        return
    # questions about a video are about what it says and shows: keep the brain close to it (at 0.5 Speedy once
    # turned "fourteen forty" into 1400 rpm and a 0.4% slip, after three right runs)
    async for piece in without_disclaimers(_stream_complete(video_messages(meta, frames, user_message, history),
                                                            temperature=0.2, max_tokens=420, max_continuations=2,
                                                            cont_tokens=200)):
        yield piece


# ======================================================================
# Highlight → Explain / Solve a portion of the slide or lecture
# ======================================================================
async def explain_stream(slide_text: str, selection: str, mode: str = "explain",
                         history=None, context: str = "", verified: str = ""):
    """Explain (or solve) the portion the student highlighted, grounded in the slide.

    `context` = relevant facts retrieved from elsewhere in the deck (RAG) so the small
    model has the exact definitions/formulas it needs. `verified` = an answer computed
    exactly by sympy (solve mode) so the model explains toward the correct result
    instead of doing fragile arithmetic itself.
    """
    sel = (selection or "").strip()[:1200]
    if mode == "solve":
        task = (
            "Solve the highlighted question step by step with the slide's methods, one line of working "
            "per step with units, then give the key idea in one sentence. If the slide lacks what is "
            "needed, say what is missing."
        )
        if verified:
            task += _VERIFIED.format(verified)
        ask = f"Solve this, showing each step, then explain:\n\"\"\"\n{sel}\n\"\"\""
    else:
        task = "Explain the highlighted part simply, using the slide; add a tiny example if it helps."
        ask = f"Explain this part in 2 to 4 sentences, under 80 words:\n\"\"\"\n{sel}\n\"\"\""
    convo = _history_block(history)
    user = ("Recent conversation:\n" + convo + "\n\n") if convo else ""
    user += f"Current slide:\n\"\"\"\n{_slide(slide_text)}\n\"\"\""
    if context:
        user += ("\n\nRelevant facts from elsewhere in your notes (use if helpful):\n"
                 f"\"\"\"\n{context[:900]}\n\"\"\"")
    user += f"\n\n{ask}\n\nReply as MrSOLIS."
    messages = [_system(task), {"role": "user", "content": user}]
    budget = 480 if mode == "solve" else 220
    async for piece in _stream_complete(messages, temperature=0.5, max_tokens=budget,
                                        max_continuations=2, cont_tokens=220):
        yield piece


async def explain_working_stream(problem: str, working: str, slide_text: str = ""):
    """CUSTOM-Mx has already worked the problem (shown to the student above this reply): the brain only says why
    the method fits and what the answer means. It never redoes the arithmetic, which is what it gets wrong."""
    task = ("CUSTOM-Mx, the app's maths engine, has worked this problem and its working is shown to the student "
            "just above your reply. In 2 to 3 sentences, explain the idea: why this formula or method fits the "
            "question and what the answer means. Don't redo the arithmetic or repeat the working.")
    user = (f"Current slide:\n\"\"\"\n{_slide(slide_text)}\n\"\"\"\n\n" if slide_text else "")
    user += f"Problem:\n\"\"\"\n{(problem or '').strip()[:800]}\n\"\"\"\n\nWorking:\n{working}\n\nReply as MrSOLIS in under 70 words."
    messages = [_system(task), {"role": "user", "content": user}]
    async for piece in _stream_complete(messages, temperature=0.4, max_tokens=170,
                                        max_continuations=1, cont_tokens=60):
        yield piece


# ======================================================================
# Tools → Solver: any maths / science problem, not tied to a slide
# ======================================================================
async def solve_free_stream(problem: str, verified: str = ""):
    """Stream a step-by-step solution of a problem typed into the Solver."""
    task = ("Solve the problem step by step, one line of working per step with units, then a last "
            "line starting 'Answer:'. Keep it short.")
    if verified:
        task += _VERIFIED.format(verified)
    ask = f"Solve:\n\"\"\"\n{(problem or '').strip()[:1200]}\n\"\"\""
    messages = [_system(task), {"role": "user", "content": ask}]
    async for piece in _stream_complete(messages, temperature=0.3, max_tokens=520,
                                        max_continuations=2, cont_tokens=220):
        yield piece
