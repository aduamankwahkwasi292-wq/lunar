/* ═══════════════════════════════════════════════════════════════════
   MrSOLIS 3 Wire — binds the UI (index.html) to the local backend.

   The classroom: upload · slide-by-slide lesson · chat · highlight →
   Explain / Solve / save to Notes · Find anything · progress · the slide
   ladder · engine status · focus mode · window controls.
   The other pages (Uploads, Subjects, Notes, Quizzes, History, Settings,
   Tools) live in mrsolis-pages.js; voice in mrsolis-voice.js. With no
   slides open, chat still works (/api/chat_stream) and every answer asks
   for the student's material.
   ═══════════════════════════════════════════════════════════════════ */
'use strict';

const $ = (id) => document.getElementById(id);
const boardFrame = $('board');          // the whole board (frame + surface + ladder)
const board = $('cr-board');            // the slide viewer in the middle (it scrolls when a slide is taller)
const boardContent = $('board-content');
const chatInput = $('chat-input');
const searchInput = $('search-input');
const searchResults = $('search-results');
const fileInput = $('file-input');
const selTools = $('cr-sel-tools');
const toastEl = $('mrsolis-toast');

const RING = 2 * Math.PI * 52;     // circumference of the progress ring (r=52 in its viewBox)
const MAX_TICKS = 40;              // the slide ladder shows one tick per slide, up to this many

// ── State ────────────────────────────────────────────────────────────
const S = {
    sessionId: null,
    filename: '',
    count: 0,            // slides in the deck
    index: 0,            // slide on the board
    active: false,       // a lesson is open (or being read)
    busy: false,         // MrSOLIS is writing a lesson or a reply
    abort: null,         // controller for the stream being written
    stopped: false,      // the user pressed Esc / Stop (keep what was written)
    gen: 0,              // bumped on every slide change; stale async work checks it
    isImageSlide: false,
    parts: [],           // what's written under the slide: {kind: lesson|user|assistant|error, text}
    streamPart: null,    // the part currently being streamed into
    history: [],         // recent turns sent with chat for context
    words: null,         // word boxes of a PDF slide, for box-select
    lastSelection: '',
    marquee: false,
};

// ── Helpers ──────────────────────────────────────────────────────────
function escapeHtml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function showToast(msg, ms = 2600) {
    toastEl.textContent = msg;
    toastEl.hidden = false;
    // over the board's lower edge in class; on the other pages (board hidden) near the bottom of the page
    const onBoard = boardFrame.getBoundingClientRect().width > 0;
    const b = (onBoard ? boardFrame : $('stage')).getBoundingClientRect();
    toastEl.style.left = `${b.left + b.width / 2}px`;
    toastEl.style.top = `${b.bottom - (onBoard ? 52 : 44)}px`;
    toastEl.classList.remove('fade-out');
    clearTimeout(showToast.t1); clearTimeout(showToast.t2);
    showToast.t1 = setTimeout(() => {
        toastEl.classList.add('fade-out');
        showToast.t2 = setTimeout(() => { toastEl.hidden = true; }, 250);
    }, ms);
}

/** POST json and call onObject for every NDJSON line. Errors thrown by onObject propagate. */
async function streamNDJSON(url, body, onObject, signal, headers = {}) {
    const res = await fetch(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...headers },
        body: JSON.stringify(body), signal,
    });
    if (!res.ok || !res.body) {
        let detail = `Request failed (${res.status})`;
        try { detail = (await res.json()).detail || detail; } catch (e) { /* not json */ }
        throw new Error(detail);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const emit = (line) => {
        line = line.trim();
        if (!line) return;
        let obj;
        try { obj = JSON.parse(line); } catch (e) { return; }
        onObject(obj);
    };
    for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buffer.indexOf('\n')) >= 0) {
            emit(buffer.slice(0, nl));
            buffer = buffer.slice(nl + 1);
        }
    }
    emit(buffer);
}

// ── Formatting what MrSOLIS writes ───────────────────────────────────
// The small model sometimes draws ASCII number lines/tables despite being told not to:
// drop fenced code and any run of 3+ "wordless" lines.
function stripDiagrams(text) {
    text = (text || '').replace(/```[\s\S]*?```/g, ' ');
    const lines = text.split('\n');
    const weak = lines.map((l) => !!l.trim() && !/[A-Za-z]{3,}/.test(l));
    const drop = new Array(lines.length).fill(false);
    for (let i = 0; i < lines.length;) {
        if (!weak[i]) { i++; continue; }
        let j = i;
        while (j < lines.length && weak[j]) j++;
        if (j - i >= 3) for (let k = i; k < j; k++) drop[k] = true;
        i = j;
    }
    return lines.filter((_, k) => !drop[k]).join('\n').replace(/^[ \t]*`+[ \t]*$/gm, '');
}

// LaTeX the model emits → readable plain maths.
function mathify(t) {
    return t
        .replace(/\$\$?/g, '')
        // set braces \{ … \} are real braces ("{ all KNUST students }"): keep them past the brace strip below
        .replace(/\\\{/g, '\u0001').replace(/\\\}/g, '\u0002')
        .replace(/\\\s*[\[\]()]/g, '')
        .replace(/\\text\s*\{([^}]*)\}/g, '$1')
        // P_{out} → P_out and x^{2} → x^(2) first, so \frac{P_{out}}{P_{in}} has no nested braces left
        .replace(/_\{([^{}]*)\}/g, '_$1').replace(/\^\{([^{}]*)\}/g, '^($1)')
        .replace(/\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, '($1)/($2)')
        .replace(/\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, '($1)/($2)')   // a fraction inside a fraction
        .replace(/\\sqrt\s*\{([^}]*)\}/g, '√($1)')
        .replace(/\\(leq|le)(?![A-Za-z])/g, '≤').replace(/\\(geq|ge)(?![A-Za-z])/g, '≥')
        .replace(/\\(neq|ne)(?![A-Za-z])/g, '≠').replace(/\\approx(?![A-Za-z])/g, '≈')
        .replace(/\\times(?![A-Za-z])/g, '×').replace(/\\div(?![A-Za-z])/g, '÷')
        .replace(/\\(cdot|ast)(?![A-Za-z])/g, '·').replace(/\\pm(?![A-Za-z])/g, '±')
        .replace(/\\infty(?![A-Za-z])/g, '∞').replace(/\\sqrt(?![A-Za-z])/g, '√')
        .replace(/\\(Rightarrow|implies)(?![A-Za-z])/g, '⇒').replace(/\\(rightarrow|to)(?![A-Za-z])/g, '→')
        .replace(/\\sum(?![A-Za-z])/g, 'Σ').replace(/\\int(?![A-Za-z])/g, '∫').replace(/\\partial(?![A-Za-z])/g, '∂')
        .replace(/\\alpha(?![A-Za-z])/g, 'α').replace(/\\beta(?![A-Za-z])/g, 'β').replace(/\\gamma(?![A-Za-z])/g, 'γ')
        .replace(/\\delta(?![A-Za-z])/g, 'δ').replace(/\\theta(?![A-Za-z])/g, 'θ').replace(/\\lambda(?![A-Za-z])/g, 'λ')
        .replace(/\\mu(?![A-Za-z])/g, 'μ').replace(/\\pi(?![A-Za-z])/g, 'π').replace(/\\sigma(?![A-Za-z])/g, 'σ')
        .replace(/\\(phi|varphi)(?![A-Za-z])/g, 'φ').replace(/\\Omega(?![A-Za-z])/g, 'Ω').replace(/\\omega(?![A-Za-z])/g, 'ω')
        .replace(/\\eta(?![A-Za-z])/g, 'η').replace(/\\(epsilon|varepsilon)(?![A-Za-z])/g, 'ε').replace(/\\rho(?![A-Za-z])/g, 'ρ')
        .replace(/\\tau(?![A-Za-z])/g, 'τ').replace(/\\nu(?![A-Za-z])/g, 'ν').replace(/\\kappa(?![A-Za-z])/g, 'κ').replace(/\\zeta(?![A-Za-z])/g, 'ζ')
        .replace(/\\xi(?![A-Za-z])/g, 'ξ').replace(/\\chi(?![A-Za-z])/g, 'χ').replace(/\\psi(?![A-Za-z])/g, 'ψ').replace(/\\Delta(?![A-Za-z])/g, 'Δ')
        .replace(/\\Sigma(?![A-Za-z])/g, 'Σ').replace(/\\Phi(?![A-Za-z])/g, 'Φ').replace(/\\Gamma(?![A-Za-z])/g, 'Γ').replace(/\\Lambda(?![A-Za-z])/g, 'Λ')
        .replace(/\\Theta(?![A-Za-z])/g, 'Θ')
        // sets and logic (discrete maths): "a \in A" read "a A" before these
        .replace(/\\notin(?![A-Za-z])/g, '∉').replace(/\\in(?![A-Za-z])/g, '∈').replace(/\\ni(?![A-Za-z])/g, '∋')
        .replace(/\\subseteq(?![A-Za-z])/g, '⊆').replace(/\\supseteq(?![A-Za-z])/g, '⊇')
        .replace(/\\subset(?![A-Za-z])/g, '⊂').replace(/\\supset(?![A-Za-z])/g, '⊃')
        .replace(/\\cup(?![A-Za-z])/g, '∪').replace(/\\cap(?![A-Za-z])/g, '∩').replace(/\\setminus(?![A-Za-z])/g, '∖')
        .replace(/\\(emptyset|varnothing)(?![A-Za-z])/g, '∅').replace(/\\forall(?![A-Za-z])/g, '∀')
        .replace(/\\exists(?![A-Za-z])/g, '∃').replace(/\\(neg|lnot)(?![A-Za-z])/g, '¬')
        .replace(/\\(land|wedge)(?![A-Za-z])/g, '∧').replace(/\\(lor|vee)(?![A-Za-z])/g, '∨')
        .replace(/\\(Leftrightarrow|iff)(?![A-Za-z])/g, '⇔').replace(/\\leftrightarrow(?![A-Za-z])/g, '↔')
        .replace(/\\mapsto(?![A-Za-z])/g, '↦').replace(/\\circ(?![A-Za-z])/g, '∘').replace(/\\equiv(?![A-Za-z])/g, '≡')
        .replace(/\\oplus(?![A-Za-z])/g, '⊕').replace(/\\(mid|vert)(?![A-Za-z])/g, '|')
        .replace(/\\(ldots|dots|cdots)(?![A-Za-z])/g, '…').replace(/\\colon(?![A-Za-z])/g, ':')
        .replace(/\\mathbb\s*\{?([A-Z])\}?/g, (m, c) => ({ N: 'ℕ', Z: 'ℤ', Q: 'ℚ', R: 'ℝ', C: 'ℂ' })[c] || c)
        .replace(/\\(?:,|;|!|quad|qquad|left|right|displaystyle)(?![A-Za-z])/g, ' ')
        .replace(/\\[a-zA-Z]+/g, '')
        .replace(/\\(?=\s|$)/g, '')
        .replace(/[{}]/g, '')
        .replace(/\u0001/g, '{').replace(/\u0002/g, '}')
        .replace(/\^\(?(\d)\)?/g, (m, d) => '⁰¹²³⁴⁵⁶⁷⁸⁹'[+d])
        .replace(/([0-9A-Za-z)])[ \t]*(?<!\*)\*(?!\*)[ \t]*([0-9A-Za-z(])/g, '$1 × $2');
}

function inlineMd(s) {
    return s
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[^*\w])\*(?!\s)(.+?)\*(?!\*)/g, '$1<em>$2</em>')
        .replace(/(^|\W)_(?!\s)(.+?)_(?=\W|$)/g, '$1<em>$2</em>');
}

/** Markdown-lite → HTML (escaped first, so slide or model text can never inject markup). */
function formatLecture(text) {
    const out = [];
    let para = [], list = null;
    const flushPara = () => { if (para.length) { out.push('<p>' + para.map(inlineMd).join('<br>') + '</p>'); para = []; } };
    const flushList = () => { if (list) { out.push('<ul>' + list.map((li) => '<li>' + inlineMd(li) + '</li>').join('') + '</ul>'); list = null; } };
    for (const raw of mathify(escapeHtml(stripDiagrams(text))).split('\n')) {
        const line = raw.trim();
        let m;
        if (!line) { flushPara(); flushList(); continue; }
        if ((m = line.match(/^(#{1,6})\s+(.*)$/))) {
            flushPara(); flushList();
            const lvl = Math.min(3, m[1].length);
            out.push(`<h${lvl}>${inlineMd(m[2])}</h${lvl}>`);
            continue;
        }
        if ((m = line.match(/^(?:[-•*]|\d+[.)])\s+(.*)$/))) { flushPara(); (list = list || []).push(m[1]); continue; }
        flushList();
        para.push(line);
    }
    flushPara(); flushList();
    return out.join('');
}

function plainText(md) {
    return (md || '').replace(/[*_`#>]/g, '').replace(/\s+/g, ' ').trim();
}

// ══════════════════════════════════════════════════════════════════════
//   BOARD
// ══════════════════════════════════════════════════════════════════════
// The slide sits in the middle (#board-content → #slide-area, rendered once per slide); the talk — lessons,
// questions, answers, re-rendered while streaming — is in the panel on the right (#talk-area in #talk-scroll),
// with the typing bar under it (layout of 2026-11-11).
boardContent.innerHTML = '<div id="slide-area"></div>';
const slideArea = $('slide-area');
const talkArea = $('talk-area');
const talkScroll = $('talk-scroll');

const thinking = (what = 'MrSOLIS is thinking…') => `<div class="cr-thinking"><i></i><i></i><i></i> <span>${what}</span></div>`;
const THINKING = thinking();

// The board is empty (as in the design) until a lesson starts — or the student chats without one.
function showBoard(on) {
    boardContent.hidden = !on;
    $('board-idle').hidden = on;
}

// The hint and the chat box say what to do: with no slides open, keep asking for them.
const HINT_LESSON = 'Highlight any part of the slide or this lesson, then tap <b>Explain</b> for a closer look — or <b>Solve</b> if it\'s a question.';
const HINT_NO_SLIDES = 'No slides yet? Drop your lecture slides or notes in the middle (or press <b>+</b>) and MrSOLIS will teach them here — or just ask anything below.';
function chatPlaceholder() {
    if (typeof VID !== 'undefined' && VID.id) return 'Ask about this video — e.g. “Summarise it” or “What did he say about…?”';
    return S.sessionId ? 'Ask MrSOLIS 3 anything about this lesson...' : 'Ask MrSOLIS anything — or upload your slides to start learning...';
}
function lessonUi() {
    $('hint-text').innerHTML = S.sessionId ? HINT_LESSON : HINT_NO_SLIDES;
    const mic = $('chat-mic');
    if (!mic.classList.contains('on') && !mic.classList.contains('starting')) chatInput.placeholder = chatPlaceholder();
}

// The slide always fits the viewer whole (its padding is 16 px top and bottom).
new ResizeObserver(() => {
    board.style.setProperty('--slide-max', `${Math.max(160, board.clientHeight - 34)}px`);
    if (S.zoom !== 1) applyZoom();                    // the zoom is a share of the fitted size: size it again
}).observe(board);

// ── Zoom on the slide (the user, 2026-11-11) ─────────────────────────
// 100% = the slide fitted to the viewer. A picture slide gets a width; a words-only slide (.cr-sheet) gets CSS zoom,
// so its text grows and wraps. Box-select keeps working: it measures the picture as it is on screen.
const ZOOM_STEPS = [0.5, 0.67, 0.8, 1, 1.25, 1.5, 2, 2.5, 3, 4];
S.zoom = 1;
const zoomBar = $('zoom-bar');

/** Size the slide for S.zoom. `fresh`: a new slide — start at its top, centred. */
function applyZoom(fresh) {
    const img = slideArea.querySelector('.cr-slide-img');
    const sheet = slideArea.querySelector('.cr-sheet');
    zoomBar.hidden = !(img || sheet);
    $('zoom-level').textContent = `${Math.round(S.zoom * 100)}%`;
    $('zoom-out').disabled = S.zoom <= ZOOM_STEPS[0];
    $('zoom-in').disabled = S.zoom >= ZOOM_STEPS[ZOOM_STEPS.length - 1];
    board.classList.toggle('zoomed', S.zoom !== 1);
    if (img) {
        img.style.width = img.style.maxWidth = img.style.maxHeight = '';
        if (S.zoom !== 1) {
            const fit = img.getBoundingClientRect().width;            // its fitted width, as the CSS lays it out
            if (!fit) { img.decode().then(() => applyZoom(fresh)).catch(() => {}); return; }
            img.style.maxWidth = img.style.maxHeight = 'none';
            img.style.width = `${Math.round(fit * S.zoom)}px`;
        }
    }
    if (sheet) sheet.style.zoom = S.zoom === 1 ? '' : String(S.zoom);
    if (fresh) {
        board.scrollTop = 0;
        board.scrollLeft = Math.max(0, (board.scrollWidth - board.clientWidth) / 2);
    }
}

/** Zoom to `z`, keeping the point under (x, y) — the pointer, or the viewer's centre — where it is. */
function setZoom(z, x, y) {
    z = Math.min(ZOOM_STEPS[ZOOM_STEPS.length - 1], Math.max(ZOOM_STEPS[0], z));
    if (Math.abs(z - 1) < 0.03) z = 1;                                  // land on "fit" when passing it
    z = Math.round(z * 100) / 100;
    if (z === S.zoom || zoomBar.hidden) return;
    const r = board.getBoundingClientRect();
    const px = (x ?? r.left + r.width / 2) - r.left, py = (y ?? r.top + r.height / 2) - r.top;
    const fx = (board.scrollLeft + px) / Math.max(1, board.scrollWidth);
    const fy = (board.scrollTop + py) / Math.max(1, board.scrollHeight);
    S.zoom = z;
    applyZoom();
    board.scrollLeft = fx * board.scrollWidth - px;
    board.scrollTop = fy * board.scrollHeight - py;
    hideSelTools(); clearMarquee();
}

/** The next step in or out (Ctrl +, Ctrl −, the buttons). */
function zoomStep(dir) {
    const next = dir > 0 ? ZOOM_STEPS.find((s) => s > S.zoom + 0.001) : [...ZOOM_STEPS].reverse().find((s) => s < S.zoom - 0.001);
    if (next) setZoom(next);
}

$('zoom-in').addEventListener('click', () => zoomStep(1));
$('zoom-out').addEventListener('click', () => zoomStep(-1));
$('zoom-level').addEventListener('click', () => setZoom(1));
// Ctrl + wheel, and a trackpad pinch (which arrives as Ctrl + wheel): zoom the slide, not the whole window
board.addEventListener('wheel', (e) => {
    if (!e.ctrlKey || zoomBar.hidden) return;
    e.preventDefault();
    setZoom(S.zoom * Math.exp(-e.deltaY * 0.002), e.clientX, e.clientY);
}, { passive: false });
// every new slide (or an empty board) goes through #slide-area: size it at the deck's zoom
new MutationObserver(() => applyZoom(true)).observe(slideArea, { childList: true });

function partHTML(p) {
    const live = S.busy && p === S.streamPart;
    if (p.kind === 'user') {
        const pic = p.image ? `<img class="msg-pic" src="${p.image}" alt="Your picture">` : '';
        const vid = p.video ? `<span class="msg-vid"><svg class="ico"><use href="#i-film"/></svg>${escapeHtml(p.video)}</span>` : '';
        return `<div class="msg-user">${pic}${vid}${escapeHtml(p.text)}</div>`;
    }
    if (p.kind === 'error') return `<div class="msg-error">${escapeHtml(p.text)}</div>`;
    const cls = p.kind === 'lesson' ? 'lesson' : 'msg-assistant';
    // a brain that sees takes a few seconds over a picture before its first word
    if (live && !p.text.trim()) {
        return `<div class="${cls}">${p.looking ? thinking(p.kind === 'lesson' ? 'MrSOLIS is looking at the slide…'
            : p.watch ? 'MrSOLIS is watching the video…'
            : p.photo ? 'MrSOLIS is looking at your picture…' : 'MrSOLIS is looking at the slide…') : THINKING}</div>`;
    }
    const save = live ? '' : `<button type="button" class="part-save${p.saved ? ' saved' : ''}" data-part="${S.parts.indexOf(p)}" title="${p.saved ? 'Saved to Notes' : 'Save to Notes'}"><svg class="ico"><use href="#i-bookmark"/></svg>${p.saved ? 'Saved' : 'Save'}</button>`;
    // with no slides open, every answer ends on a way to start learning properly
    const start = p.free && !live && !S.sessionId && !p.watch          // not under an answer about a video
        ? `<div class="part-start"><button type="button" class="primary" data-start="upload"><svg class="ico"><use href="#i-upload"/></svg>Upload slides</button>` +
          `<button type="button" data-start="uploads"><svg class="ico"><use href="#i-folder"/></svg>Open a past upload</button></div>`
        : '';
    // Read aloud (mrsolis-voice.js); pressing it again stops
    const reading = typeof READ !== 'undefined' && READ.part === p;
    const readBtn = !live && typeof VOICE !== 'undefined' && VOICE.speak
        ? `<button type="button" class="${reading ? 'on' : ''}" data-read="${S.parts.indexOf(p)}">` +
          (reading ? '<svg class="ico"><use href="#i-stop"/></svg>Stop reading' : '<svg class="ico"><use href="#i-speaker"/></svg>Read aloud') +
          '</button>'
        : '';
    // a solved maths question: more like it in the SQE window, with new numbers
    const practise = !live && p.sqe
        ? `<button type="button" data-sqe="${S.parts.indexOf(p)}"><svg class="ico"><use href="#i-quiz"/></svg>Practise more like this</button>`
        : '';
    const read = readBtn || practise ? `<div class="part-read">${readBtn}${practise}</div>` : '';
    const exact = !live && p.exact ? p.exact.map((d, i) => exactCardHTML(d, `data-exact="${S.parts.indexOf(p)}:${i}:run"`,
        `data-exact="${S.parts.indexOf(p)}:${i}:edit"`)).join('') : '';
    return `<div class="${cls}">${save}${formatLecture(p.text)}${live ? '<span class="cr-cursor">▋</span>' : ''}${exact}${read}${start}</div>`;
}

/** A CUSTOM-Mx draft to check: the exact command, what to look at, then Run it or Edit it first. Shared by the
 *  chat, lessons and the Solver (each passes its own button attributes). */
function exactCardHTML(d, runAttr, editAttr) {
    const notes = (d.check || []).map((c) => `Check: ${c}.`);
    if (d.left_out && d.left_out.length) notes.push(`Left out: ${d.left_out.join(', ')}.`);
    return `<div class="exact-card"><div class="exact-head"><svg class="ico"><use href="#i-sigma"/></svg>` +
        `${d.by === 'brain' ? 'Set up by the brain — check every value' : 'Work it exactly with CUSTOM-Mx'}</div>` +
        `<code>/mx ${escapeHtml(d.command)}</code>` +
        (notes.length ? `<div class="exact-note">${escapeHtml(notes.join(' '))}</div>` : '') +
        `<div class="exact-acts"><button type="button" class="primary" ${runAttr}><svg class="ico"><use href="#i-play"/></svg>Run</button>` +
        `<button type="button" ${editAttr}><svg class="ico"><use href="#i-edit"/></svg>Edit</button></div></div>`;
}

/** Save a lesson / answer, or a highlight, to the deck's notes (General notes with no slides open). */
async function saveNote(text, kind, part) {
    text = (text || '').trim();
    if (part && part.free) text = text.replace(/\n\n[^\n]*$/, '').trim();   // not the upload reminder
    if (part && part.transition && text.endsWith(part.transition)) text = text.slice(0, -part.transition.length).trim();   // nor "next slide"
    if (!text) return;
    const deck = S.sessionId || null;
    try {
        const res = await fetch('/api/notes', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ deck_id: deck, text, kind, slide: deck ? S.index : null }),
        });
        if (!res.ok) throw new Error((await res.json()).detail || 'Could not save');
        if (part) { part.saved = true; renderTalk(); }
        showToast(deck ? 'Saved to Notes' : 'Saved to General notes');
    } catch (e) {
        showToast(e.message, 4000);
    }
}

let renderTimer = null;
function renderTalk(follow = false) {
    clearTimeout(renderTimer); renderTimer = null;
    const nearBottom = talkScroll.scrollHeight - talkScroll.scrollTop - talkScroll.clientHeight < 60;
    // what was being read aloud has left the board (new slide, cleared…): stop reading it
    if (typeof READ !== 'undefined' && READ.part && !S.parts.includes(READ.part)) stopReading();
    talkArea.innerHTML = S.parts.map(partHTML).join('');
    updateEject();
    // follow the writing, but don't yank the student back if they scrolled up to read
    if (follow || nearBottom) talkScroll.scrollTop = talkScroll.scrollHeight;
}
// Coalesce token renders to ~16 fps (re-formatting the whole text per token would lag).
function renderTalkSoon() {
    if (!renderTimer) renderTimer = setTimeout(() => renderTalk(), 60);
}

function mediaHTML(b) {
    if (!b || !b.url) return '';
    const url = escapeHtml(b.url);
    if (b.type === 'image') {
        const cap = (b.alt || '').trim();
        return `<figure class="cr-figure"><img src="${url}" alt="${escapeHtml(cap)}" loading="lazy">` +
            (cap ? `<figcaption>${escapeHtml(cap)}</figcaption>` : '') + '</figure>';
    }
    if (b.type === 'video') return `<figure class="cr-figure"><video src="${url}" controls preload="metadata"></video></figure>`;
    return '';
}

function linksHTML(links) {
    const ls = (links || []).filter((l) => l && /^https?:/i.test(l.url || ''));
    if (!ls.length) return '';
    return '<div class="cr-links"><span class="cr-links-label">Links</span>' +
        ls.map((l) => `<a href="${escapeHtml(l.url)}" target="_blank" rel="noopener">${escapeHtml(l.text || l.url)}</a>`).join('') +
        '</div>';
}

function loadImage(url) {
    return new Promise((resolve) => {
        const im = new Image();
        im.onload = () => resolve(im);
        im.onerror = () => resolve(null);
        im.src = url;
    });
}

/** Put the slide itself on the board: the real page (PDF/image) or its text + figures. */
async function showSlide(payload, gen) {
    S.isImageSlide = false;
    if (payload.blank) {
        slideArea.innerHTML = '<div class="cr-empty">This page is blank in the original document. Press → (or ▼ on the right of the board) for the next slide.</div>';
        return;
    }
    if (payload.image) {
        S.isImageSlide = true;
        const img = await loadImage(payload.image);
        if (gen !== S.gen) return;
        slideArea.innerHTML = img
            ? `<figure class="cr-slide"><img class="cr-slide-img" src="${escapeHtml(payload.image)}" alt="Slide ${S.index + 1}" draggable="false"></figure>` + linksHTML(payload.links)
            : '<div class="cr-empty">Couldn’t open this slide. Press → for the next one.</div>';
        board.scrollTop = 0;
        if (img) loadSlideWords(S.index, gen);
        return;
    }
    const blocks = payload.blocks || [];
    if (!blocks.length) {
        slideArea.innerHTML = '<div class="cr-empty">This slide has no teachable content (it looks like a title, names or references). Press → to continue.</div>';
        return;
    }
    slideArea.innerHTML = '<div class="cr-sheet">' + blocks.map((b) =>
        b.type === 'text' ? `<div class="slide-text">${formatLecture(b.text)}</div>` : mediaHTML(b)
    ).join('') + linksHTML(payload.links) + '</div>';
    board.scrollTop = 0;
}

// ══════════════════════════════════════════════════════════════════════
//   PROGRESS, STATUS, BUSY
// ══════════════════════════════════════════════════════════════════════
function updateProgress() {
    const n = S.count;
    const k = S.active && n ? S.index + 1 : 0;
    const frac = n ? k / n : 0;
    $('slide-label').textContent = !S.active ? 'No lesson open' : n ? `Slide ${k} of ${n}` : 'Reading your slides…';
    $('slide-bar-fill').style.width = `${frac * 100}%`;
    $('pg-count').textContent = `${k}/${n}`;
    $('pg-pct').textContent = `${Math.round(frac * 100)}% Complete`;
    $('pg-bar-fill').style.width = `${frac * 100}%`;
    $('pg-arc').style.strokeDasharray = `${frac * RING} ${RING}`;
    $('pg-arc').style.opacity = frac > 0 ? 1 : 0;           // a round cap would draw a dot at 0%
    $('hs-slide-prev').classList.toggle('disabled', !S.active || k <= 1);
    $('hs-slide-next').classList.toggle('disabled', !S.active || !n || k >= n);
    updateEject();
    renderLadder();
}

/** The button under the ladder: take the slides and the chat off the board, leaving it empty.
 *  Nothing is deleted — the deck stays in Uploads and reopens where the student left off. */
function ejectBoard() {
    if (!S.active && !S.parts.length) return;
    const name = S.sessionId ? (S.filename || 'Your lesson').replace(/\.[^.]+$/, '') : '';
    if (typeof closeBoardCalc === 'function') closeBoardCalc();
    closeLesson();
    showToast(name ? `Board cleared — “${name}” is still in Uploads, ready where you left off` : 'Board cleared', 3800);
}
function updateEject() {
    $('hs-target').classList.toggle('disabled', !S.active && !S.parts.length);
}

/** The ladder on the board: one tick per slide (or per run of slides in a long deck); click to jump. */
const seen = new Set();
function renderLadder() {
    const box = $('ladder-ticks');
    box.textContent = '';
    if (!S.sessionId || !S.count) {
        for (let i = 0; i < 12; i++) box.appendChild(Object.assign(document.createElement('i'), { className: 'tick idle' }));
        return;
    }
    const n = Math.min(S.count, MAX_TICKS);
    for (let t = 0; t < n; t++) {
        const from = Math.floor((t * S.count) / n), to = Math.floor(((t + 1) * S.count) / n) - 1;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'tick';
        if (S.index >= from && S.index <= to) btn.classList.add('current');
        else if ([...Array(to - from + 1).keys()].some((d) => seen.has(from + d))) btn.classList.add('seen');
        btn.title = from === to ? `Slide ${from + 1}` : `Slides ${from + 1}–${to + 1}`;
        btn.addEventListener('click', () => { if (from !== S.index) teachSlide(from); });
        box.appendChild(btn);
    }
}

function setBusy(on) {
    S.busy = on;
    if (on) { S.stopped = false; closeSearch(); hideSelTools(); }
    searchInput.disabled = on;
    searchInput.placeholder = on ? 'Available in a moment…' : 'Find anything...';
    const send = $('chat-send');
    send.classList.toggle('busy', on);
    send.title = on ? 'Stop (Esc)' : 'Send';
}

function setStatus(kind, label) {
    $('status-dot').className = kind;
    $('status-text').textContent = label;
    $('status-text').title = label;
}

let wasOffline = false;
async function checkHealth() {
    try {
        const res = await fetch('/api/health', { cache: 'no-store' });
        const h = await res.json();
        if (typeof setCanSee === 'function') setCanSee(h.ok && h.sees);
        setThinkCan(!!(h.ok && h.online));
        // "Using ChatGPT plan · Manage usage" by the chat box; "Manage usage" first when the plan's limit is reached
        const planOn = !!(h.ok && h.online && h.provider === 'chatgpt');
        const limit = planOn && h.code === 'subscription_sharing_usage_limit_exceeded';
        $('plan-badge').hidden = !planOn;
        $('plan-badge').classList.toggle('limit', limit);
        $('plan-badge-text').textContent = limit ? 'Your ChatGPT plan has reached its limit for MrSOLIS' : 'Using ChatGPT plan';
        if (h.ok && h.brain_state === 'starting') {          // loading the brain: look again soon
            setStatus('starting', `Loading ${h.chat_model || 'brain'}…`);
            wasOffline = false;
            setTimeout(checkHealth, 2000);
            return;
        }
        if (h.ok) {
            setStatus('online', h.backend === 'brain' && h.chat_model ? `Online · ${h.chat_model}` : 'Online');
            // the online brain couldn't answer (no internet, no credit): say once that this computer's brain took over
            if (h.online && h.fallback && !checkHealth.saidFallback) {
                checkHealth.saidFallback = true;
                showToast(`${h.chat_model} couldn't answer${h.last_error ? ` (${h.last_error})` : ''} — the brain on this computer answered instead`, 6000);
            } else if (!h.fallback) checkHealth.saidFallback = false;
            wasOffline = false;
            return;
        }
        setStatus('offline', 'Offline');
        if (!wasOffline) showToast(h.error ? `AI engine offline: ${h.error}` : 'The AI engine is offline', 5000);
    } catch (e) {
        setStatus('offline', 'Offline');
    }
    wasOffline = true;
}

// ══════════════════════════════════════════════════════════════════════
//   UPLOAD → LESSON
// ══════════════════════════════════════════════════════════════════════
/** Open a file as a lesson: one picked or dropped (`file`), or one /find found on this computer (`path`). */
async function upload(file, path = null) {
    if (!file && !path) return;
    const name = file ? file.name : path.split(/[\\/]/).pop();
    if (typeof go === 'function') go('home');
    closeLesson();
    S.active = true;
    S.filename = name;
    const gen = ++S.gen;
    showBoard(true);
    const slow = /\.pptx?$/i.test(name) ? 'PowerPoint slides take 10–30 seconds to draw.' : 'scanned pages take a little longer.';
    slideArea.innerHTML = `<div class="cr-thinking"><i></i><i></i><i></i> <span>Reading ${escapeHtml(name)}… ${slow}</span></div>`;
    talkArea.innerHTML = '';
    updateProgress();

    let data;
    try {
        let res;
        if (path) {
            res = await fetch('/api/files/open', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }),
            });
        } else {
            const form = new FormData();
            form.append('file', file);
            res = await fetch('/api/upload', { method: 'POST', body: form });
        }
        data = await res.json();
        if (!res.ok || !data.session_id) throw new Error(data.detail || `Upload failed (${res.status})`);
    } catch (e) {
        if (gen !== S.gen) return;
        closeLesson();
        showToast(`Couldn’t open ${name}: ${e.message}`, 5000);
        return;
    }
    if (gen !== S.gen) return;
    if (data.warning) {
        closeLesson();
        showToast(data.warning, 6000);
        return;
    }
    if (data.existing) {
        // the same file is already in the library: carry on with that deck (its subject, notes, progress)
        await startLesson(data.session_id, data.filename || name, data.last_slide || 0, data.seen || []);
        showToast(`You already have “${(data.title || name).replace(/\.[^.]+$/, '')}” — picking up where you left off`, 4500);
        return;
    }
    await startLesson(data.session_id, data.filename || name);
}

async function startLesson(sessionId, filename, at = 0, seenBefore = []) {
    S.zoom = 1;                                       // a new deck starts fitted
    S.sessionId = sessionId;
    S.filename = filename || '';
    S.active = true;
    S.history = [];
    lessonUi();
    seenBefore.forEach((i) => seen.add(i));
    const gen = S.gen;
    try {
        const res = await fetch('/api/classroom/start', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `Could not start (${res.status})`);
        S.count = data.count || 1;
    } catch (e) {
        if (gen !== S.gen) return;
        closeLesson();
        showToast(e.message, 5000);
        return;
    }
    if (gen !== S.gen) return;
    const start = Math.max(0, Math.min(at, S.count - 1));
    showToast(start ? `Back to slide ${start + 1} of ${S.count}` : `${S.count} slide${S.count === 1 ? '' : 's'} ready — class is starting`);
    teachSlide(start);
}

async function teachSlide(index) {
    if (!S.sessionId || index < 0 || index >= S.count) return;
    if (S.abort) { try { S.abort.abort(); } catch (e) { /* already done */ } }
    const gen = ++S.gen;
    const ctrl = S.abort = new AbortController();
    S.index = index;
    seen.add(index);
    S.parts = [];
    S.streamPart = null;
    S.words = null;
    clearMarquee();
    showBoard(true);
    slideArea.innerHTML = '<div class="cr-thinking"><i></i><i></i><i></i> <span>Opening slide…</span></div>';
    setBusy(true);
    renderTalk();
    updateProgress();

    let lesson = null, gotSlide = false;
    try {
        await streamNDJSON('/api/classroom/teach_stream', { session_id: S.sessionId, slide_index: index }, (msg) => {
            if (gen !== S.gen) return;
            if (msg.slide) {
                gotSlide = true;
                showSlide(msg.slide, gen);
                if (msg.slide.examinable) {
                    lesson = S.streamPart = { kind: 'lesson', text: '' };
                    S.parts.push(lesson);
                    renderTalk();
                }
            } else if (msg.token && lesson) {
                lesson.text += msg.token;
                renderTalkSoon();
            } else if (msg.looking && lesson) {
                lesson.looking = true;
                renderTalk();
            } else if (msg.exact && lesson) {
                lesson.exact = msg.exact;                    // the slide's questions, as CUSTOM-Mx drafts to run
                renderTalkSoon();
            } else if (msg.next && lesson && lesson.text.trim()) {
                // "Next, we'll look at …" / the close after the last slide: read aloud, not saved to Notes
                lesson.transition = msg.next;
                lesson.text += '\n\n' + msg.next;
                renderTalkSoon();
            } else if (msg.error) {
                throw new Error(msg.error);
            }
        }, ctrl.signal);
    } catch (e) {
        if (gen !== S.gen) return;                       // moved to another slide
        if (!(e.name === 'AbortError' && S.stopped)) {
            if (!gotSlide) slideArea.innerHTML = '';
            S.parts.push({ kind: 'error', text: gotSlide ? `MrSOLIS stopped: ${e.message}` : `Couldn’t open slide ${index + 1}: ${e.message}` });
        }
    }
    if (gen !== S.gen) return;
    if (lesson && !lesson.text.trim()) S.parts = S.parts.filter((p) => p !== lesson);
    if (lesson && lesson.text.trim()) S.history.push({ role: 'assistant', content: plainText(lesson.text).slice(0, 400) });
    S.abort = null;
    setBusy(false);
    renderTalk();
    // warm the next page's render so moving on feels instant
    if (S.isImageSlide && index + 1 < S.count) {
        const im = new Image();
        im.onerror = () => {};
        im.src = `/api/classroom/slide_image/${S.sessionId}/${index + 1}?look=colour`;
    }
}

function nextSlide() {
    if (!S.sessionId) return;
    if (S.index >= S.count - 1) { showToast('That’s the last slide — ask anything to review'); return; }
    teachSlide(S.index + 1);
}
function prevSlide() {
    if (S.sessionId && S.index > 0) teachSlide(S.index - 1);
}

/** Leave the lesson and go back to the empty board. */
function closeLesson() {
    if (S.abort) { try { S.abort.abort(); } catch (e) { /* done */ } }
    S.gen++;
    Object.assign(S, {
        sessionId: null, filename: '', count: 0, index: 0, active: false, abort: null,
        parts: [], streamPart: null, history: [], words: null, isImageSlide: false,
    });
    seen.clear();
    setBusy(false);
    clearMarquee();
    slideArea.innerHTML = '';
    talkArea.innerHTML = '';
    showBoard(false);
    searchInput.value = '';
    closeSearch();
    updateProgress();
    lessonUi();
}

/** Stop whatever MrSOLIS is writing; keep what's already on the board. */
function stopWriting() {
    if (!S.busy || !S.abort) return;
    S.stopped = true;
    try { S.abort.abort(); } catch (e) { /* done */ }
    showToast('Stopped');
}

// ══════════════════════════════════════════════════════════════════════
//   CHAT · EXPLAIN · SOLVE
// ══════════════════════════════════════════════════════════════════════
async function ask(kind, text, image = null, video = null) {
    // video: { id, name } of the video attached in the chat box (mrsolis-video.js) — chat questions only
    text = (text || '').trim();
    if (!text && image) text = 'What is this? Explain it to me.';
    if (!text && video) text = 'Summarise this video for me.';
    if (!text) return;
    // with no slides open only chat works: MrSOLIS answers generally and asks for the material
    const free = !S.sessionId;
    if (free && kind !== 'chat') { showToast('Upload your slides first — drop a file on the board'); return; }
    if (S.busy) { showToast('MrSOLIS is still writing — press Esc to stop'); return; }
    hideSelTools();
    clearMarquee();
    try { window.getSelection().removeAllRanges(); } catch (e) { /* none */ }

    const gen = S.gen;
    const shown = text.length > 160 ? text.slice(0, 160) + '…' : text;
    S.parts.push({ kind: 'user', text: kind === 'chat' ? text : `${kind === 'solve' ? 'Solve' : 'Explain'}: “${shown}”`, image,
        video: video ? video.name : null });
    const reply = S.streamPart = { kind: 'assistant', text: '', free, looking: !!image || !!video, photo: !!image, watch: !!video,
        sqe: kind === 'solve' && looksMathsy(text) ? text : '' };
    S.parts.push(reply);
    const ctrl = S.abort = new AbortController();
    setBusy(true);
    renderTalk(true);

    const url = free ? '/api/chat_stream' : kind === 'chat' ? '/api/classroom/chat_stream' : '/api/classroom/explain';
    const vid = video ? video.id : null;
    const body = free ? { message: text, history: S.history.slice(-6), image, video: vid }
        : kind === 'chat'
        ? { session_id: S.sessionId, slide_index: S.index, message: text, history: S.history.slice(-6), image, video: vid }
        : { session_id: S.sessionId, slide_index: S.index, selection: text, mode: kind };
    try {
        await streamNDJSON(url, body, (msg) => {
            if (gen !== S.gen) return;
            if (msg.token) { reply.text += msg.token; renderTalkSoon(); }
            else if (msg.exact) { reply.exact = msg.exact; renderTalkSoon(); }      // a word problem: check, then Run
            else if (msg.looking && !reply.looking) { reply.looking = true; renderTalk(); }
            else if (msg.error) throw new Error(msg.error);
        }, ctrl.signal, THINK.on && THINK.can ? { 'x-mrsolis-think': '1' } : {});
    } catch (e) {
        if (gen !== S.gen) return;
        if (!(e.name === 'AbortError' && S.stopped) && !reply.text.trim()) {
            reply.kind = 'error';
            reply.text = `Sorry, I couldn’t answer that: ${e.message}`;
        }
    }
    if (gen !== S.gen) return;
    if (!reply.text.trim()) S.parts = S.parts.filter((p) => p !== reply);
    S.history.push({ role: 'user', content: (kind === 'chat' ? text : `${kind}: ${text}`) + (image ? ' [with a picture]' : '')
        + (video ? ` [about the video “${video.name}”]` : '') });
    if (reply.kind === 'assistant' && reply.text.trim()) S.history.push({ role: 'assistant', content: plainText(reply.text).slice(0, 400) });
    S.abort = null;
    setBusy(false);
    renderTalk();
}

// ── "/" commands typed in the chat box ───────────────────────────────
//   /calculator        the scientific calculator on the board (mrsolis-calc.js)
//   /find <name>       find a study file on this computer by name and open it on the board
//   /custom-mx <cmd>   CUSTOM-Mx's precise language: find … given …, solve, rearrange, convert (/mx for short)
const COMMANDS = [
    { name: 'calculator', alias: ['calc'], desc: 'A scientific calculator on the board', run: () => openBoardCalc() },
    { name: 'find', alias: ['open'], arg: 'file name', desc: 'Find your slides on this computer by name and open them', run: (q) => findAndOpen(q) },
    { name: 'custom-mx', alias: ['mx', 'cmx'], arg: 'command', desc: 'Talk to the maths engine directly — e.g. find power given V = 240 V, I = 5 A (or: help)', run: (q) => mxCommand(q) },
];
const cmdMenu = $('cmd-menu');
const FIND = { q: '', results: [], sel: 0, timer: null, seq: 0 };   // live /find results under the chat box

/** The command a "/word" means: an exact name or alias, else the only one it starts. */
function findCommand(word) {
    const w = word.toLowerCase();
    const exact = COMMANDS.find((c) => c.name === w || c.alias.includes(w));
    if (exact) return exact;
    const starts = COMMANDS.filter((c) => [c.name, ...c.alias].some((n) => n.startsWith(w)));
    return starts.length === 1 ? starts[0] : null;
}

const parseCommand = (text) => /^\/(\S*)(?:\s+([\s\S]*))?$/.exec(text);

/** Run "/command [argument]" from the chat box. Returns false if the text isn't a command. */
function runCommand(text) {
    const m = parseCommand(text);
    if (!m) return false;
    const cmd = m[1] ? findCommand(m[1]) : null;
    const arg = (m[2] || '').trim();
    if (!cmd) { hideCmdMenu(); chatInput.value = ''; showToast(`No command “/${m[1]}” — try /calculator, /find or /mx`, 3500); return true; }
    if (cmd.arg && !arg) { chatInput.value = `/${cmd.name} `; showCmdMenu(); chatInput.focus(); return true; }
    hideCmdMenu();
    chatInput.value = '';
    cmd.run(arg);
    return true;
}

// ── the menu above the chat box: matching commands, or live /find results ──
function showCmdMenu() {
    const m = parseCommand(chatInput.value);
    if (!m) { hideCmdMenu(); return; }
    const cmd = m[2] !== undefined ? findCommand(m[1]) : null;
    if (cmd && cmd.name === 'find') { liveFind((m[2] || '').trim()); return; }
    const w = m[1].toLowerCase();
    const list = m[2] === undefined ? COMMANDS.filter((c) => [c.name, ...c.alias].some((n) => n.startsWith(w))) : [];
    if (!list.length) { hideCmdMenu(); return; }
    cmdMenu.innerHTML = list.map((c, i) => `<button type="button" class="${i ? '' : 'sel'}" data-cmd="${c.name}">` +
        `<b>/${c.name}${c.arg ? ` <i>${c.arg}</i>` : ''}</b><span>${escapeHtml(c.desc)}</span></button>`).join('');
    cmdMenu.hidden = false;
}
function hideCmdMenu() {
    cmdMenu.hidden = true;
    clearTimeout(FIND.timer);
}

/** Search as the student types "/find EE 172". */
function liveFind(q) {
    clearTimeout(FIND.timer);
    if (!q) {
        cmdMenu.innerHTML = '<div class="cmd-note">Type part of a file name — e.g. <b>/find EE 172</b> — then press Enter to open it.</div>';
        cmdMenu.hidden = false;
        FIND.results = [];
        return;
    }
    FIND.timer = setTimeout(() => fetchFind(q), 160);
}

async function fetchFind(q) {
    const seq = ++FIND.seq;
    let data;
    try {
        data = await (await fetch(`/api/files/find?q=${encodeURIComponent(q)}`)).json();
    } catch (e) { return; }
    if (seq !== FIND.seq || !parseCommand(chatInput.value)) return;       // typed on, or left /find
    FIND.q = q;
    FIND.results = data.results || [];
    FIND.sel = 0;
    drawFind(data.building);
    if (data.building) FIND.timer = setTimeout(() => fetchFind(q), 900);  // still listing files: look again
}

const FILE_KIND = { pdf: 'PDF', pptx: 'PPT', ppt: 'PPT', docx: 'DOC', doc: 'DOC', txt: 'TXT' };
function drawFind(building) {
    if (!FIND.results.length) {
        cmdMenu.innerHTML = `<div class="cmd-note">${building ? 'Searching your files…'
            : `No PDF, PowerPoint, Word or text file named like “${escapeHtml(FIND.q)}” on this computer.`}</div>`;
        cmdMenu.hidden = false;
        return;
    }
    const day = (t) => new Date(t * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
    cmdMenu.innerHTML = FIND.results.map((f, i) => {
        const ext = (f.name.split('.').pop() || '').toLowerCase();
        return `<button type="button" class="find-item${i === FIND.sel ? ' sel' : ''}" data-find="${i}" title="${escapeHtml(f.path)}">` +
            `<em>${FILE_KIND[ext] || ext.toUpperCase()}</em><b>${escapeHtml(f.name)}</b>` +
            `<span>${escapeHtml(f.folder)} · ${day(f.modified)}</span></button>`;
    }).join('') + (building ? '<div class="cmd-note">Still searching the rest of your files…</div>' : '');
    cmdMenu.hidden = false;
    const sel = cmdMenu.querySelector('.sel');
    if (sel) sel.scrollIntoView({ block: 'nearest' });
}

function openFound(f) {
    hideCmdMenu();
    chatInput.value = '';
    upload(null, f.path);
}

/** Enter on "/find …": open the highlighted result (the best match unless the student moved). */
/** /CUSTOM-Mx: the engine runs the command exactly as written, or says why it won't — no brain involved
 *  (backend/mathengine/command.py). The answer lands in the chat like any other. */
async function mxCommand(text) {
    if (S.busy) { showToast('MrSOLIS is still writing — press Esc to stop'); return; }
    S.parts.push({ kind: 'user', text: `/CUSTOM-Mx ${text}` });
    const reply = { kind: 'assistant', text: '' };
    S.parts.push(reply);
    renderTalk(true);
    try {
        const r = await fetch('/api/mx', { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: text }) });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || `error ${r.status}`);
        reply.text = data.markdown;
    } catch (e) {
        reply.kind = 'error';
        reply.text = `CUSTOM-Mx couldn't run that: ${e.message}`;
    }
    renderTalk();
}

/** "Make it exact" (Σ): a question in everyday words → a /CUSTOM-Mx command the student checks before sending.
 *  Code copies every number; CUSTOM-Mx's rules, else the brain, only say what each one is (main.mx_draft). */
async function draftExact(text) {
    const r = await fetch('/api/mx/draft', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }) });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.reason || d.detail || `error ${r.status}`);
    const notes = [];
    if (d.check && d.check.length) notes.push(`Check: ${d.check.join('; ')}.`);
    if (d.left_out && d.left_out.length) notes.push(`Left out: ${d.left_out.join(', ')}.`);
    return { command: `/mx ${d.command}`,
             note: `${d.by === 'brain' ? 'The brain' : 'CUSTOM-Mx'} set this up — check each value means what your question says, then send it. ${notes.join(' ')}`.trim() };
}

const exactBtn = $('chat-exact');
exactBtn.addEventListener('click', async () => {
    const text = chatInput.value.trim();
    if (!text) { showToast('Type a maths or science question, then press Σ to make it exact', 4000); chatInput.focus(); return; }
    if (text.startsWith('/')) { showToast('That is already a command — press Enter to run it', 3500); return; }
    if (exactBtn.classList.contains('busy')) return;
    exactBtn.classList.add('busy');
    try {
        const d = await draftExact(text);
        chatInput.value = d.command;
        chatInput.focus();
        chatInput.setSelectionRange(d.command.length, d.command.length);
        showToast(d.note, 8000);
    } catch (e) {
        showToast(`Couldn't make that exact: ${e.message}`, 6000);
    }
    exactBtn.classList.remove('busy');
});

async function findAndOpen(q) {
    if (FIND.q === q && FIND.results.length) { openFound(FIND.results[FIND.sel] || FIND.results[0]); return; }
    let data;
    try { data = await (await fetch(`/api/files/find?q=${encodeURIComponent(q)}`)).json(); } catch (e) { data = { results: [] }; }
    const found = data.results || [];
    if (!found.length) { showToast(`No file named like “${q}” on this computer — try fewer words`, 4500); return; }
    openFound(found[0]);
}

chatInput.addEventListener('input', showCmdMenu);
chatInput.addEventListener('blur', () => setTimeout(hideCmdMenu, 150));
chatInput.addEventListener('keydown', (e) => {
    if (cmdMenu.hidden) return;
    if (e.key === 'Escape') { e.stopPropagation(); hideCmdMenu(); return; }
    if (FIND.results.length && cmdMenu.querySelector('.find-item') && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
        e.preventDefault();
        FIND.sel = (FIND.sel + (e.key === 'ArrowDown' ? 1 : -1) + FIND.results.length) % FIND.results.length;
        drawFind(false);
    }
    if (e.key === 'Tab') {                                      // complete the command's name
        const b = cmdMenu.querySelector('[data-cmd].sel');
        if (b) { e.preventDefault(); chatInput.value = `/${b.dataset.cmd} `; showCmdMenu(); }
    }
});
cmdMenu.addEventListener('mousedown', (e) => e.preventDefault());      // keep the chat box focused
cmdMenu.addEventListener('click', (e) => {
    const f = e.target.closest('[data-find]');
    if (f) { const item = FIND.results[+f.dataset.find]; if (item) openFound(item); return; }
    const b = e.target.closest('[data-cmd]');
    if (b) runCommand('/' + b.dataset.cmd);
});

function sendChat() {
    const typed = chatInput.value.trim();
    if (typed.startsWith('/') && runCommand(typed)) return;      // a command, not a question
    if (S.busy) { stopWriting(); return; }          // the send button doubles as Stop while writing
    if (typeof stopDictation === 'function') stopDictation();   // sending ends Transcription (mrsolis-voice.js)
    const text = chatInput.value.trim();
    const hasPic = typeof PIC !== 'undefined' && PIC.url;          // a picture in the chat box (mrsolis-brain.js)
    const video = typeof VID !== 'undefined' && VID.id ? { id: VID.id, name: VID.name } : null;   // stays attached (mrsolis-video.js)
    if (!text && !hasPic && !video) { chatInput.focus(); return; }
    chatInput.value = '';
    ask('chat', text, hasPic ? takePicture() : null, video);
}

// ── Highlight → Explain / Solve ──────────────────────────────────────
function hideSelTools() { selTools.hidden = true; }

/** Place the Explain/Solve toolbar above (or below) a viewport rect: beside the part of it you can see in its pane
 *  (the slide viewer, or MrSOLIS's panel on the right), and always on screen (a long highlight used to push it off). */
function showSelToolsAt(rect, pane = board) {
    // with no slides open only Save to Notes applies: Explain and Solve are about a slide
    $('cr-explain-btn').hidden = $('cr-solve-btn').hidden = !S.sessionId;
    selTools.hidden = false;
    const tw = selTools.offsetWidth || 150, th = selTools.offsetHeight || 38;
    const view = pane.getBoundingClientRect();
    const seenTop = Math.max(rect.top, view.top), seenBottom = Math.min(rect.bottom, view.bottom);
    const left = Math.max(8, Math.min(rect.left + rect.width / 2 - tw / 2, window.innerWidth - tw - 8));
    let top = seenTop - th - 8;
    if (top < 80) top = seenBottom + 8;
    top = Math.max(8, Math.min(top, window.innerHeight - th - 8));
    selTools.style.left = `${left}px`;
    selTools.style.top = `${top}px`;
}

function updateSelTools() {
    if (S.busy) { hideSelTools(); return; }   // with no slides open, a highlight can still be saved to Notes
    const sel = window.getSelection();
    const text = sel && sel.toString ? sel.toString().trim() : '';
    if (!text || text.length < 2 || !sel.rangeCount || sel.isCollapsed) {
        if (!S.marquee) hideSelTools();
        return;
    }
    const range = sel.getRangeAt(0);
    const where = range.commonAncestorContainer;          // the slide in the middle, or the talk on the right
    if (!board.contains(where) && !talkScroll.contains(where)) { if (!S.marquee) hideSelTools(); return; }
    clearMarquee();
    S.lastSelection = text;
    showSelToolsAt(range.getBoundingClientRect(), talkScroll.contains(where) ? talkScroll : board);
}

// Box-select on a PDF slide image: drag a rectangle, the words inside it become the selection.
async function loadSlideWords(idx, gen) {
    try {
        const res = await fetch(`/api/classroom/slide_text/${S.sessionId}/${idx}`);
        if (!res.ok) return;
        const data = await res.json();
        if (gen !== S.gen) return;
        const words = (data && data.words) || [];
        if (words.length) {
            S.words = words;
            const fig = slideArea.querySelector('.cr-slide');
            if (fig) fig.classList.add('selectable');
        }
    } catch (e) { /* box-select just isn't available on this slide */ }
}

function clearMarquee() {
    S.marquee = false;
    const old = board.querySelector('.cr-marquee');
    if (old) old.remove();
}

let mq = null;
function marqueeStart(e) {
    if (e.button !== 0) return;
    clearMarquee();
    hideSelTools();
    if (S.busy) return;
    const fig = e.target.closest && e.target.closest('.cr-slide');
    const img = fig && fig.querySelector('.cr-slide-img');
    if (!fig || !img || !S.words) return;
    e.preventDefault();
    mq = { fig, imgRect: img.getBoundingClientRect(), x0: e.clientX, y0: e.clientY, box: null };
    document.addEventListener('mousemove', marqueeMove);
    document.addEventListener('mouseup', marqueeEnd);
}
function marqueeMove(e) {
    if (!mq) return;
    const r = mq.imgRect;
    const x1 = Math.max(r.left, Math.min(e.clientX, r.right));
    const y1 = Math.max(r.top, Math.min(e.clientY, r.bottom));
    const w = Math.abs(x1 - mq.x0), h = Math.abs(y1 - mq.y0);
    if (!mq.box && (w > 3 || h > 3)) {
        mq.box = document.createElement('div');
        mq.box.className = 'cr-marquee';
        mq.fig.appendChild(mq.box);
    }
    if (mq.box) {
        const fr = mq.fig.getBoundingClientRect();
        Object.assign(mq.box.style, {
            left: `${Math.min(mq.x0, x1) - fr.left}px`, top: `${Math.min(mq.y0, y1) - fr.top}px`,
            width: `${w}px`, height: `${h}px`,
        });
    }
}
function marqueeEnd() {
    const m = mq;
    mq = null;
    document.removeEventListener('mousemove', marqueeMove);
    document.removeEventListener('mouseup', marqueeEnd);
    if (!m || !m.box) { clearMarquee(); return; }
    const r = m.imgRect, bx = m.box.getBoundingClientRect();
    const fx = (bx.left - r.left) / r.width, fy = (bx.top - r.top) / r.height;
    const fw = bx.width / r.width, fh = bx.height / r.height;
    // A word counts when the box covers a good part of it: half its width (or half the box, for a box drawn inside
    // one word) and part of its height (a thin drag along a line counts). It used to need the word's exact centre
    // inside the box — the PDF's word boxes are taller than the letters, so a snug box round one word missed it
    // until it was drawn bigger (the user, 2026-11-11).
    const text = (S.words || [])
        .filter((wd) => {
            const ix = Math.min(fx + fw, wd.x + wd.w) - Math.max(fx, wd.x);
            const iy = Math.min(fy + fh, wd.y + wd.h) - Math.max(fy, wd.y);
            return ix > 0 && iy > 0 && ix >= 0.5 * Math.min(wd.w, fw) && iy >= 0.4 * Math.min(wd.h, fh);
        })
        .map((wd) => wd.t).join(' ').replace(/\s+/g, ' ').trim();
    if (!text) { clearMarquee(); return; }
    S.lastSelection = text;
    S.marquee = true;
    ['tl', 'tr', 'bl', 'br'].forEach((p) => {
        const h = document.createElement('span');
        h.className = `cr-mq-h cr-mq-${p}`;
        m.box.appendChild(h);
    });
    showSelToolsAt(bx);
}

// ══════════════════════════════════════════════════════════════════════
//   FIND ANYTHING
// ══════════════════════════════════════════════════════════════════════
let searchTimer = null;
function closeSearch() { searchResults.classList.remove('open'); }
function showResults(html) { searchResults.innerHTML = html; searchResults.classList.add('open'); }

async function runSearch() {
    const q = searchInput.value.trim();
    if (!q) { closeSearch(); return; }
    if (!S.sessionId) { showResults('<div class="sr-empty">Open a lesson first — then find any word, idea or slide number in it.</div>'); return; }
    if (S.busy) { closeSearch(); return; }
    showResults('<div class="sr-empty">Searching…</div>');
    let results = [];
    try {
        const res = await fetch('/api/classroom/search', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: S.sessionId, query: q }),
        });
        results = ((await res.json()) || {}).results || [];
    } catch (e) { /* show "nothing matched" */ }
    if (searchInput.value.trim() !== q) return;          // the query changed while we waited
    if (!results.length) { showResults('<div class="sr-empty">Nothing matched that on your slides.</div>'); return; }
    searchResults.innerHTML = '';
    for (const r of results) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'sr-item';
        btn.innerHTML = `<span class="sr-title"><span class="sr-num">Slide ${r.index + 1}</span>${escapeHtml(r.title || '')}</span>` +
            (r.snippet ? `<span class="sr-snip">${escapeHtml(r.snippet)}</span>` : '');
        btn.addEventListener('click', () => {
            closeSearch();
            searchInput.value = '';
            teachSlide(r.index);
        });
        searchResults.appendChild(btn);
    }
    searchResults.classList.add('open');
}

// ══════════════════════════════════════════════════════════════════════
//   EVENT WIRING
// ══════════════════════════════════════════════════════════════════════
// Upload: Uploads in the sidebar or "+" by the search bar — or drop a file anywhere on the window.
const pickFile = () => fileInput.click();
$('hs-add').addEventListener('click', pickFile);
fileInput.addEventListener('change', () => {
    const f = fileInput.files && fileInput.files[0];
    fileInput.value = '';
    if (f) upload(f);
});

const veil = $('drop-veil');
let dragDepth = 0;
const hasFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes('Files');
window.addEventListener('dragenter', (e) => { if (hasFiles(e)) { dragDepth++; veil.hidden = false; } });
window.addEventListener('dragleave', (e) => { if (hasFiles(e) && --dragDepth <= 0) { dragDepth = 0; veil.hidden = true; } });
window.addEventListener('dragover', (e) => { if (hasFiles(e)) e.preventDefault(); });
window.addEventListener('drop', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth = 0;
    veil.hidden = true;
    const f = e.dataTransfer.files[0];
    if (!f) return;
    // a picture dropped on the chat box is a question about it, not a deck to study
    const bar = $('chatbar').getBoundingClientRect();
    const onChat = e.clientY >= bar.top - 40 && e.clientY <= bar.bottom + 20 && e.clientX >= bar.left && e.clientX <= bar.right;
    if (onChat && /^image\//.test(f.type) && typeof PIC !== 'undefined' && PIC.canSee) { attachPicture(f); return; }
    // a video or a recorded lecture, dropped anywhere, is something to ask about (mrsolis-video.js)
    if (typeof isVideoFile === 'function' && isVideoFile(f)) { attachVideo(f); return; }
    upload(f);
});

// Lesson controls
$('hs-slide-prev').addEventListener('click', prevSlide);
$('hs-slide-next').addEventListener('click', nextSlide);
$('hs-target').addEventListener('click', ejectBoard);
$('hs-home').addEventListener('click', () => { /* the classroom is Home */ });

// Chat
$('chat-send').addEventListener('click', sendChat);
chatInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); sendChat(); } });

// Explain / Solve
$('cr-explain-btn').addEventListener('click', () => ask('explain', S.lastSelection));
$('cr-solve-btn').addEventListener('click', () => ask('solve', S.lastSelection));
$('cr-note-btn').addEventListener('click', () => {
    const text = S.lastSelection;
    hideSelTools(); clearMarquee();
    try { window.getSelection().removeAllRanges(); } catch (e) { /* none */ }
    saveNote(text, 'highlight');
});
talkArea.addEventListener('click', (e) => {
    const ex = e.target.closest('[data-exact]');
    if (ex) {                                            // a CUSTOM-Mx draft: run it, or put it in the chat box to edit
        const [pi, di, act] = ex.dataset.exact.split(':');
        const d = ((S.parts[+pi] || {}).exact || [])[+di];
        if (!d) return;
        if (act === 'run') { mxCommand(d.command); return; }
        chatInput.value = `/mx ${d.command}`;
        chatInput.focus();
        chatInput.setSelectionRange(chatInput.value.length, chatInput.value.length);
        return;
    }
    const read = e.target.closest('[data-read]');
    if (read) { const part = S.parts[+read.dataset.read]; if (part) readAloud(part); return; }
    const sqe = e.target.closest('[data-sqe]');
    if (sqe) { const part = S.parts[+sqe.dataset.sqe]; if (part && part.sqe) openSqe(part.sqe); return; }
    const start = e.target.closest('[data-start]');
    if (start) {
        if (start.dataset.start === 'upload') pickFile();
        else if (typeof go === 'function') go('uploads');
        return;
    }
    const btn = e.target.closest('.part-save');
    if (!btn) return;
    const part = S.parts[+btn.dataset.part];
    if (part && !part.saved) saveNote(part.text, 'saved', part);
});
board.addEventListener('mousedown', marqueeStart);
board.addEventListener('scroll', () => { hideSelTools(); clearMarquee(); });
talkScroll.addEventListener('scroll', () => { if (!S.marquee) hideSelTools(); });
document.addEventListener('mouseup', (e) => {
    if (e.target.closest && e.target.closest('#cr-sel-tools')) return;
    setTimeout(updateSelTools, 0);
});

// Find anything
document.querySelector('.search > .ico').addEventListener('click', () => searchInput.focus());
searchInput.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 280); });
searchInput.addEventListener('focus', () => { if (searchInput.value.trim()) runSearch(); });
searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closeSearch(); searchInput.blur(); }
    if (e.key === 'Enter') { const first = searchResults.querySelector('.sr-item'); if (first) first.click(); }
});
document.addEventListener('mousedown', (e) => {
    if (!e.target.closest('#search-results') && e.target !== searchInput) closeSearch();
});

// Not built yet: clickable, but they only say so.
document.querySelectorAll('.soon').forEach((el) => {
    el.addEventListener('click', () => showToast(`${el.dataset.label || 'This'} — coming soon`));
});

// Window controls (the desktop window is frameless; preload.js exposes these)
const winApi = window.mrsolisWindow;
$('win-min').addEventListener('click', () => winApi && winApi.minimize());
$('win-max').addEventListener('click', () => winApi && winApi.toggleMaximize());
$('win-close').addEventListener('click', () => (winApi ? winApi.close() : window.close()));

/** The SQE window (MrSOLIS 2-AL, sqe.html): maths practice made from the student's own question, typed in for
 *  them when given. Quizzes → SQE and "Practise more like this". In a browser tab it opens as another tab. */
function openSqe(question = '') {
    const q = String(question || '').trim().slice(0, 2000);
    if (winApi && winApi.openSqe) { winApi.openSqe(q); return; }
    window.open(`/sqe${q ? `?q=${encodeURIComponent(q)}` : ''}`, 'mrsolis-sqe');
}
/** Worth offering practice for: a highlighted bit that looks like maths (numbers, an equation, calculus). */
const looksMathsy = (t) => /\d|[=^√∫]|\b(?:differentiate|integrate|solve|simplify|expand|factori[sz]e|evaluate|lim)\b/i.test(t || '');

// Focus mode: no sidebar — the slide and MrSOLIS's panel have the whole window
function setFocus(on) {
    document.body.classList.toggle('focus', on);
    $('hs-focus').classList.toggle('on', on);
    $('hs-focus').title = on ? 'Leave focus mode (Esc)' : 'Focus mode — hide the sidebar';
    if (on && typeof go === 'function') go('home');
}
$('hs-focus').addEventListener('click', () => setFocus(!document.body.classList.contains('focus')));

// Settings that change how the app looks (Settings page → /api/settings)
function applySettings(st) {
    if (!st) return;
    document.body.dataset.boardText = st.board_text || 'normal';
    document.body.classList.toggle('reduce-motion', !!st.reduce_motion);
}
fetch('/api/settings').then((r) => r.json()).then((d) => applySettings(d.settings)).catch(() => {});

// Keyboard: ← / → change slide, Esc stops writing / dismisses / leaves focus mode
document.addEventListener('keydown', (e) => {
    const typing = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA';
    if (e.key === 'Escape') {
        if (S.busy) stopWriting();
        else if (document.body.classList.contains('focus')) setFocus(false);
        hideSelTools(); clearMarquee(); closeSearch();
        return;
    }
    if (typing || document.getElementById('view-class').hidden) return;
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !zoomBar.hidden) {      // Ctrl +, Ctrl −, Ctrl 0: the slide's zoom
        if (e.key === '=' || e.key === '+') { e.preventDefault(); zoomStep(1); return; }
        if (e.key === '-' || e.key === '_') { e.preventDefault(); zoomStep(-1); return; }
        if (e.key === '0') { e.preventDefault(); setZoom(1); return; }
    }
    if (e.key === 'ArrowRight') nextSlide();
    if (e.key === 'ArrowLeft') prevSlide();
});

// ── Think (by the chat box) ──────────────────────────────────────────
// With an online brain, the student's questions (chat, Explain, Solve) can make it think before it answers: better
// answers to hard questions, a slightly longer wait. Not on this computer's brain: measured on Smarts, one question
// took 230 s instead of 13 s and came out wrong (2026-11-11, think_probe.py). Lessons, quizzes and Interactive mode
// never think. The choice is remembered on this computer.
const THINK = { on: false, can: false };
try { THINK.on = localStorage.getItem('mrsolis.think') === '1'; } catch (e) { /* storage blocked: off */ }
const THINK_ON = 'Thinking on — MrSOLIS thinks before it answers your questions: better answers to hard ones, but a slightly longer wait.';
const THINK_NEEDS = 'Thinking needs an online brain (Settings → Brain). The brain on this computer would take minutes to think and didn’t answer better in our tests.';

function drawThink() {
    const b = $('chat-think');
    b.classList.toggle('on', THINK.on && THINK.can);
    b.classList.toggle('unavailable', !THINK.can);
    b.setAttribute('aria-pressed', String(THINK.on && THINK.can));
    b.title = !THINK.can ? THINK_NEEDS
        : THINK.on ? 'Thinking is on: better answers to hard questions, a slightly longer wait. Click to answer quickly.'
        : 'Think: MrSOLIS thinks before it answers — better answers to hard questions, a slightly longer wait.';
}
function setThinkCan(can) {
    if (THINK.can === can) return;
    THINK.can = can;
    drawThink();
}
$('chat-think').addEventListener('click', () => {
    if (!THINK.can) { showToast(THINK_NEEDS, 6500); return; }
    THINK.on = !THINK.on;
    try { localStorage.setItem('mrsolis.think', THINK.on ? '1' : '0'); } catch (e) { /* not remembered */ }
    drawThink();
    showToast(THINK.on ? THINK_ON : 'Thinking off — quicker answers.', THINK.on ? 6000 : 3000);
});
drawThink();

// ── Start ────────────────────────────────────────────────────────────
updateProgress();
lessonUi();
checkHealth();
setInterval(checkHealth, 15000);
