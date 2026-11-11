# Lunar AI — project guide for Claude Code

Lunar AI is a **100% local, offline study app**, shipped as a **cross-platform Electron desktop app**
(Windows/macOS/Linux) — one double-click installer, models bundled, zero setup. Upload slides → a
full-screen hologram classroom where an AI tutor (**Lunar**) teaches slide-by-slide on the board. No
cloud, no API keys. Stack: Electron shell (`desktop/`) → spawns a PyInstaller-frozen FastAPI backend
(`backend/`) → runs `Qwen2.5-1.5B-Instruct` (chat) + `nomic-embed-text-v1.5` (embeddings) **in-process
via llama.cpp** (`llama-cpp-python`); vanilla-JS frontend; RapidOCR + PDFium (`backend/pdf.py`) for PDF pages and image-slide OCR.
**No voice.** `backend/local_llm.py` defaults to the llama.cpp backend and falls back to Ollama only in
dev when the GGUFs aren't present (`LUNAR_LLM_BACKEND=auto`). Build steps: see `BUILD.md`
(`scripts/fetch_models.py` then `scripts/build_desktop.py`, run per-OS).

## MrSOLIS 3 UI (the live frontend, `/app`)
The app is being rebranded **MrSOLIS 3**: a **black & white**, futuristic UI built in plain HTML/CSS/SVG.
**Layout since 2026-11-11 (the user's design, "kinda like Copilot in VS Code"):** the sidebar on the left; the slide
as large as it fits in the middle, on a dark viewer (`#class-main` → `#board`, which keeps its old ids and parts — the
steel frame `#board-frame` and the silver surface are hidden by the CSS section "THE CLASSROOM LAYOUT" at the end of
mrsolis.css, which overrides the older rules above it); **Interactive mode** and Look at slides under the slide
(`#class-under`); MrSOLIS's lessons and answers in the right-hand panel (`#talk-panel` → `#talk-scroll` →
`#talk-area`, rendered by mrsolis-wire.js), with the tip and a two-row typing bar under them; Find anything centred in
the 56 px title bar, Focus and Settings top right. **Focus** hides the sidebar so the slide and the panel fill the
window. Words-only slides sit on a white `.cr-sheet`. **Zoom** (2026-11-11): `#zoom-bar` at the viewer's
bottom-left (− / level = fit / +), Ctrl + wheel or a pinch, Ctrl +/−/0; 50–400% of the fitted size (`S.zoom`,
mrsolis-wire.js `applyZoom`): a picture gets a width, a sheet CSS `zoom`; kept across a deck's slides, fit for a new
deck; a MutationObserver on #slide-area re-applies it to every new slide; `#cr-board.zoomed` scrolls sideways.
**Box-select** on a slide picture (`marqueeEnd`): a word counts when the box covers half its width (or half the box)
and 40% of its height (or of a thin box) — it used to need the word's centre inside, and the PDF's word boxes are
taller than the letters, so a snug box round one word failed (the user, 2026-11-11; marquee-test.js).
  The real cause of both reports: `backend/pdf.py` took PDFium's text and object positions as if every page started at
  0,0. Books often don't (the student's 1118-page textbook: 42, 43.3), so every word box was 6.9 % right and 5.7 %
  high and a box picked the words two lines below. `_origin()` (the crop box's corner) is now subtracted in
  `words()` and `objects()`: on that page 96 % of word boxes sit on their ink (41 % before). Before, the slide sat small on a silver board with the lesson
under it (the user: "impossible to read anything"). Check layouts at real window sizes with
`Downloads\lunar\class-board-test\shoot.mjs` (headless Edge; the preview pane is too small). `frontend/index.html`
loads:
- `static/mrsolis.css` — all styles (Inter Tight bundled in `static/fonts/`, no web fonts).
- `static/mrsolis-scene.js` — the backdrop canvas (stars, greyscale moon, floor grid) and the board frame SVG,
  redrawn to the board's size. Its frame insets must match `#board`'s `--frame-*` in the CSS.
- `static/mrsolis-wire.js` — wiring to the backend (upload, teach, chat, explain/solve, search, progress, the
  slide ladder). PDF pages and images show in their own colours, like a printed sheet on the silver (the
  student asked for this, 2026-10-18 — they used to be recoloured to "chalk"); cached as `page_N.png`.
  **PowerPoint decks** are drawn by an office suite on the computer (`file_processor.office_to_pdf`: PowerPoint or
  WPS via COM from a hidden PowerShell, else LibreOffice headless) into `uploads/<id>.pdf`, then go through the PDF
  board pipeline (`ppt_render_path`); titles and speaker notes come from the .pptx (hidden slides skipped, as in the
  PDF). With no office suite (or a file PowerPoint refuses), MrSOLIS draws the slides itself: `backend/pptx_render.py`
  paints backgrounds (slide→layout→master, theme textures), template shapes, pictures, shapes incl. freeforms
  (even-odd holes), tables from the deck's own tableStyles.xml, SmartArt (its saved drawing), groups, rotation,
  and text with PowerPoint's inheritance (placeholder→layout→master→txStyles), theme fonts/colours, bullets
  (symbol fonts via encoding="symb"), 1.2× single line spacing, saved autofit scale. Fonts come from Windows
  Fonts + Microsoft 365 CloudFonts (Aptos), indexed by full name ("Arial Black"). Board kind "pptx"; each
  slide's word boxes are saved as `page_N.png.words.json` for box-select. Compared slide-by-slide against
  PowerPoint's own PDFs of the student's decks (scratch tool: compare.py). `LUNAR_NO_OFFICE=1` forces this path. Old block-style PowerPoint decks are redrawn once
  when opened (`_upgrade_ppt_session`), keeping the student's place. The student reported blocks "mangle" slides.
  Also: save lesson parts / highlights to Notes, resume a deck at its last slide, focus mode, settings.
  The button under the slide ladder (`#hs-target`) clears the board (slides + chat) — the deck stays in Uploads.
- **No slides open:** chat (typed and Transcription) still works. `/api/chat_stream` →
  `classroom.free_chat_stream` answers from general knowledge, and every reply ends with a rotating reminder
  (`upload_nudge`) to upload material or reopen a recent deck. The board shows Upload / Open a past upload buttons
  under each such answer; the hint bar, chat placeholder and idle board ask for slides with the same
  request and answers "next slide" with it. The student asked for this (2026-10-17): "MrSOLIS should continually
  tell them to upload their material and start learning".
- `static/mrsolis-pages.js` — the sidebar pages, rendered into `#view-page`: Uploads (library), Subjects,
  Notes (crib sheet + saved + own notes, Markdown export), Quizzes, History, Settings, Tools (solver,
  formula sheet, study timer).
- `static/mrsolis-calc.js` — Tools → Calculator: a real scientific calculator (own recursive-descent parser, no
  model, no eval): DEG/RAD, 2nd for inverses, EXP, Ans, nCr/nPr, live preview, history tape. `calcEval()` is pure
  and can be tested with node (`require` the file). One shared calculator (CALC state) mounted with `mountCalc(root)`
  in Tools and in `#board-calc` — typing **/calculator** (or /calc) in the chat box
  puts it on the board as a draggable dark panel. "/" commands live in `COMMANDS` in mrsolis-wire.js (menu: #cmd-menu).
  **/find <name>** (alias /open) searches the student's files by name (`backend/finder.py`: a background list of
  PDF/PPT/Word/text files in Desktop, Downloads, Documents, OneDrive, the rest of home, other drives/USB; skips app
  data, code and media folders; the top of Desktop/Downloads/Documents is re-checked per search). Live results show
  above the chat box (↑/↓, Enter, click); opening goes through `/api/files/open` → the same `_ingest` as Upload.
  Only paths a search returned can be opened (`finder.allowed`). Same names in different folders are normal.
  Never rebuild the keys while in use (`refreshKeys` relabels in place) — a key replaced mid-press loses its click.
- `static/mrsolis-voice.js` — voice. **Transcription** (mic button) types what you say into the chat box;
  **Read aloud** (under every lesson/answer, `readAloud`) speaks it through a small queue (`enqueue`/`playNext`,
  a short first sentence alone so speech starts in ~0.5 s). The file also holds `Mic` and `VOICE`, which
  Interactive mode uses. **Live** (the wave button: a spoken chat that was always listening) was **removed on
  2026-11-11** — the user: "REMOVE THE LIVE MODE … INTERACTIVE MODE IS EVEN BETTER AND DOES MORE". Don't bring
  it back. Backend `backend/voice.py` (sherpa-onnx): NVIDIA Parakeet TDT 110M hears, Silero VAD finds turns,
  Supertonic 2 speaks in male voice M2 (speaker id 6). Audio is posted as 16 kHz float32 chunks to
  `/api/voice/listen/{id}` (no WebSockets needed; `?final=1` on the last post finishes the sentence in progress
  when the mic is stopped). `voice.speakable` reads maths: units after numbers (12 V → 12 volts, A, kWh, MJ…),
  "Q / t" as "Q over t", Greek, powers.
  Models in `models/voice/` (`scripts/fetch_models.py`); credit Parakeet (CC BY 4.0) wherever the app lists them.
  Picked 2026-10-17 by testing on the student's own Ghanaian-accented voice. Rejected: Moonshine Base (garbled the
  student's sentences, nothing past ~9 s), Canary 180M (as accurate, 5× slower), Kokoro (2.4× slower than real
  time), Pocket TTS (3.3 s to first word, dropped words, non-commercial ONNX), Kitten (5.7 s to first word), Matcha (female).
- Backend: `backend/library.py` keeps everything that outlives a restart in `DATA_DIR/library.json`
  (decks, subjects, notes, quizzes, history events, settings). One deck per file: uploads are fingerprinted
  (sha256), a re-upload reopens the existing deck, and duplicates are merged on startup. Decks reopen after a restart from
  `DATA_DIR/study-cache/slides/` (never `cache/` — on Windows that is Electron's own browser `Cache`).
  The crib sheet comes only from the slides (`questions.py`). **Quizzes (2026-10-20): written and marked by the
  brain** (`backend/quizgen.py`; the user called the rule-built ones "really bad" and asked that the model write the
  questions, check answers against the slides, and never repeat a question). `plan` picks slides least-quizzed first,
  spread over the deck (a slide repeats only in a later round); `write` makes one question per call as strict JSON
  (llama-server json_schema grammar) with 1–3 short key points, nudged to a different style each time, told what was
  already asked (library `asked`, per deck, question + answer; `_alike` rejects near-repeats of either), no calculation
  on a slide without a formula, calculations recomputed from the brain's own arithmetic (`calc`, safe AST eval), a
  units check in code (`_units_agree`, 2026-11-06: the working must give the answer's unit and a value can't be named
  as another quantity; Speedy wrote "40 A … in 3 s" for 40 C and "4 Ω of current"; it judges only the units it can
  read, 28/28 on a test set), and
  every question re-checked against the slide (`_CHECKER`) before use. `mark`: numbers and "I don't know" in code,
  answers repeating the key words in code, otherwise one yes/no brain call per key point (8/8, then 11/12 on test
  answers; asking for a verdict/comment directly gave 2/8–6/8 and praised things the student never wrote); verdict
  correct/partly/wrong and the comment ("you left out: …") are built in code. main.py writes questions in the
  background `_QUIZ_AHEAD`=2 ahead of the student (`/api/quiz/{id}/question/{i}` waits), and marking pre-empts the
  writer (cancel, mark, rewrite) — marking waited 25 s behind it. On the i5: first question ~17–37 s, marking 0–8 s.
  Without a brain, `questions.py` rules are still used. **How to use**: `PAGES.help` (sidebar + a link on the empty board).
- **The brain (2026-10-19): a model that sees.** `backend/brain.py` replaces Qwen2.5-1.5B for chat/teaching. The
  student picks a card (`CATALOG`), named by the user **Smarts** = Qwen3.5-2B (recommended) and **Speedy** =
  Qwen3.5-0.8B. **Middler** (Qwen3-VL-2B) was dropped on 2026-10-29 — the user: "we'll find another model later for
  Middler"; a saved pick of it falls back to an installed brain. **The real model names must never appear in the UI** (user's rule,
  2026-10-20): `status()` drops `model_name`, download errors never quote URLs, Settings shows only the brain's name —
  all Apache 2.0, GGUF Q4_K_M + mmproj, downloaded once (resumable `.part`, Range) into `DATA_DIR/brains/<id>/`.
  **Speedy is our fine-tune** (2026-10-22, `Downloads\lunar\finetune\train_speedy.py`, 2,600 Codex-written examples
  built with the app's exact prompts): `model` = `MrSOLIS-Speedy-v1-Q4_K_M.gguf` from `model_url` (the separate public
  repo `mrsolis-brains`, release `speedy-v1`; never a release in this repo, whose releases trigger the installer build).
  Its mmproj still comes from unsloth's repo. `status()` also drops `model_url`. A finished download deletes other
  `.gguf` files in that brain's folder (an older version). Held-out results: quiz checks 42/50 vs 33, broken quiz JSON
  6 → 0, lessons over the limit 7 → 0, maths unchanged (6/11 vs 7/11).
  Gemma was left out on the user's word. Card figures are **estimates** and the UI says so; once a brain runs, its
  card adds "Measured on this computer" (tokens/s × 0.75 → words/s). It runs in the official **llama.cpp
  `llama-server`** (CPU build b11721, `runtime/llama.cpp/`, ggml picks the CPU's DLL) as a sidecar on 127.0.0.1:
  `-ngl 0 --reasoning off --jinja --image-max-tokens 768`, threads = cores/2, tied to the backend by a Job Object
  (dies with it) and opted out of EcoQoS. Plus the **CUSTOM-Kx memory flags** (`KX_FLAGS`, 2026-10-24):
  - `--cache-ram 256`: the engine's RAM prompt cache defaults to 8 GB, so Speedy grew 1.3 → 3.2 GB over 20 slides and
    kept climbing. Capped, it levels off at about 1.2 GB with the same speed.
  - `--no-repack`: repacking keeps a private copy of the weights while their file pages stay mapped (209 MB on Speedy,
    1.8 GB on a 4B brain), and without it Speedy is no slower.
  - `--lazy-mode on`: Gemma 4's per-layer word tables stay on disk.

  Measurements and plan: `../../reports/CUSTOM-Kx initial report.md`; tools: `../../finetune/kx/`.
  **CUSTOM-Kx picture reader:**
  - On a brain's first start, `brain.kx_upgrade` uses `backend/kx.py` to write `mmproj-Kx-Q8_0.gguf` next to the
    download: the encoder linears and Qwen's merger become Q8_0, and the result is marked `mrsolis.kx`. `_files`
    prefers that file; `LUNAR_KX=0` turns it off.
  - Smarts: 637 → 345 MB, RAM −292 MB, slide reading identical (recall 0.965 on every slide, the same facts).
    Conversion takes 13 s, once. Speedy: 196 → 108 MB, RAM −86 MB after load and −95 MB looking at a slide, reading identical (recall 0.96 on every slide, the same facts, 7/8 transcripts word for word).
  - The original is kept unless `LUNAR_KX_TIDY=1`. On 2026-10-24 the default deleted the user's own 16-bit readers
    when their app picked up the code; both were restored from Hugging Face on 2026-10-25 (SHA-256 checked).
  - `_download` skips the 16-bit reader when the Kx one exists.

  **Picture size:** `_image_data_url` sends a landscape slide at 832 px (about 360 picture tokens) and a portrait page
  at 1024 px. Smarts read slides identically and began answering in 8.8 s instead of 19.9 s; on dense notes, fewer
  tokens once misread a number. OpenAI chat API; pictures are `image_url` data-URL parts. `local_llm.chat*`
  route to the brain when one is installed (Ollama/llama-cpp stay as fallback, text-only); embeddings are unchanged.
  `info={"finish"}` from the stream stops `_stream_complete` continuing a reply the model ended itself (it used to
  re-ask after "…😊" and the model started over). Lessons send the slide's picture (`_slide_picture`, 1024 px JPEG,
  cached per session) only when `file_processor.slide_has_figure` finds a picture/chart/diagram or the text is short
  — looking costs ~15–20 s on a laptop CPU; Settings → "Look at the slides" turns it off. Slide chat sends it for
  visual questions (`_VISUAL_ASK`); the student can attach a photo (`#chat-pic`, paste, drop on the chat box;
  shrunk to 1280 px in the browser). Streams send `{"looking": true}` → "MrSOLIS is looking at the slide…".
  Frontend: `static/mrsolis-brain.js` (cards in Settings → Brain, the chooser shown at start-up when no brain is
  downloaded — i.e. after the v1 update — and the picture chip). Endpoints: `GET /api/brain`, `POST
  /api/brain/download|cancel|select`, `DELETE /api/brain/{id}`. Measured on the i5-13420H (CPU only): Qwen3.5-2B loads
  in ~10–18 s, ~2.9 GB RAM, text lesson first word 3.3 s at ~7–9 words/s, a diagram slide 20 s to first word.
  **Not done yet:** packaging — bundle `runtime/llama.cpp` as an extraResource, don't bundle the old chat GGUF, and
  give prod embeddings a path (llama-cpp-python or a second `llama-server --embeddings`).
- **Prompts (2026-10-20, `backend/classroom.py`):** every prompt is `_CORE` (~133 tokens: who MrSOLIS is,
  professional tutor manner, accuracy, maths as plain text) + a 1–3 sentence task, via `_system` — 153–196 tokens
  per task (the old lesson prompt alone was 239). Tested on 13 tutor situations with Qwen3.5-2B (scratch
  prompt_eval.py). It parrots rules and quoted lines back, so keep few rules and no scripts; hard numbers next to
  the question ("in under 80 words") work where "a few sentences" gave 371 words. What the brain fumbles is decided
  in code: `fixed_answer` (`_WHO` "which model are you?" / `_META` "ignore your instructions" → fixed replies, also
  in main.py so no slide picture is made for them), `_heading_note` (title slide 1, outline, "Thank you" → instant
  fixed note), `_LOST` ("I'm lost" → summary + "which part?" put in the user turn), `_scrub` (the real model's name
  is replaced in every stream). Lessons close with "a one-sentence summary" — "End with **Key idea:**" made it open
  with the label on picture slides.
- **2026-10-21 fixes (user's list):**
  - Quiz never asks about slide admin: `_quiz_text` drops lines repeated on 30%+ of the deck's slides (footers such as "P. A. KWABI (Ph.D.) SET THEORY 110/119"), admin lines (`_ADMIN_LINE`: university, lecturer, Dr., email…) and page numbers before writing. `quizgen._ADMIN_Q` rejects admin questions, and the checker rejects them too. The user saw "What is the name of the institution?".
  - "Look at slides" is an eye switch under the slide, beside Interactive mode (`#look-chip` in `#class-under`; mrsolis-brain.js `LOOK`), no longer in Settings.
  - Lesson length is held three ways for every brain (Smarts overran its cap on Short):
    - the word limit sits in the user turn ("Teach this slide in under 120/220/380 words");
    - the lesson stops at the first full stop past limit × 1.3;
    - the token cap sits just above that, with at most one 60-token top-up.
    - Smarts measured 119–434 words, all ending cleanly.
  - Transitions: after each lesson the stream sends `{"next": …}` (`main._transition` → `classroom.lesson_transition`). The frontend appends it to the lesson, so it is read aloud but not saved to Notes.
    - It names the next slide only if `_heading_title` says its title is a real heading (PDF first lines are often sentences).
    - The same section gets "let's continue"; the last real slide (only blank or "Thank you" after it) gets a professional close.
  - `mathify` now renders set/logic LaTeX (∈ ∉ ⊆ ∪ ∩ ∅ ↦ ℤ, and `\{…\}` as real braces). Quiz text goes through it too (`qtext`).
`backend/run.py` opts the backend out of Windows power throttling (EcoQoS): Windows 11 runs windowless processes on
the efficiency cores when on battery, which made speech ~7× slower (4.5 s vs 0.6 s a sentence) and slows the tutor
model too. It also exits by itself when the desktop app (`LUNAR_PARENT_PID`) is gone, so no backend is left running.
The desktop window is frameless (`desktop/preload.js` exposes minimize/maximize/close) and opens maximized.
`static/script.js`/`style.css` are the old Lunar UI and are no longer loaded.

## Videos (`backend/video.py`, `static/mrsolis-video.js`) — 2026-10-24
The user wants MrSOLIS to "watch" videos. The Qwen brains see but can't hear, so a video is shown to the brain as
**frames plus a transcript**. This works for Speedy and Smarts (and worked for Middler), and would for Gemma.
- **Attaching:** the picture button takes videos too. A video or recording dropped *anywhere* on the window goes to
  the chat box, not to upload. `desktop/preload.js` exposes `mrsolisFiles.pathFor` (webUtils) so the backend reads the
  file in place. Without a path it's uploaded to `uploads/videos/`. One attachment at a time. Unlike a picture, the
  video **stays attached for follow-up questions** until removed.
- **Preparing, once:** `POST /api/video/prepare {path}` (or `/api/video/upload`). `video.prepare` runs a thread,
  one video at a time, and caches to `study-cache/videos/<id>/` keyed by path, size, mtime and VERSION.
  - It listens with ffmpeg → 16 kHz → Parakeet (`voice.recognize`), in pieces of under 20 s cut at quiet points
    (`voice.quiet_cut`), each with its start time; silence is skipped.
  - It watches with one ffmpeg fast-seek per frame: about one every 15 s, up to 48, or at least 6 for short clips.
    A frame is kept only if more than 1% of the pixels of a 128×72 thumbnail changed by more than 40 levels; slides
    that differ only in their words look alike when shrunk, which is why it counts pixels rather than averaging.
    It keeps up to 24.
  - The page polls `GET /api/video/{id}`. When the video is ready it calls `POST /api/video/{id}/warm`, so the brain
    reads the video while the student types.
- **Asking:** the chat endpoints take `video: id` and route to `_video_answer` → `classroom.video_chat_stream`
  (temperature 0.2; at 0.5 Speedy once turned "fourteen forty" into 1400 rpm).
  - **Message layout:** `[system, user: video (what is said + 6 frames, each after its time), assistant: fixed "I have
    watched…", user: question]`. The video sits in its own message because the engine saves its place only at the start of the
    last user message and never inside pictures, and the hybrid Qwen3.5 brains can only resume from such a saved
    place.
  - **Measured on the i5-13420H** (82 s narrated test lecture, `finetune/kx/make_test_lecture.py`):

    | Brain | First question | Follow-ups |
    |---|---|---|
    | Speedy | 9 s | 0.3–0.9 s to the first word |
    | Smarts | 23 s | 1.3–1.6 s |

    With video and question in one message, every follow-up re-read about 1,170 of 1,390 tokens.
  - A talk of up to about 2,600 tokens (≈ 30 min) is shown whole. Longer ones get an even spread (the cached part)
    plus pieces sharing words with the question (`video.matching`).
- **Results:** Speedy 5/5 at temperature 0.2 on the test lecture's questions (facts only spoken, facts on slides,
  advice); `scratchpad video_feature_test.py`. It was tested in the real app over CDP with an isolated user-data dir:
  pick → watched → answers with a video tag.
- **ffmpeg / ffprobe (bundled 2026-10-25, the user said yes):** `runtime/ffmpeg/` holds the LGPL v3 "win64-lgpl-shared" FFmpeg n9.0.2 from BtbN FFmpeg-Builds (ffmpeg.exe, ffprobe.exe and 7 DLLs, 150 MB; no ffplay, headers or docs), with LICENSE.txt (LGPL v3), COPYING.GPLv3.txt and README-MrSOLIS.txt (source, pinned dated release, SHA-256). Built without GPL or non-free parts (`ffmpeg -buildconf`). `video.tools()` looks at `LUNAR_FFMPEG_DIR`, then `runtime/ffmpeg/`, then the PATH; `desktop/package.json` extraResources ships it to `resources/runtime/ffmpeg`. Same results and speed as the dev laptop's own ffmpeg (82 s lecture prepared in 7.9 s). Its licences are on the app's Licences & credits page.
- Parakeet runs about 15× real time here, so a 1-hour lecture takes about 4–7 min to prepare (progress is shown on
  the chip).

## Interactive mode — the class at the blackboard (2026-11-10, reworked 2026-11-11)
The user: "MAKE MrSOLIS INTERACTIVE, JUST LIKE A TEACHER TEACHING IN CLASS": a full-screen blackboard "like the
Organic Chem Tutor's", written on while it is explained aloud. Started with the **Interactive mode** button over the
board (`#ic-start`, shown once slides are open) or `/class`. After testing it (11-11) the user asked for: a
**raise-hand** button instead of always listening (it heard its own voice: "an echo", and the voice dipped), every
slide **finished** before the next with "we're moving on", no Next-slide button, more on the board and speech about
exactly what is written, no slide numbers or fake "Answer:" lines, no SHOUTED headings.
- `static/mrsolis-board.js` — class `Blackboard`: the board itself, no backend. Every letter is drawn stroke by
  stroke with a pen dot (`write(text, {duration, color, indent, scale, kind})` resolves when the pen lifts;
  `pause/resume/finish/erase/space`, `.lines`, `.rate`; `erase()` also forgets `.lines`). It lays out what a teacher
  writes: `# heading` (underlined), `- bullet`, `**key term**` in colour, "Answer: …" boxed, and maths: x^2, v_0,
  √(…), and fractions stacked from plain text ("V/R", "(a+b)/c", "G m1 m2 / r^2"; units like "m/s" after a number
  and words like "and/or" stay on the line). `boardTidy` turns LaTeX leftovers and keyboard stand-ins into signs.
  Drawn in a 1600-wide space the screen scales (the class uses em 52). Test bench outside the repo:
  `Downloads\lunar\class-board-test` (preview "class-board-test"; `capture('name')` saves a full-size PNG; a hidden
  pane draws no frames: call `board.frame()`), plus `run_backend.py` (preview "mrsolis-class-test": the backend on
  the TEST profile, port 8011) and `try_class.py` (prints a slide's class, or `--ask "question"`).
- `static/board-font.json` — the handwriting, built by `scripts/build_board_font.py` from the npm package
  hersheytext 2.0.0 (kept in the test bench folder): EMS Tech (SIL OFL, a single-line Architects Daughter) plus the
  Hershey Greek letters (their keys follow the Symbol font: q is theta, w is omega) plus maths signs drawn in the
  script. 1 and I are drawn again (both were a bare stroke), and × ÷ ± (they sat outside their own space). Heights
  are measured from the font (cap, xh, asc, desc in the JSON), not its metadata, which is wrong. Credited in
  Licences & credits (`licences/board-handwriting-ofl.txt`).
- `backend/boardclass.py` — **what is written is normal mode's own lesson** (the user, 11-11: "MrSOLIS WRITES SOME
  REAL BS ON THE BOARD … MAKE IT WRITE AS THOUGH IT WAS ON THE BOARD (THE NORMAL MODE)"). An earlier design (11-11
  morning) made the brain fill BOARD:/SAY: lines point by point under a GBNF grammar: a 2B brain writes much worse
  under such rules than in its own prose ("A = 3 A", fake "Answer:" lines). Now `lesson_steps` streams
  `classroom.teach_slide_stream` (the same prompt, length setting and `exact` hand-off as the lesson under the
  slide; `prior=` carries on after the student cut in) and `sentences()` cuts it into sentences as they arrive
  (`_cut`: "1." of a numbered step, "e.g." are not sentence ends; a blank line marks a new paragraph, `gap`). Each
  sentence is one step: written on the board while exactly that sentence is said. Before that, `unlatex` turns
  LaTeX into signs ("\times" → ×: the voice skipped LaTeX words) and `check_sums` recomputes every "sum = result"
  with quizgen's safe calculator and corrects a wrong result. A bold line repeating the heading is dropped. Answers
  to the student are normal chat answers (`classroom.chat_stream`) cut the same way, written in orange.
- **Maths goes through CUSTOM-Mx** (the user: "ROUTE MATH THROUGH CUSTOM-Mx"; `main._class_maths`): the question in
  symbols first (`spoken_maths`: "twelve divided by four" → 12 / 4, number words → digits); a unit conversion
  ("how many joules is 2 kWh" → `convert 2 kWh to joules`, `conversion`) or a CUSTOM-Mx command runs exactly; maths
  with nothing to misread goes to `mathengine.solve`; a word problem (a cue word or units) is set up by
  `_draft_exact` and shown as an **offer** (`offer_step`) — never worked unchecked, as in normal mode (its reading of
  words is right only about half the time). The slide's own questions (`mathengine.slide_questions`) are offered
  after its lesson. `/api/class/run` works a checked setup and returns `working_steps` (CUSTOM-Mx's lines, the
  answer boxed; a "Result:" equal to the answer is dropped). Spoken maths reads well because `voice.speakable` now
  says units after numbers (12 V → 12 volts, A, kWh, MJ, g, h, min…) and "Q / t" as "Q over t".
- The class's slide steps: title/outline slides in code (`fixed_steps`), a closing "Thank you" slide passed over,
  footers left out (`repeated_lines`), SHOUTED headings calmed (`calm`, acronyms kept via `caps_kept`), and a last
  step `{"end": true}` that says where the class goes next (`transition`; `main._class_next` finds the next title as
  normal lessons' `_transition` does). Routes: `/api/class/teach_stream` (`done`: steps already written — their
  `md` rebuilds the lesson so far, `fin` marks it complete, offers already made aren't repeated),
  `/api/class/ask_stream`, `/api/class/run`.
- `static/mrsolis-class.js` — the class (`IC`, `startClass`/`endClass`). One loop (`icDirect`) teaches step after
  step: the voice (`/api/voice/speak`, a sentence at a time, cached) and the pen start together, and the writing is
  timed to the saying. A new slide wipes the board first. The next slide is prepared while the current one is
  taught (`icLoad`/`icAhead`, one slide ahead at most). **The microphone is on only while the hand is up**
  (`icRaiseHand`, ✋ button or H): the voice and pen freeze first, then the voice module's `Mic` opens; the student's words
  show as a caption; 1.5 s after they stop (or ✋ Done) the mic closes and the words go to `icStudent`: a command
  ("continue", "say that again", "next slide", "go back", "slower"/"faster", "end the class") or a question
  (`icAnswer`: written in purple so a mishearing shows, answered in orange — CUSTOM-Mx's working in white —, then "Back to the lesson" and the
  interrupted step is said again without being written again). No speech for 10 s lowers the hand. Typing a
  question (the box) pauses the class too. An offer (`icOffer`) shows ▶ Run it / Skip (R / S, or "yes" / "skip" with
  the hand up) and the class waits for the student; Run writes and says CUSTOM-Mx's working line by line. Never two voices at once (`icPlay` pauses the old one). The whole
  page goes full screen (not just the board), so toasts still show.
- Not built yet: the slide's picture on the board for diagram slides, MrSOLIS asking the student questions,
  saving a class to Notes/History, editing a CUSTOM-Mx setup in class (Skip, then ask it again).

## Online brain — the student's own AI account (2026-11-11)
The user: "make MrSOLIS offline-first instead of fully offline … bring their own LLM API key … SUPPORT DEEPSEEK,
OpenAI COMPATIBLE POINTS, ANTHROPIC, GEMINI, NVIDIA FOR NOW". Everything stays in MrSOLIS's window.
- `backend/cloud.py`: providers DeepSeek, OpenAI, Anthropic (Claude), Google Gemini (its OpenAI-compatible endpoint),
  NVIDIA (integrate.api.nvidia.com), Other (any OpenAI-compatible server; plain http only for localhost/LAN).
  OpenAI-style chat completions over httpx; Claude through the official `anthropic` SDK (AsyncAnthropic; never an
  OpenAI shim): system prompts → `system`, image_url data URLs → base64 image blocks, no temperature (400 on the
  2026-10-21 API version), `output_config.effort: "low"`, top-level `cache_control`, `output_config.format` for
  schemas (objects closed, size limits moved into descriptions), and for Opus 5.5 / Sonnet 5.5 / Fable the
  server-side refusal fallback (beta `server-side-fallback-2026-07-01`, `fallbacks: "default"`).
- Servers differ: `_QUIRKS` learns per (server, model) what was refused — max_tokens → max_completion_tokens,
  temperature, reasoning_effort, json_schema → json_object + a JSON hint, too-large caps — and retries once.
  Reply caps get +3072 for reasoning models (callers stop at their own length). `<think>` at the start is dropped.
- **Offline-first:** `brain.chat` / `brain.chat_stream` try `cloud` when `cloud.on()`; a `CloudError(local_ok=True)`
  (no internet, 402/429/5xx, out of credit) before any words falls back to the brain on this computer (words only if
  it can't see). A refused key or unknown model is shown, not hidden. `brain.active()` = online or local;
  `brain.sees()` follows the online model; `warm()` skips loading the local brain while online, and switching online
  on stops it (memory back); the video warm-up is skipped online (it would be a paid request).
- **The key:** `DATA_DIR/online-brain.json`, sealed with Windows DPAPI (`dpapi:`; other systems `b64:`, the file
  is private); the page only ever gets `…last4`. API: GET/POST `/api/brain/online`, POST `/api/brain/online/models`
  (filters embeddings/voices/images; `suggest`: Claude → claude-opus-5-5 per Anthropic's guidance), POST
  `/api/brain/online/test`. `/api/health` → `online`, `chat_model` = short name ("Claude"; Other = "your server"),
  `model`, `fallback`, `last_error`.
- UI: Settings → Brain → "Online brain" card (mrsolis-brain.js `ONLINE`, also in the first-start chooser); the local
  card says "Backup — used without internet" while online; the chip says "Online · Claude" (one line, ellipsis); a
  toast once when the local brain answered instead. Real provider model names are shown here (the student picks
  them); the never-name-the-model rule is about MrSOLIS's own brains.
- Terms 6.1, 6.4, 6.6 and 5.1 cover it (make_terms.py run); credits list the SDK and httpx2. The release needs
  `anthropic` installed (requirements.txt) and the spec collects `anthropic`, `httpx2`, `httpcore2`.
- **Think** (the button by the chat box, 2026-11-11): the student's own questions (chat, free chat, Explain/Solve)
  carry `x-mrsolis-think: 1`; main.py's `_ThinkFlag` (plain ASGI, so it holds while the answer streams) sets
  `cloud.THINK`; the online model then thinks more: effort "medium" (not "low") for OpenAI/Gemini/Claude/ChatGPT plan,
  deepseek-chat → deepseek-reasoner, `chat_template_kwargs.enable_thinking` for NVIDIA/Other, bigger reply caps.
  Lessons, quizzes and Interactive mode never think. **Not on this computer's brain:** measured on Smarts
  (think_probe.py) one circuit question took 230 s instead of 13 s and came out wrong (2 A, not 3 A); the server
  stays `--reasoning off`, and the button is dimmed there with that reason. Remembered in localStorage
  (`mrsolis.think`). Tests: think_app_test.py 4/4 (a fresh backend: a bug where the `<think>` filter reused the name
  `think` made retries think — fixed, the filter is `nothink`).
- **Subscriptions (researched 2026-11-11):** Anthropic forbids Claude Free/Pro/Max OAuth in third-party apps
  (enforced Jan–Apr 2026; API keys only) — never build it. OpenAI's "Sign in with ChatGPT" plan usage (DevDay
  2026-09-29) is self-serve only for open-source/locally hosted apps; a **paid** app must be accepted first. The user
  sent OpenAI's interest form on 2026-11-11 ("Sign in and ChatGPT plan use for AI requests").
- **Sign in with ChatGPT is BUILT but OFF** (`backend/siwc.py`, provider "chatgpt" in cloud.py, hidden unless
  `siwc.enabled()`: `ENABLED = False`; dev runs only: `MRSOLIS_CHATGPT_PLAN=1`, ignored by the frozen app).
  - OAuth (OpenAI's open-source flow): PKCE S256 in the student's browser (`window.open` → main.js →
    shell.openExternal), a one-time listener on `http://127.0.0.1:<free port>/auth/callback`; first sign-in
    `client_id=dynamic_agent_client` + `agent_name_hint=MrSOLIS`, the issued `oaiapp_…` id comes back in the callback
    and is kept; `ext_agent_host_id` = `urn:uuid:` per install; scopes `openid profile email offline_access
    resource.invoke chatgpt.tokens.use.direct`; `resource` is ALWAYS `https://api.openai.com/v1` (`RESOURCE`, apart
    from `API`). ID token: iss/aud/exp/nonce/sub + RS256 against OpenAI's JWKS (pure Python). Plan use only if the
    token response grants `chatgpt.tokens.use.direct` (else "Turn on plan use" = `prompt=consent`). Re-sign-in:
    saved client id + `id_token_hint` + `login_hint`. Tokens sealed with DPAPI in online-brain.json.
  - Refresh: grant `refresh_token` + client id + `resource`; the refresh token rotates (saved at once; one refresh at a
    time); network trouble keeps credentials; terminal codes (invalid_grant, refresh_token_reused…) clear the tokens
    and ask to sign in again. Sign out revokes at the discovery document's `revocation_endpoint`.
  - Inference: `POST /v1/responses` with `store:false`, `stream:true`, system prompts in `instructions` (system items
    are refused), pictures as `input_image`, `reasoning.effort:"low"` and `text.format` json_schema dropped if refused
    (`subscription_sharing_unsupported_capability` + `error.param`); never temperature / max_output_tokens. Success
    only on `response.completed`. Models: `GET /v1/models` → `models[]` with `visibility == "list"` (`slug`,
    `display_name`). Usage limit (429) / unavailable (503) may fall back to this computer's brain.
  - OpenAI's UI wording is used: "Continue with ChatGPT", "Use your ChatGPT plan" + its text, the one-time notice
    "You're using your ChatGPT plan … Got it", "Using ChatGPT plan · Manage usage" by the chat box (`#plan-badge`) and
    on the card, "Manage usage" first at the limit (https://chatgpt.com/settings/usage).
  - Tests: `siwc_test.py` 29/29 (mock OpenAI: sign-in, RS256, rotation, terminal refresh, re-sign-in, revoke, declined,
    no plan scope, forged token, gate), `cg-ui-test.mjs` 13/13 (the whole flow through the screen; `mock-openai` +
    `mrsolis-chatgpt-test` preview configs, run_backend_cg.py). Not tried against the real OpenAI (needs acceptance).
  - **To turn it on when OpenAI accepts MrSOLIS:** set `siwc.ENABLED = True` (and `PARTNER_CLIENT_ID` if OpenAI issues
    one — then check their partner docs for a different flow); put OpenAI's official "Continue with ChatGPT" button
    asset on `.cg-btn` (the docs require approved branding; ours is text-only); add "ChatGPT plans via Continue with
    ChatGPT" to TERMS-OF-USE.md 6.6 (it now says subscriptions can't be used) + make_terms.py, and to the website's
    terms/privacy; test once with a real ChatGPT account; then release.
- Tests (Downloads\lunar\class-board-test): `online_brain_test.py` (32 mock checks + 4 on a real llama-server),
  `online_app_test.py` (in the running app: online answer, then the stand-in server stopped → Smarts answered,
  health showed the fallback), `settings-online-flow.js` (the card driven like a student). No real company keys
  were available: the user tests those.

## CUSTOM-Mx (`backend/mathengine/`) — the maths engine
Code does every calculation; a brain only explains, or labels a question's numbers when the rules can't read it.
- **Word problems are never answered unreviewed.** On 2,680 OpenStax textbook problems with answer keys the rules'
  own reading was right only ~half the times they answered, and a trained checker still let ~1 in 8 wrong answers
  through (retired; its training scripts stay in `finetune/mx_reader/`). So `mathengine.solve` answers only maths with
  no words to misread (equations, calculus, statistics); a word problem — highlight → Solve, the Solver's Solve, a
  question printed on a slide — becomes a CUSTOM-Mx draft card (Run / Edit) the student checks first
  (`_draft_exact` + `_offer_events` in main.py, `{"exact": [...]}` stream events, `exactCardHTML` in the frontend).
  In lessons the brain teaches the method but is told not to calculate the slide question's final numbers.
- **`/CUSTOM-Mx` (`command.py`, chat `/mx`, or "/mx …" in the Solver)**: the Javelin idea — a precise language the
  student writes (`find s given u = 0 m/s, v = 20 m/s, t = 5 s`, `rearrange "…" for t`, `convert …`). It runs exactly
  what is written or refuses with the reason; it never guesses which role, formula or reading was meant, and never
  ignores a given value. Everyday phrasing is rewritten by fixed rules and shown as "Understood as". No brain.
  Tests: `python -m backend.mathengine.command_test` (all must pass) and `python -m backend.mathengine.selftest`.
- **"Make it exact" (Σ in the chat bar, button in the Solver → `/api/mx/draft` → `command.draft`)**: the student's
  own question becomes a /mx command they review before sending. Code copies every number; the rules' reading (or,
  if they can't read it, the brain picking labels from `reader.request` lists) only names them. A draft must give the
  reading's own answer when run, else it adds `using "…"`; names come from `name_for`, which must read back exactly.

## CUSTOM-SQE and the SQE window (MrSOLIS 2-AL) — 2026-10-29
The student brings one maths question; MrSOLIS 2-AL makes practice versions of it. Plan and results:
`CUSTOM-SQE-TODO.md`.
- **Window**:
  - `frontend/sqe.html` + `static/mrsolis-sqe.js/.css`, opened by `openSqe()` in `desktop/main.js`;
  - one frameless window, the question passed in over IPC `sqe:prefill`, only the main window may send `sqe:open`,
    and it closes with MrSOLIS;
  - entry points: Quizzes → **SQE**, "Practise more like this" (Tools → Solver, the board's Solve answers);
  - History records `practice` events (`/api/sqe/done`).
  - **Highly recommended for maths quizzes** (the user, 2026-10-29: the brains "are not great at that and will never
    be"): How to use's SQE card carries a "Highly recommended" tag (GUIDE's optional 4th field), "Test yourself" sends
    maths quizzes to SQE, and the Quizzes panel says it too.
  - **Calculator** (the user, 2026-10-29): the practice bar's **Calculator** button docks MrSOLIS 3's own calculator
    (`mrsolis-calc.js`, loaded by sqe.html) on the right; the stage makes room, so the question and answer box stay
    uncovered. `mountCalc(root, true, { tape, drag: false, onClose, onCopy, copyTitle })`: pressing "= answer" puts it
    in the typed-answer box (copied to the clipboard in choose-from-four). The module stands alone there (`calcEsc` /
    `calcIcon`, `#board-calc` may be absent); Tools and the board calculator are unchanged.
- **Engine (`backend/sqe/`)**:
  - `api.generate` → `engine.make` (families in `fam_*.py`, in a fixed order).
  - MrSOLIS 2-AL's own `pipeline` is only a fallback.
  - `text.py`: every number in the question is a *slot*. A version is the student's exact words with new numbers;
    the symbolic template (`(S0)`…) is parsed once with sympy.
  - `core.keep_roots` / `back_solve` choose the answer first, then the numbers that give it: whole roots, 0/0 kept
    0/0, factorisable stays factorisable.
  - Every version is re-read from its own text and must give the same answer.
  - `text.to_expr` lets only maths characters and names reach sympy's `parse_expr`, which runs eval.
  - Response extras: `original` (the student's own question answered) and `understood` (how a word problem was read,
    shown as "Read as").
- **Measure after changes**:
  - `python -m backend.sqe.selftest` (all must pass);
  - `python scripts/sqe_check.py --bank a` and `--bank b`, coverage (bank B is held out: never tune to its
    single questions);
  - `python scripts/sqe_verify.py --bank a|b`, which re-checks answers independently and must be 0 wrong.
- **Gotchas**:
  - Shell heredocs halve backslashes (`\b` becomes a backspace inside a regex), so edit these files with the editor.
  - A single letter next to +/- is a variable ("3a + 2"), never the English "a".
  - `sp.nsimplify` on exact π/surd values is very slow, so use `text.exact`.

## Graphify knowledge graph — consult this BEFORE searching

This repo has a prebuilt Graphify knowledge graph in `graphify-out/`. **Use it before grepping or reading
whole files** — it is far cheaper on tokens and already maps every function, class, route, and concept.

**Order of operations for any "where / how / what calls X" question:**
1. **Read `graphify-out/GRAPH_REPORT.md` first** — god nodes, communities (subsystems), and key flows.
2. Run a graph query instead of a repo-wide grep:
   - `graphify query "<question>"` — BFS context for "how does X work / what connects to Y".
   - `graphify explain "<NodeLabel>"` — what a function/class is + its neighbors.
   - `graphify path "<A>" "<B>"` — shortest path between two concepts.
   - `graphify affected "<X>"` — what breaks if you change X (reverse traversal).
   - (Graph file: `graphify-out/graph.json`; interactive view: `graphify-out/graph.html`.)
3. Only fall back to `Grep`/`Glob`/reading entire files when the graph genuinely can't answer (e.g. exact
   string/line lookups, or files outside the graph such as `uploads/` runtime data).

**Prefer graph queries over reading entire files.** A targeted `graphify query` or `explain` usually
answers a navigation question without opening `script.js` (≈2,800 lines) or `classroom.py` end-to-end.

### Subsystem map (Graphify communities)
- **Backend** — `main.py` FastAPI routes (`FastAPI Endpoints & Routes`); `classroom.py` teaching + grounded
  quiz logic (`Classroom Teaching & Quiz Logic`); `local_llm.py` Ollama client (`Local LLM Client`);
  `voice.py` STT/TTS (`Voice Engine`); `file_processor.py` slide/OCR extraction (`Slide & Document
  Extraction`); `setup_models.py` (`Model Setup & Download`).
- **Frontend** — `script.js` controllers: the `cr*` classroom controller (`Classroom Frontend Controller`),
  lecture/TTS delivery (`Lecture Delivery & TTS`), upload/init (`Upload & Classroom Init`), mic/VAD
  (`Voice Mode Mic Control`, `Audio VAD & Barge-in`); `nebula.js` animated background.
- Communities tagged **(legacy)** in GRAPH_REPORT.md (`Ask Lunar Chat Modal`, `Quiz Creation & Timer`,
  `Quiz Scoring & Feedback`, `Topics & Solutions UI`) are pre-classroom code paths still present in
  `script.js`; the live flow is the classroom, not these.

### Rebuilding the graph after code changes
- Code edits: `graphify update .` (deterministic AST re-extract, no LLM, fast).
- Bigger/structural changes or new docs: re-run the `/graphify` skill (full rebuild).
- The graph intentionally **excludes** `uploads/` and `cache/` (user runtime data, not source).

## Don't break things
- **Questions beyond the slide** (the user, 2026-11-11): `classroom.chat_stream` answers a question on the
  subject directly, never saying whether the slide covers it; a question with nothing to do with the deck
  (`on_subject`: its words against the whole deck's, `main._deck_subject`) is asked on its own (shown the
  lesson, Smarts refused it), answered in one or two sentences, and code adds a friendly "Now, let's get back
  to <slide title>." (`back_to_lesson`). `without_disclaimers` cuts "the slide doesn't cover this… from
  general knowledge" clauses from chat, video and no-slides answers (keeping the answer after them).
- **The window must never run old scripts:** `/static/*`, `/app`, `/sqe` are sent `Cache-Control: no-cache`
  (middleware `_always_fresh`; unchanged files come back as 304s), and index.html links its scripts with
  `?v=…`. Without it the window kept old copies for days by the browser's own guess: after Live was removed a
  cached old mrsolis-voice.js failed on the new page. Bump `?v=` when a release changes several scripts.
- Keep the app fully local — never reintroduce cloud LLM/API-key/Deepgram paths.
- Preserve every DOM id/class that `script.js` selects; CSS is restyle-only (additive), no renames.
- **The crib sheet must quote the slides exactly** (`questions.formula_lines` / `definition_pairs`). Before
  2026-10-30 it took only the letter before the last "=", so "1/R = 1/R1 + 1/R2" became "R = 1/R1 + 1/R2" and
  "P = V I = I^2 R = V^2/R" became "R = V^2/R". Run `python -m backend.crib_test` after touching them.

## Releases (3.0.0, 2026-10-30)
- This folder is a git checkout of github.com/aduamankwahkwasi292-wq/lunar (public), branch `main`; it used to be a
  zip copy. Release builds are made on the laptop while GitHub Actions is blocked by the account's billing lock:
  RELEASE.md "Building on this laptop". The installer is Windows-only and no longer carries Lunar 1's built-in
  GGUFs (`models/**/*.gguf`): `local_llm`'s in-process llama.cpp ("Classic", and embeddings for "Find anything" by
  meaning) only runs in dev when llama-cpp-python and the GGUFs are present. Every embedding call already falls back.
- **A release is tested as a student meets it** (2026-11-03): 3.0.0 and 3.0.1 never opened for a new student. The
  desktop shell waited for a ready brain, and a new install has none until the student downloads one inside MrSOLIS;
  and the engine, a windowed program, crashed in uvicorn's log setup when started without standard handles. Neither
  showed in tests started from a terminal with brains copied into the profile. Now: the shell opens MrSOLIS once the
  engine answers at all (brain state is the app's business: status chip, first-start chooser), the installed
  `/api/health` never asks Ollama, `backend/run.py` gives a stream-less engine `<data>/logs/engine.log`, and the shell
  keeps the engine's output there too. Before publishing: `python -m backend.start_test` and
  `scripts/smoke_packaged.py` on the installer (and the Store package) must pass, every stage (RELEASE.md).

## Licences & credits, and the runtime in releases (2026-10-25)
- **Settings → About** names the engines (CUSTOM-Mx, CUSTOM-Kx) and has a **Licences & credits** button. It opens
  `PAGES.licences` (`mrsolis-pages.js`, data in `ENGINES` and `CREDITS`).
  - The page lists every shipped component, with its licence and what it does; the full texts are in
    `frontend/static/licences/` and open inline.
  - Web addresses are plain text, because a link would navigate the app window away.
  - The brains are described, never named (the user's rule).
- **Licence obligations still open (the user's call):**
  - **PDFs no longer use PyMuPDF (AGPL)** — 2026-10-26: `backend/pdf.py` is MrSOLIS's own PDF layer on PDFium (pypdfium2, BSD-3/Apache-2.0): text, words/lines with boxes, pictures/shapes (figure + blank checks, straight lines count as no area), links, page drawing. Not based on PyMuPDF's code (that would stay AGPL). Parity on 98 pages of the training decks (`finetune/kx/pdf_parity.py`): text 99.4%, words 97.9%, figure/blank/links 98/98, drawings identical by eye.
  - **Supertonic's OpenRAIL-M** requires its use restrictions (Attachment A) in MrSOLIS's terms of use.
- **The runtime in releases:** `scripts/fetch_runtime.py` fetches the AI engine (llama.cpp b11721: win-cpu-x64,
  ubuntu-x64, macos-arm64/x64) and FFmpeg n9.0.2 LGPL shared (win64, linux64; none for macOS) into `runtime/`.
  - Downloads are pinned and SHA-256 checked. It was tested on Windows: all 51 engine files and 10 FFmpeg files are
    byte-identical to the app's.
  - `.github/workflows/release.yml` runs it before PyInstaller, cached per OS and architecture.
  - `desktop/package.json` extraResources ships `runtime/llama.cpp` (llama-server and its libraries) and
    `runtime/ffmpeg`.
  - `.gitignore` keeps the binaries out of git but keeps `runtime/ffmpeg/README-MrSOLIS.txt` and `COPYING.GPLv3.txt`.
- **Terms of use** (2026-10-26): the source is `TERMS-OF-USE.md`. The seller is Behemoth Group, at
  jonsonwhocancreate@gmail.com.
  - **The owner's terms:** US$1, paid as GHS 12 (the user, 2026-10-29: "make the price one dollar"; GHS 35 before;
    the server's `PRICE_PESEWAS` / `PRICE_USD_ABOUT` must match sections 2.1 and 7), one computer per licence; ALL
    updates free, brains included (the user, 2026-10-28: "let's make updates free"; brains updates had been US$0.50);
    refunds within 24 hours with a screen recording of the problem and proof of payment; the courts of Ghana. Section 5.3 holds the OpenRAIL-M restrictions.
  - **Section 2.6 (2026-10-29, the user):** the CUSTOM engines (CUSTOM-Mx, CUSTOM-SQE, CUSTOM-Kx, any later
    "CUSTOM" engine) and their names are Behemoth Group's property, and the names may not be used anywhere else (3.6
    forbids it; 2.6 survives ending, section 9). Section 5.1 says CUSTOM-Mx and CUSTOM-SQE are great but not perfect and
    that Behemoth Group will keep updating them. How to use and Licences & credits say the same.
  - **Build step:** after any change, run `python scripts/make_terms.py`. It builds `desktop/build/license.txt` (ASCII,
    the NSIS installer's licence page via `nsis.license`) and `frontend/static/licences/terms-of-use.html`
    (Settings → About → Terms of use). Text between `<!-- owner -->` markers is left out.

## Licence system (2026-10-26)
The user's rules: one computer per licence; the app checks **once a day when online**; refunds cancel the code.
**No moving licences to another computer** (the user, 2026-10-26: "REMOVE THE MOVE SYSTEM FOR NOW"; it had been
built as an owner-only `admin.mjs move`, once a year, and was taken out the same day).
- **Server:** `Downloads\lunar\licence-server` (outside this repo). `src/core.js` holds all the rules. It runs on
  Cloudflare Workers + D1 (`src/worker.js`, `wrangler.toml`) or on Node (`node-server.mjs`, node:sqlite).
  `admin.mjs` is the owner's tool: new / info / refund / restore / list. `node test.mjs` runs
  13 end-to-end checks. **`keys/` is secret** (private.key signs licences, admin.token); never commit or share it.
- **Online since 2026-10-27:** https://mrsolis-licence.jonsonwhocancreate.workers.dev (Cloudflare Workers + D1
  `mrsolis-licences`, Western Europe; account jonsonwhocancreate@gmail.com).
  - Deploy from `licence-server/` with `npx wrangler deploy`. wrangler 4.150.0 is installed slim (no workerd; the
    README says why).
  - A live smoke test (fake computer IDs) passed: activate about 1 s from Ghana, check about 0.6 s, the signature
    passes the app's key, refund then revoked. Its code MRS-XDAG-N8WE-5SKX is refunded.
- **App:** `desktop/licence.js` has `PUBLIC_KEY` (Ed25519) and `SERVER` (that address; `release.yml` fails if it
  is ever the placeholder `licence.mrsolis.example` again).
  - A licence is base64url(JSON {v, code, device, kind, iat}) + "." + signature.
  - The device is the SHA-256 of Windows' MachineGuid, 40 hex characters; the raw ID is never sent.
  - It is saved in `userData/licence.json` with `lastCheck`. When the daily check finds the licence revoked
    (refunded), the file becomes `{removed, removedAt}` and `removedReason()` gives the activation screen its text.
- **Gate (`desktop/main.js`):** required when `app.isPackaged`, or in dev with `LUNAR_LICENCE=1`
  (`LUNAR_LICENCE_URL` points it at a local `node-server.mjs`; `LUNAR_DEVICE_ID` pretends to be another computer).
  - With no valid licence, `activate.html` (frameless, 520×600, `window.mrsolisLicence` from preload.js) comes
    before the splash, and its IPC only answers that window.
  - The daily check runs 30 s after the main window opens, then hourly; `dailyCheck` only contacts the server
    24 h after the last successful check.
  - When the licence is revoked: a dialog, then `app.relaunch()`, which opens on the activation screen.
- **Tested:** an Electron UI run over CDP with a scratch `--user-data-dir` (Electron honours it, checked). It covered:
  first start → activation only; a wrong code; a sloppily typed right code; splash → app; the next start skips the
  gate; a refund stopping the app 30 s after it opened; the reason shown; "Close MrSOLIS" quits.
- **Owner's window:** `licence-server/MrSOLIS Licences.cmd` (admin-ui.mjs + admin-ui.html, served on 127.0.0.1, opened
  with `msedge --app`). Tabs: new sale / free / testers, a searchable list, Payments, details, refund / undo.
- **Buying inside MrSOLIS (2026-10-27; the user chose Paystack, GHS 35, in-app only):**
  - **Server:** `licence-server/src/pay.js`, and an `orders` table.
    - `buy/start` creates an order and a Paystack payment.
    - `buy/done` is the return page; `paystack/webhook` is HMAC-SHA512 signed; `buy/status` takes the app's claim.
    - Each of these settles by verifying with Paystack and makes the code exactly once (an UPDATE ... WHERE code
      IS NULL, then INSERT OR IGNORE).
    - Underpaid -> `rejected`.
    - Test keys are ignored on the live server unless `ALLOW_TEST_PAYMENTS = "1"`.
  - **App:**
    - `licence.js`: `price()`, `buyStart()` (saves `pending {claim, url}` in licence.json), `buyStatus()`,
      `pendingPurchase()`, `isPaymentPage()` (only `https://checkout.paystack.com`, or 127.0.0.1 in tests).
    - `main.js`: `licence:price|buy|buy-reopen|buy-cancel` IPC. `watchPurchase` polls every 3 s for up to
      45 min; when paid it activates, shows the code for 4 s, then opens.
    - A pending purchase resumes when the activation window loads.
    - `activate.html` has three views (code / buy / wait). `price()` hides "Buy" when the server isn't selling,
      or when Paystack is in test mode and the app isn't pointed at a test server.
    - Test hook: `LUNAR_OPEN_URL_LOG=<file>` logs the payment page instead of opening the browser.
  - **Tested:**
    - `licence-server/test-pay.mjs`, 12 checks with a stand-in Paystack.
    - An Electron UI run (buy, wait, paid, activated, opened; closed mid-payment, then reopened and resumed).
    - The Payments tab in the built-in browser.
  - **Live:** deployed, and not selling until a live key is set (`licence-server/Set payment key.cmd`).
  - **Flutterwave (2026-10-28):** the user's Paystack sign-in failed, and they want buyers abroad too.
    - `pay.js` has provider adapters (`flutterwave`, `paystack`), each with start, verify and webhook.
    - Flutterwave Standard v3: `POST /v3/payments` with amounts in cedis; `verify_by_reference`; webhooks carry
      `verif-hash` = `FLW_SECRET_HASH`; checkout is on `checkout.flutterwave.com`.
    - Flutterwave is chosen when its key is set (`PAY_PROVIDER` overrides). Orders have a `provider` column.
    - The price route returns the provider name and `usd`; the activation screen says "Buy MrSOLIS · US$1" and
      "US$1 (GHS 12)" (dollars first since 2026-10-29; it was "GHS 35 (about US$3)"), and names the provider.
    - Tests: `test-flutterwave.mjs`, 6 checks with a stand-in Flutterwave.
    - Not yet run against real Flutterwave test mode (needs the user's test key).
  - **Flutterwave refused us (2026-10-28):** in Ghana it only onboards businesses above $5M a year; the user is on
    its waitlist. Paystack never sent its sign-in code. Neither is usable now.
  - **Mobile Money to the owner's number, LIVE since 2026-10-28** (the user chose it):
    - Config: `MOMO_NUMBER` / `MOMO_NETWORK` / `MOMO_NAME` in licence-server/wrangler.toml (0204832725, Telecel
      Cash, Janet Nartey).
    - `buy/start` with `{method: 'momo', payer}` makes an order `MOMO-XXXXXX` (6-letter reference, `payer` = the
      number they pay from) and returns what to send where. There's no provider check.
    - The owner confirms in the licences window's Payments tab (dialog: "Money received: confirm" or "Not
      received"), or with `admin.mjs confirm|reject REF` (admin routes `order-confirm`/`order-reject`).
    - Confirm makes the code via `pay.js` `fulfil()`, the same path as online payments; a rejected order can still
      be confirmed later.
    - At most 3 open MoMo orders per computer a day.
  - **App (MoMo):**
    - `licence.price()` gives `{online, provider, momo}`; `buyStart(..., {method: 'momo', payer})`.
    - `main.js` polls every 15 s for up to 3 days; the `licence:copy` IPC copies the number or reference.
    - `activate.html` has a `vMomo` view (number, network and name, reference, copy buttons); Back keeps checking
      ("See your payment").
    - The window is now 520x660.
  - **Tested:** test-momo 7/7; the Electron MoMo UI 4/4 (confirm, then activated 19 s later; restart mid-wait
    resumes); the owner's dialog in the built-in browser; live start, status and reject on Cloudflare (test order
    F5M2C8, rejected).

## Hardening (2026-10-29) — who can use MrSOLIS, and what text can do
The user: "harden MrSOLIS. Search for weaknesses and then fix". An offline app can't be made uncrackable; each layer
raises the cost. What was found, and the fix (all tested):
- **The backend ran without a licence.** Started by hand, `lunar-backend.exe` served all of MrSOLIS to a browser.
  Now `backend/gate.py` (pure-Python Ed25519, the same public key as licence.js, the same device hash of
  MachineGuid) checks `licence.json` itself: `run.py` exits 3 before serving, and `guard.Guard` refuses requests if
  unlicensed. Only frozen builds (or `LUNAR_BACKEND_LICENCE=1`); dev runs skip it. The frozen backend always binds
  127.0.0.1 (LUNAR_HOST ignored).
- **A copied licence ran anywhere.** licence.js honoured `LUNAR_DEVICE_ID` / `LUNAR_LICENCE_URL` in the installed
  app, so licence.json + the device in it worked on any computer. `licence.lock()` (main.js, packaged) turns both off.
- **Any website could read the student's data.** The backend had CORS `allow_origins=["*"]` and no auth. Now
  `backend/guard.py`: Host must be 127.0.0.1/localhost (no DNS rebinding, no LAN), and every request carries the
  per-launch secret (`LUNAR_TOKEN`): the `mrsolis` cookie main.js sets for its windows (httpOnly, SameSite=Strict)
  or the `x-mrsolis` header (main.js's health check). HTML gets a CSP (own scripts + `blob:` for the voice
  worklet; `connect-src 'self'`). **Test tools that call the API directly need the header now.**
- **Text could run code.** SymPy's sympify/parse_expr run eval; slides, brain answers, photos and pasted questions
  reach them. `backend/safemath.py`, installed by `backend/__init__.py`, patches `stringify_expr` (no `__`, no
  attribute access, no backslash, no f-strings, after NFKC) and `eval_expr` (no builtins, no lambdify/plot/preview/
  test...). 21/21 known escapes refused; SQE self-test, mathengine selftest and command_test unchanged; +0.5 ms a parse.
- **The brain engine answered anyone.** llama-server allows any origin; now `--api-key` per run (`SERVER.key`, sent
  as `SERVER.headers`).
- **The packaged app, sealed** (`desktop/build/harden.js`, electron-builder `afterPack`, 2026-10-30; it replaced
  build/fuses.js). After electron-builder packs, it rebuilds app.asar with:
  - main.js, licence.js, preload.js and updates.js scrambled by javascript-obfuscator (devDependency): names
    renamed, every string encoded, control flow flattened at 0.4. preload.js is treated as browser code. Write names
    the scrambler must hide as standalone strings: it leaves `process.env.NAME` and `obj['NAME']` keys readable
    (licence.js keeps its env names in `ENV_SERVER` / `ENV_DEVICE`, and builds the MachineGuid regex from a string).
  - `integrity.json`: SHA-256 of the engine (resources/backend/lunar-backend(.exe) and `_internal/backend/gate.*.pyd`).
    Packaged main.js `engineIntact()` checks it first thing and refuses a changed engine.
  - **Signed Windows builds only** (`sealWindowsExe`: an appx/msix target, CSC_LINK / WIN_CSC_LINK, or
    MRSOLIS_SEAL_EXE=1): app.asar's header hash goes into the exe as resource INTEGRITY/ELECTRONASAR (resedit,
    devDependency; the format of Electron Packager's src/resedit.ts). The fuses become "00001101": RunAsNode,
    NODE_OPTIONS and `--inspect` off, EnableEmbeddedAsarIntegrityValidation and OnlyLoadAppFromAsar on, so a changed
    app.asar stops Electron. **Unsigned builds leave Lunar.exe byte-for-byte Electron's own.** Smart App Control
    (on, on the user's laptop) refused a sealed unsigned Lunar.exe (Code Integrity 3077), but ran the untouched one,
    which has the same bytes as the widely used electron.exe. Linux gets the fuses but not the integrity check (it
    has no resource); macOS gets steps 1-2 only (fuses need re-signing).
  - Proved with real `electron-builder --win --dir` builds (scratchpad packaged-test.mjs; `electronDist` = the local
    Electron, no download).
    - Unsigned: it opens "Activate MrSOLIS"; it refuses a changed engine or a swapped gate .pyd; it quits on
      `--remote-debugging-port`.
    - Sealed (two earlier runs, before Smart App Control began blocking them): it stopped on a changed asar header, a
      changed byte inside app.asar, or a changed engine; `--inspect`, NODE_OPTIONS and ELECTRON_RUN_AS_NODE got
      nowhere.
    - The whole UI also ran on scrambled code (obf-dev-run.mjs: a temporary desktop-obf beside desktop, node_modules
      by junction; Electron ignores NODE_PATH).
- **Smart App Control blocks unsigned MrSOLIS.** The Code Integrity log shows the installed Lunar 1's
  `C:\Program Files\Lunar\resources\backend\lunar-backend.exe` blocked 6 times (2026-10-06), and unsigned `.pyd`
  modules blocked often. Any PC with SAC on will refuse the unsigned PyInstaller engine, before or after the
  hardening. The fix is a trusted signature: the Microsoft Store (free, below) or a certificate.
  - Packaged main.js also quits on `--remote-debugging-*` / `--inspect` / `--js-flags`, has no DevTools, and keeps
    only the Edit menu. Every window may show only MrSOLIS's own pages (`will-navigate`, `will-redirect`, no
    webviews, `window.open` denied except the main window's links -> browser).
- **The engine's licence check, compiled** (2026-10-30): `scripts/build_gate.py --release` (in release.yml, before
  PyInstaller) Cythonizes backend/gate.py into gate.<tag>.pyd and moves gate.py aside, so PyInstaller bundles only
  the native module. `--out DIR` makes a test build. The laptop compiles it with VS Build Tools 2019 (cp314, 81 KB,
  7.9 ms a check); CI with MSVC on Python 3.11. Dev runs use gate.py (.gitignore keeps the .pyd out).
- **Licence server race.** Activation counted, then inserted: with D1-like latency 7 of 8 computers got into a
  one-computer code. Now one `INSERT OR IGNORE ... SELECT ... WHERE (SELECT COUNT(*) ...) < max` (core.js). Deployed
  by the user 2026-10-30.
- **Request limits** (2026-10-30, free): wrangler.toml `[[ratelimits]]` LIMIT_APP (120/min per IP: activate, check,
  buy/status, buy/price, admin) and LIMIT_BUY (10/min: buy/start), applied in worker.js before any work. Answers
  429 `{error: 'busy'}`, which licence.js turns into "The licence server is busy". Webhooks and buy/done are never
  limited; a missing or broken limiter serves. `wrangler deploy --dry-run` lists both bindings. **Needs a deploy.**
- **Brain downloads** are pinned to a repo revision and SHA-256-checked before use (`revision` / `sha256` on each
  card; status() never sends them). The user's installed files matched the published hashes.
- **Code signing (needs money):** the free route is the Microsoft Store. Individual developer accounts have been
  free since Sept 2025; Electron/Win32 apps are allowed, MSIX packages are signed by Microsoft, and non-game apps
  may keep their own payment system. That needs the user's Partner Center registration (ID + selfie). main.js
  already skips electron-updater when `process.windowsStore`. SignPath Foundation is free for open-source projects
  only, so not for MrSOLIS.
- Tests (session scratchpad): `guard_test.py` 12/12, `safemath_test.py`, `fuse-test.mjs`, `race-test.mjs`,
  `worker-limit-test.mjs` 5/5, `packaged-test.mjs` 8/8, `brain_key_test.py` (real Speedy), and the Electron runs
  `sqe-calc-test.mjs` 8/8 (plain and scrambled), `additions-ui-test.mjs` 8/8, `sqe-ui-test.mjs` 10/10, with no CSP blocks.

