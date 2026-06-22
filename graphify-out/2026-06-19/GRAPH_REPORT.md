# Graph Report - Lunar-ai-main  (2026-06-19)

## Corpus Check
- 16 files · ~10,972,872 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 385 nodes · 652 edges · 24 communities (19 shown, 5 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 10 edges (avg confidence: 0.82)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Frontend App Controllers|Frontend App Controllers]]
- [[_COMMUNITY_Classroom Frontend Controller|Classroom Frontend Controller]]
- [[_COMMUNITY_FastAPI Endpoints & Routes|FastAPI Endpoints & Routes]]
- [[_COMMUNITY_Slide & Document Extraction|Slide & Document Extraction]]
- [[_COMMUNITY_Nebula Background Animation|Nebula Background Animation]]
- [[_COMMUNITY_Classroom Teaching & Quiz Logic|Classroom Teaching & Quiz Logic]]
- [[_COMMUNITY_Local LLM Client (Ollama)|Local LLM Client (Ollama)]]
- [[_COMMUNITY_Voice Engine (STTTTS)|Voice Engine (STT/TTS)]]
- [[_COMMUNITY_App Concepts & UI Sections|App Concepts & UI Sections]]
- [[_COMMUNITY_Lecture Delivery & TTS|Lecture Delivery & TTS]]
- [[_COMMUNITY_Topics & Solutions UI|Topics & Solutions UI]]
- [[_COMMUNITY_Upload & Classroom Init|Upload & Classroom Init]]
- [[_COMMUNITY_Ask Lunar Chat Modal (legacy)|Ask Lunar Chat Modal (legacy)]]
- [[_COMMUNITY_Quiz Creation & Timer (legacy)|Quiz Creation & Timer (legacy)]]
- [[_COMMUNITY_Voice Mode Mic Control|Voice Mode Mic Control]]
- [[_COMMUNITY_Quiz Scoring & Feedback (legacy)|Quiz Scoring & Feedback (legacy)]]
- [[_COMMUNITY_Model Setup & Download|Model Setup & Download]]
- [[_COMMUNITY_Audio VAD & Barge-in|Audio VAD & Barge-in]]
- [[_COMMUNITY_Backend Package Init|Backend Package Init]]
- [[_COMMUNITY_Startup Script|Startup Script]]
- [[_COMMUNITY_FastAPI Web Server|FastAPI Web Server]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]

## God Nodes (most connected - your core abstractions)
1. `$()` - 144 edges
2. `NebulaBackground` - 24 edges
3. `_ocr_image_obj()` - 12 edges
4. `extract_rich_slides()` - 12 edges
5. `crTeachSlide()` - 12 edges
6. `extract_text_from_file()` - 11 edges
7. `escapeHtml()` - 11 edges
8. `speakAndType()` - 10 edges
9. `extract_slides()` - 9 edges
10. `crHandleMessage()` - 9 edges

## Surprising Connections (you probably didn't know these)
- `Slide Upload Entry` --conceptually_related_to--> `Document Extraction Stack`  [INFERRED]
  frontend/home.html → requirements.txt
- `Slide Upload Entry` --conceptually_related_to--> `OCR for Image Slides (RapidOCR)`  [INFERRED]
  frontend/home.html → requirements.txt
- `Teaching Board` --conceptually_related_to--> `Local LLM RAG (Ollama qwen3:1.7b)`  [INFERRED]
  frontend/home.html → requirements.txt
- `Speak or Type Answer` --conceptually_related_to--> `faster-whisper STT`  [INFERRED]
  frontend/home.html → requirements.txt
- `Speak or Type Answer` --conceptually_related_to--> `Piper TTS`  [INFERRED]
  frontend/home.html → requirements.txt

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Slide Ingestion and Extraction** — frontend_home_slide_upload, requirements_document_extraction, requirements_ocr [INFERRED 0.85]
- **Voice Interaction Loop** — frontend_home_voice_answer, requirements_faster_whisper, requirements_piper_tts, requirements_voice_pipeline [INFERRED 0.85]
- **Grounded Teaching and Quiz Flow** — frontend_home_board, frontend_home_quiz_flow, frontend_home_grounded_material, requirements_ollama_rag [INFERRED 0.85]

## Communities (24 total, 5 thin omitted)

### Community 0 - "Frontend App Controllers"
Cohesion: 0.04
Nodes (40): $(), aiStatusChip, cr, CR_BUSY, crEls, difficultySelect, fileInfo, fileInput (+32 more)

### Community 1 - "Classroom Frontend Controller"
Cohesion: 0.22
Nodes (15): crAppendBoard(), crBuildProgress(), crHandleMessage(), crNextSlide(), crPrefetchSlide(), crPrevSlide(), crRenderBoard(), crSetStatus() (+7 more)

### Community 2 - "FastAPI Endpoints & Routes"
Cohesion: 0.08
Nodes (37): classroom_chat_stream(), classroom_search(), classroom_start(), classroom_teach_stream(), ClassroomChatRequest, ClassroomStartRequest, _embed_slides_bg(), _ensure_board_image() (+29 more)

### Community 3 - "Slide & Document Extraction"
Cohesion: 0.07
Nodes (57): _autosplit(), _chalk_from_rgb(), _dedupe_links(), _extract_csv(), _extract_docx(), _extract_image(), _extract_pdf(), _extract_pptx() (+49 more)

### Community 5 - "Classroom Teaching & Quiz Logic"
Cohesion: 0.27
Nodes (10): chat_stream(), clean_board_text(), _history_block(), _is_reference_line(), Classroom tutor for Lunar — explains one slide at a time, then quizzes.  The LLM, Stream Lunar's reply to whatever the student says, on the current slide.      `f, Return the slide text verbatim with only reference/dedication lines removed., Stream Lunar's tutoring explanation of the slide (shown under the image). (+2 more)

### Community 6 - "Local LLM Client (Ollama)"
Cohesion: 0.13
Nodes (21): _base_options(), chat(), chat_json(), chat_stream(), embed(), _extract_json(), health(), LocalLLMError (+13 more)

### Community 7 - "Voice Engine (STT/TTS)"
Cohesion: 0.15
Nodes (18): engine_status(), _get_piper(), _get_whisper(), _pcm_to_wav(), _piper_to_wav(), Local voice engine for Lunar AI — on-device STT and TTS (replaces Deepgram)., Synthesize with Piper across its several API generations -> WAV bytes., Fallback TTS using the OS speech engine (pyttsx3 / Windows SAPI). (+10 more)

### Community 8 - "App Concepts & UI Sections"
Cohesion: 0.18
Nodes (15): App Navigation Link, Teaching Board, Classroom View, Strictly Your Slides Grounding, Lunar Landing Page, 100% On-Device Privacy, Grounded Quiz Flow, Slide Upload Entry (+7 more)

### Community 9 - "Lecture Delivery & TTS"
Cohesion: 0.14
Nodes (21): continueNextChunk(), crAttr(), crLinksHTML(), crLoadImage(), crMediaHTML(), crTypeInto(), crTypeSlidePayload(), delay() (+13 more)

### Community 10 - "Topics & Solutions UI"
Cohesion: 0.20
Nodes (11): appendQuestionCard(), appendTopicChip(), escapeHtml(), formatSolution(), getLecture(), getSolution(), handleAnalyzeTopics(), handleGenerate() (+3 more)

### Community 11 - "Upload & Classroom Init"
Cohesion: 0.33
Nodes (5): Don't break things, Graphify knowledge graph — consult this BEFORE searching, Lunar AI — project guide for Claude Code, Rebuilding the graph after code changes, Subsystem map (Graphify communities)

### Community 12 - "Ask Lunar Chat Modal (legacy)"
Cohesion: 0.33
Nodes (6): formatAskLunarError(), getAskLunarHistory(), handleAskLunarInputKeydown(), openAskLunarModal(), renderAskLunarChat(), submitAskLunarQuestion()

### Community 13 - "Quiz Creation & Timer (legacy)"
Cohesion: 0.33
Nodes (6): handleCreateQuiz(), handleNextQuestion(), practiceWeakAreas(), renderQuizQuestion(), startTimer(), updateTimerDisplay()

### Community 14 - "Voice Mode Mic Control"
Cohesion: 0.40
Nodes (6): downsampleTo16k(), encodeWav(), finalizeUtterance(), flattenVad(), handleAudioFrame(), interruptLunar()

### Community 15 - "Quiz Scoring & Feedback (legacy)"
Cohesion: 0.11
Nodes (28): build_crib_sheet(), calc_questions(), _cos(), definition_pairs(), _embed(), _format_num(), formula_lines(), generate() (+20 more)

### Community 17 - "Audio VAD & Barge-in"
Cohesion: 0.47
Nodes (6): quitVoiceMode(), resetVad(), restartDuplexListening(), startDuplexListening(), stopDuplexListening(), toggleMicrophoneInput()

### Community 21 - "Community 21"
Cohesion: 0.22
Nodes (9): crCloseSearch(), crEnterReading(), crExit(), crInit(), crRunSearch(), formatFileSize(), handleFileUpload(), resetUpload() (+1 more)

### Community 22 - "Community 22"
Cohesion: 0.40
Nodes (5): analyzeLunarPerformance(), handleSubmitAnswer(), handleTimeUp(), showFeedback(), showQuizScore()

### Community 23 - "Community 23"
Cohesion: 0.40
Nodes (4): fs, inp, src, start

## Knowledge Gaps
- **52 isolated node(s):** `UploadFile`, `ndarray`, `fs`, `src`, `start` (+47 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `$()` connect `Frontend App Controllers` to `Classroom Frontend Controller`, `Lecture Delivery & TTS`, `Topics & Solutions UI`, `Ask Lunar Chat Modal (legacy)`, `Quiz Creation & Timer (legacy)`, `Voice Mode Mic Control`, `Audio VAD & Barge-in`, `Community 21`, `Community 22`?**
  _High betweenness centrality (0.132) - this node is a cross-community bridge._
- **Why does `extract_rich_slides()` connect `Slide & Document Extraction` to `FastAPI Endpoints & Routes`?**
  _High betweenness centrality (0.012) - this node is a cross-community bridge._
- **Why does `extract_slides()` connect `Slide & Document Extraction` to `FastAPI Endpoints & Routes`?**
  _High betweenness centrality (0.009) - this node is a cross-community bridge._
- **What connects `Lunar AI backend package.`, `Classroom tutor for Lunar — explains one slide at a time, then quizzes.  The LLM`, `Return the slide text verbatim with only reference/dedication lines removed.` to the rest of the system?**
  _123 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Frontend App Controllers` be split into smaller, more focused modules?**
  _Cohesion score 0.03508771929824561 - nodes in this community are weakly interconnected._
- **Should `FastAPI Endpoints & Routes` be split into smaller, more focused modules?**
  _Cohesion score 0.07564102564102564 - nodes in this community are weakly interconnected._
- **Should `Slide & Document Extraction` be split into smaller, more focused modules?**
  _Cohesion score 0.07199032062915911 - nodes in this community are weakly interconnected._