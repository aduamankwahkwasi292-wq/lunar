# Lunar AI — project guide for Claude Code

Lunar AI is a **100% local, offline study app**, shipped as a **cross-platform Electron desktop app**
(Windows/macOS/Linux) — one double-click installer, models bundled, zero setup. Upload slides → a
full-screen hologram classroom where an AI tutor (**Lunar**) teaches slide-by-slide on the board. No
cloud, no API keys. Stack: Electron shell (`desktop/`) → spawns a PyInstaller-frozen FastAPI backend
(`backend/`) → runs `Qwen2.5-1.5B-Instruct` (chat) + `nomic-embed-text-v1.5` (embeddings) **in-process
via llama.cpp** (`llama-cpp-python`); vanilla-JS frontend; RapidOCR + PyMuPDF for image-slide OCR.
**No voice.** `backend/local_llm.py` defaults to the llama.cpp backend and falls back to Ollama only in
dev when the GGUFs aren't present (`LUNAR_LLM_BACKEND=auto`). Build steps: see `BUILD.md`
(`scripts/fetch_models.py` then `scripts/build_desktop.py`, run per-OS).

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
- Keep the app fully local — never reintroduce cloud LLM/API-key/Deepgram paths.
- Preserve every DOM id/class that `script.js` selects; CSS is restyle-only (additive), no renames.
