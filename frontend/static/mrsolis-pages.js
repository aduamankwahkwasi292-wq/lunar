/* ═══════════════════════════════════════════════════════════════════
   MrSOLIS 3 Pages — everything in the sidebar besides the classroom.

     Uploads   the library: continue a deck where you left off, rename,
               file it under a subject, delete
     Subjects  group decks by course
     Notes     per deck: saved lesson parts and highlights, your own
               notes; export to Markdown
     Quizzes   questions built from the slides themselves, graded,
               with past scores
     History   what you studied, asked and scored, day by day
     Settings  lesson length, board text size, motion, engine, data
     Tools     step-by-step solver, study timer

   Uses the classroom's helpers from mrsolis-wire.js ($, S, showToast,
   formatLecture, streamNDJSON, startLesson, closeLesson, …).
   ═══════════════════════════════════════════════════════════════════ */
'use strict';

const pageView = $('view-page');
const classView = $('view-class');
let currentPage = 'home';
let LIB = { decks: [], subjects: [] };
const ACT = {};          // click handlers for [data-act] in the current page
const CHANGE = {};       // change handlers for [data-change]

// ── helpers ───────────────────────────────────────────────────────────
async function api(url, { method = 'GET', body } = {}) {
    const res = await fetch(url, {
        method,
        headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
        body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch (e) { /* no body */ }
    if (!res.ok) throw new Error((data && data.detail) || `Request failed (${res.status})`);
    return data;
}

const icon = (name) => `<svg class="ico"><use href="#i-${name}"/></svg>`;
const esc = escapeHtml;
const deckName = (d) => (d && (d.title || (d.filename || 'Untitled').replace(/\.[^.]+$/, ''))) || 'Untitled';
const deckExt = (d) => ((d && d.filename && d.filename.split('.').pop()) || 'DOC').slice(0, 4).toUpperCase();
const deckById = (id) => LIB.decks.find((d) => d.id === id);

function ago(ts) {
    if (!ts) return 'never';
    const s = Date.now() / 1000 - ts;
    if (s < 60) return 'just now';
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    if (s < 172800) return 'yesterday';
    return new Date(ts * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}
const clock = (ts) => new Date(ts * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });

async function loadLib() {
    LIB = await api('/api/library');
    return LIB;
}

function head(title, sub, actions = '') {
    return `<div class="page-head"><div><h1>${title}</h1><p>${sub}</p></div><div class="page-actions">${actions}</div></div>`;
}

function deckOptions(selected, { general = false, none = '' } = {}) {
    let html = none ? `<option value="">${none}</option>` : '';
    if (general) html += `<option value="general"${selected === 'general' ? ' selected' : ''}>General notes</option>`;
    html += LIB.decks.map((d) => `<option value="${d.id}"${d.id === selected ? ' selected' : ''}>${esc(deckName(d))}</option>`).join('');
    return html;
}

/** Destructive buttons ask twice: the first click arms them for 3 seconds. */
function armed(btn, label) {
    if (btn.classList.contains('armed')) return true;
    const before = btn.innerHTML;
    btn.classList.add('armed');
    btn.innerHTML = label;
    setTimeout(() => { btn.classList.remove('armed'); btn.innerHTML = before; }, 3000);
    return false;
}

function download(url) {
    const a = document.createElement('a');
    a.href = url; a.download = '';
    document.body.appendChild(a); a.click(); a.remove();
}

// ── navigation ────────────────────────────────────────────────────────
function go(page) {
    currentPage = page;
    document.querySelectorAll('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.page === page));
    $('hs-tools').classList.toggle('active', page === 'tools');
    const home = page === 'home';
    classView.hidden = !home;
    pageView.hidden = home;
    if (home) return;
    if (document.body.classList.contains('focus')) setFocus(false);
    hideSelTools(); closeSearch();
    render(page);
}

const PAGES = {};
async function render(page) {
    for (const k in ACT) delete ACT[k];
    for (const k in CHANGE) delete CHANGE[k];
    pageView.innerHTML = '<div class="page"><div class="empty">Loading…</div></div>';
    pageView.scrollTop = 0;
    try {
        await PAGES[page]();
    } catch (e) {
        pageView.innerHTML = `<div class="page"><div class="empty"><b>Something went wrong</b>${esc(e.message)}</div></div>`;
    }
}
const refresh = () => { if (currentPage !== 'home') render(currentPage); };

document.querySelectorAll('[data-page]').forEach((b) => b.addEventListener('click', () => go(b.dataset.page)));
pageView.addEventListener('click', (e) => {
    const el = e.target.closest('[data-act]');
    if (el && ACT[el.dataset.act]) ACT[el.dataset.act](el, e);
});
pageView.addEventListener('change', (e) => {
    const el = e.target.closest('[data-change]');
    if (el && CHANGE[el.dataset.change]) CHANGE[el.dataset.change](el, e);
});

/** Open a deck from the library in the classroom, at the slide the student reached. */
async function openDeck(id) {
    if (S.sessionId === id) { go('home'); return; }
    try {
        const d = await api(`/api/library/${id}/open`, { method: 'POST' });
        go('home');
        closeLesson();
        startLesson(d.session_id, d.filename, d.last_slide || 0, d.seen || []);
    } catch (e) {
        showToast(e.message, 4500);
    }
}

// ══════════════════════════════════════════════════════════════════════
//   UPLOADS — the library
// ══════════════════════════════════════════════════════════════════════
PAGES.uploads = async () => {
    await loadLib();
    const { decks, subjects } = LIB;
    const subjectName = (sid) => (subjects.find((s) => s.id === sid) || {}).name;
    let html = head('Uploads', 'Every deck you have uploaded. Pick up exactly where you left off.',
        `<button type="button" class="btn primary" data-act="upload">${icon('upload')}Upload slides</button>`);
    if (!decks.length) {
        html += `<div class="panel empty"><b>No decks yet</b>Upload a PDF, PowerPoint, Word file or photos of slides to start your first class.
                 <br><button type="button" class="btn primary" data-act="upload">${icon('upload')}Upload slides</button></div>`;
    } else {
        html += '<div class="stack">' + decks.map((d) => {
            const pct = d.count ? Math.round((d.seen / d.count) * 100) : 0;
            const subj = subjectName(d.subject_id);
            const meta = [`${d.count} slide${d.count === 1 ? '' : 's'}`, `${d.seen} studied`, `opened ${ago(d.opened)}`];
            if (!d.available) meta.push('file missing');
            const opts = `<option value="">No subject</option>` +
                subjects.map((s) => `<option value="${s.id}"${s.id === d.subject_id ? ' selected' : ''}>${esc(s.name)}</option>`).join('') +
                `<option value="__manage">Manage subjects…</option>`;
            return `<div class="deck${d.available ? '' : ' missing'}" data-deck="${d.id}">
                <div class="deck-icon">${esc(deckExt(d))}</div>
                <div style="min-width:0">
                    <div class="deck-name" title="${esc(d.filename || '')}">${esc(deckName(d))}${subj ? ` <span class="muted" style="font-weight:400">· ${esc(subj)}</span>` : ''}</div>
                    <div class="deck-meta">${meta.join(' · ')}</div>
                    <div class="bar"><i style="width:${pct}%"></i></div>
                </div>
                <div class="deck-actions">
                    <select class="select" data-change="subject" data-id="${d.id}" title="Subject">${opts}</select>
                    <button type="button" class="btn small ghost icon" data-act="rename" data-id="${d.id}" title="Rename">${icon('edit')}</button>
                    <button type="button" class="btn small ghost icon" data-act="delete" data-id="${d.id}" title="Delete">${icon('trash')}</button>
                    <button type="button" class="btn small primary" data-act="open" data-id="${d.id}"${d.available ? '' : ' disabled'}>${S.sessionId === d.id ? 'Back to class' : (d.seen ? 'Continue' : 'Start')}${icon('arrow')}</button>
                </div>
            </div>`;
        }).join('') + '</div>';
    }
    pageView.innerHTML = `<div class="page">${html}</div>`;

    ACT.upload = () => pickFile();
    ACT.open = (el) => openDeck(el.dataset.id);
    ACT.delete = async (el) => {
        if (!armed(el, 'Delete?')) return;
        try {
            await api(`/api/library/${el.dataset.id}`, { method: 'DELETE' });
            if (S.sessionId === el.dataset.id) closeLesson();
            showToast('Deck deleted');
            refresh();
        } catch (e) { showToast(e.message, 4000); }
    };
    ACT.rename = (el) => {
        const row = pageView.querySelector(`[data-deck="${el.dataset.id}"] .deck-name`);
        const d = deckById(el.dataset.id);
        row.innerHTML = `<input class="field rename" value="${esc(deckName(d))}" maxlength="120">`;
        const input = row.querySelector('input');
        input.focus(); input.select();
        const save = async () => {
            try { await api(`/api/library/${d.id}`, { method: 'PATCH', body: { title: input.value } }); } catch (e) { showToast(e.message); }
            refresh();
        };
        input.addEventListener('keydown', (e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') refresh(); });
        input.addEventListener('blur', save, { once: true });
    };
    CHANGE.subject = async (el) => {
        if (el.value === '__manage') { go('subjects'); return; }
        try {
            await api(`/api/library/${el.dataset.id}`, { method: 'PATCH', body: { subject_id: el.value || null } });
            showToast(el.value ? 'Filed under ' + el.selectedOptions[0].textContent : 'Removed from its subject');
            refresh();
        } catch (e) { showToast(e.message); }
    };
};

// ══════════════════════════════════════════════════════════════════════
//   SUBJECTS
// ══════════════════════════════════════════════════════════════════════
PAGES.subjects = async () => {
    await loadLib();
    const { decks, subjects } = LIB;
    const adder = `<input class="field" id="new-subject" placeholder="New subject, e.g. Physics 101" maxlength="60" style="width:260px">
                   <button type="button" class="btn primary" data-act="add">${icon('plus')}Add subject</button>`;
    let html = head('Subjects', 'Group your decks by course, so each subject keeps its own slides, notes and progress.', adder);
    const card = (s, list, isUnsorted) => {
        const slides = list.reduce((n, d) => n + d.count, 0), seen = list.reduce((n, d) => n + d.seen, 0);
        const pct = slides ? Math.round((seen / slides) * 100) : 0;
        const others = decks.filter((d) => !list.includes(d));
        return `<div class="panel subject-card" data-subject="${s ? s.id : ''}">
            <div class="subject-head">
                <h3>${esc(s ? s.name : 'Not in a subject')}</h3>
                ${isUnsorted ? '' : `<button type="button" class="btn small ghost icon" data-act="rename" data-id="${s.id}" title="Rename">${icon('edit')}</button>
                <button type="button" class="btn small ghost icon" data-act="remove" data-id="${s.id}" title="Delete subject (its decks stay in Uploads)">${icon('trash')}</button>`}
            </div>
            <div class="subject-stat">${list.length} DECK${list.length === 1 ? '' : 'S'} · ${pct}% STUDIED</div>
            <div class="bar"><i style="width:${pct}%"></i></div>
            <div class="stack" style="gap:6px">${list.map((d) => `<button type="button" class="mini-deck" data-act="open" data-id="${d.id}">
                ${icon('notes')}<span>${esc(deckName(d))}</span><small>${d.seen}/${d.count}</small></button>`).join('') ||
                '<div class="muted" style="font-size:13px;padding:4px 2px">No decks here yet.</div>'}</div>
            ${isUnsorted || !others.length ? '' : `<select class="select" data-change="adddeck" data-id="${s.id}"><option value="">+ Add a deck…</option>${others.map((d) => `<option value="${d.id}">${esc(deckName(d))}</option>`).join('')}</select>`}
        </div>`;
    };
    if (!subjects.length) {
        html += `<div class="panel empty"><b>No subjects yet</b>Create one above — then file decks under it here or from Uploads.</div>`;
    }
    html += '<div class="grid">' + subjects.map((s) => card(s, decks.filter((d) => d.subject_id === s.id))).join('');
    const unsorted = decks.filter((d) => !d.subject_id || !subjects.some((s) => s.id === d.subject_id));
    if (unsorted.length && subjects.length) html += card(null, unsorted, true);
    html += '</div>';
    pageView.innerHTML = `<div class="page">${html}</div>`;

    const input = $('new-subject');
    const add = async () => {
        const name = input.value.trim();
        if (!name) { input.focus(); return; }
        try { await api('/api/subjects', { method: 'POST', body: { name } }); showToast(`Subject “${name}” created`); refresh(); }
        catch (e) { showToast(e.message); }
    };
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') add(); });
    ACT.add = add;
    ACT.open = (el) => openDeck(el.dataset.id);
    ACT.remove = async (el) => {
        if (!armed(el, 'Delete?')) return;
        try { await api(`/api/subjects/${el.dataset.id}`, { method: 'DELETE' }); refresh(); } catch (e) { showToast(e.message); }
    };
    ACT.rename = (el) => {
        const h = pageView.querySelector(`[data-subject="${el.dataset.id}"] h3`);
        const s = LIB.subjects.find((x) => x.id === el.dataset.id);
        h.innerHTML = `<input class="field rename" value="${esc(s.name)}" maxlength="60">`;
        const f = h.querySelector('input');
        f.focus(); f.select();
        const save = async () => {
            try { await api(`/api/subjects/${s.id}`, { method: 'PATCH', body: { name: f.value || s.name } }); } catch (e) { showToast(e.message); }
            refresh();
        };
        f.addEventListener('keydown', (e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') refresh(); });
        f.addEventListener('blur', save, { once: true });
    };
    CHANGE.adddeck = async (el) => {
        if (!el.value) return;
        try { await api(`/api/library/${el.value}`, { method: 'PATCH', body: { subject_id: el.dataset.id } }); refresh(); }
        catch (e) { showToast(e.message); }
    };
};

// ══════════════════════════════════════════════════════════════════════
//   NOTES
// ══════════════════════════════════════════════════════════════════════
let notesDeck = null;
PAGES.notes = async () => {
    await loadLib();
    if (!notesDeck || (notesDeck !== 'general' && !deckById(notesDeck))) {
        notesDeck = (S.sessionId && deckById(S.sessionId)) ? S.sessionId : (LIB.decks[0] ? LIB.decks[0].id : 'general');
    }
    const general = notesDeck === 'general';
    const { notes } = await api('/api/notes' + (general ? '' : `?deck_id=${notesDeck}`));
    const mine = general ? notes.filter((n) => !n.deck_id) : notes;
    const label = { saved: 'Saved from a lesson', highlight: 'Highlight', mine: 'My note' };
    const actions = `<select class="select" data-change="deck" style="min-width:240px">${deckOptions(notesDeck, { general: true })}</select>
        ${general ? '' : `<button type="button" class="btn" data-act="export">${icon('download')}Export</button>`}`;
    let html = head('Notes', 'The lesson parts and highlights you saved, and your own notes.', actions);

    html += `<div class="section-title">Write a note</div>
        <div class="panel stack"><textarea class="textarea" id="note-text" placeholder="Anything worth remembering…"></textarea>
        <div class="row" style="justify-content:flex-end"><button type="button" class="btn primary" data-act="add">${icon('check')}Save note</button></div></div>`;

    html += `<div class="section-title">Saved (${mine.length})</div>`;
    html += mine.length
        ? '<div class="cols">' + mine.slice().reverse().map((n) => `<div class="silver note" data-note="${n.id}">
            <div class="note-tag">${label[n.kind] || 'Note'}${Number.isInteger(n.slide) ? ` · Slide ${n.slide + 1}` : ''} · ${ago(n.created)}</div>
            <div class="note-tools">
                <button type="button" data-act="edit" data-id="${n.id}" title="Edit">${icon('edit')}</button>
                <button type="button" data-act="del" data-id="${n.id}" title="Delete">${icon('trash')}</button>
            </div>
            <div class="note-body">${formatLecture(n.text)}</div></div>`).join('') + '</div>'
        : `<div class="panel empty" style="padding:26px"><b>Nothing saved yet</b>In class, hover over a lesson or answer and press <b style="display:inline;font-size:inherit">Save</b>, or highlight something and press the bookmark.</div>`;

    pageView.innerHTML = `<div class="page">${html}</div>`;

    CHANGE.deck = (el) => { notesDeck = el.value; refresh(); };
    ACT.export = () => download(`/api/notes/export/${notesDeck}`);
    ACT.add = async () => {
        const ta = $('note-text');
        if (!ta.value.trim()) { ta.focus(); return; }
        try {
            await api('/api/notes', { method: 'POST', body: { deck_id: general ? null : notesDeck, text: ta.value, kind: 'mine' } });
            showToast('Note saved');
            refresh();
        } catch (e) { showToast(e.message); }
    };
    ACT.del = async (el) => {
        if (!armed(el, 'Delete?')) return;               // a bare tick read as "nothing happened" (2026-10-31)
        try { await api(`/api/notes/${el.dataset.id}`, { method: 'DELETE' }); refresh(); } catch (e) { showToast(e.message); }
    };
    ACT.edit = (el) => {
        const card = pageView.querySelector(`[data-note="${el.dataset.id}"]`);
        const n = mine.find((x) => x.id === el.dataset.id);
        const body = card.querySelector('.note-body');
        body.innerHTML = `<textarea>${esc(n.text)}</textarea><div class="quiz-row"><button type="button" class="btn small primary" data-act="save-edit" data-id="${n.id}">Save</button><button type="button" class="btn small" data-act="cancel">Cancel</button></div>`;
        body.querySelector('textarea').focus();
    };
    ACT['save-edit'] = async (el) => {
        const text = pageView.querySelector(`[data-note="${el.dataset.id}"] textarea`).value;
        try { await api(`/api/notes/${el.dataset.id}`, { method: 'PATCH', body: { text } }); refresh(); } catch (e) { showToast(e.message); }
    };
    ACT.cancel = () => refresh();
};

// ══════════════════════════════════════════════════════════════════════
//   QUIZZES
// ══════════════════════════════════════════════════════════════════════
const QZ = { deck: null, count: 10, live: null, building: false };
// live = { id, deck, total, questions: [...], i, answers: {qid: {verdict, feedback, answer, work, given}}, done }
// MrSOLIS writes the questions while you answer, so they arrive one at a time (`fetchQuestion`).

PAGES.quizzes = async () => {
    await loadLib();
    if (QZ.live) { drawQuiz(); return; }
    if (!QZ.deck || !deckById(QZ.deck)) QZ.deck = (S.sessionId && deckById(S.sessionId)) ? S.sessionId : (LIB.decks[0] || {}).id || null;
    const { quizzes } = await api('/api/quizzes');
    let html = head('Quizzes', 'MrSOLIS writes questions from your slides and marks your answers against them. No question is ever asked twice.');
    if (!LIB.decks.length) {
        html += `<div class="panel empty"><b>No decks to quiz you on</b>Upload slides first — or practise maths with SQE below.<br><button type="button" class="btn primary" data-act="upload">${icon('upload')}Upload slides</button></div>`;
    } else {
        html += `<div class="panel">
            <div class="setting"><div><b>Deck</b><span>Which slides to test you on.</span></div>
                <select class="select" data-change="deck" style="min-width:280px">${deckOptions(QZ.deck)}</select></div>
            <div class="setting"><div><b>Questions</b><span>Spread across the whole deck.</span></div>
                <div class="seg">${[5, 10, 15].map((n) => `<button type="button" data-act="count" data-n="${n}" class="${QZ.count === n ? 'on' : ''}">${n}</button>`).join('')}</div></div>
            <div class="setting"><div><b>Ready?</b><span>Answer in your own words. The first question takes a few seconds to write; the rest are written while you answer.</span></div>
                <button type="button" class="btn primary" data-act="start"${QZ.building ? ' disabled' : ''}>${QZ.building ? 'Writing your first question…' : icon('play') + 'Start quiz'}</button></div>
        </div>`;
    }
    // MrSOLIS 2-AL (the SQE window): practice from the student's own maths question; it needs no slides
    html += `<div class="panel"><div class="setting last"><div><b>Practise maths</b><span><b style="display:inline;font-size:inherit">Highly
        recommended for maths quizzes:</b> the brains can get maths wrong, and SQE works it out exactly. Bring a maths question of your own.
        MrSOLIS 2-AL makes fresh versions of it with new numbers and works out every answer exactly, with the working.</span></div>
        <button type="button" class="btn primary" data-act="sqe" title="Open MrSOLIS 2-AL (powered by CUSTOM-SQE)">${icon('sigma')}SQE</button></div></div>`;
    html += `<div class="section-title">Past quizzes</div>`;
    html += quizzes.length
        ? '<div class="stack">' + quizzes.map((q) => `<div class="result-row">
            <div><div class="deck-name">${esc(deckName(deckById(q.deck_id)) || 'Deleted deck')}</div><div class="deck-meta">${ago(q.created)}</div></div>
            <span class="muted">${q.total ? Math.round((q.score / q.total) * 100) : 0}%</span><b>${q.score}/${q.total}</b></div>`).join('') + '</div>'
        : '<div class="panel empty" style="padding:24px">No quizzes taken yet.</div>';
    pageView.innerHTML = `<div class="page">${html}</div>`;

    ACT.upload = () => pickFile();
    CHANGE.deck = (el) => { QZ.deck = el.value; };
    ACT.count = (el) => { QZ.count = +el.dataset.n; refresh(); };
    ACT.start = startQuiz;
    ACT.sqe = () => openSqe();
};

async function startQuiz() {
    if (!QZ.deck || QZ.building) return;
    QZ.building = true;
    refresh();
    try {
        const d = await api('/api/quiz/start', { method: 'POST', body: { session_id: QZ.deck, count: QZ.count } });
        if (!d.quiz_id) { showToast(d.message || 'No questions could be made from these slides.', 5000); return; }
        QZ.live = { id: d.quiz_id, deck: QZ.deck, total: d.total, questions: [d.first], i: 0, answers: {}, done: null, next: null };
        fetchQuestion(QZ.live, 1);                       // start waiting for question 2 straight away
    } catch (e) {
        showToast(e.message, 4500);
    } finally {
        QZ.building = false;
        if (currentPage === 'quizzes') refresh();
    }
}

/** Question i of the live quiz: the server waits while MrSOLIS writes it. One request per question. */
function fetchQuestion(L, i) {
    L.fetching = L.fetching || {};
    if (!L.fetching[i]) {
        L.fetching[i] = api(`/api/quiz/${L.id}/question/${i}`).then((r) => {
            L.total = r.total;
            if (r.question) L.questions[i] = r.question;
            return r.question;
        }).catch(() => null);
    }
    return L.fetching[i];
}

// quiz text from the brain may hold LaTeX ("$x \mapsto -x$"): show it as readable maths, like lessons
const qtext = (t) => mathify(esc(t || ''));
const VERDICT = { correct: ['✓', 'Correct.'], partly: ['½', 'Partly right.'], wrong: ['✗', 'Not quite.'] };

function drawQuiz() {
    const L = QZ.live;
    const deck = deckById(L.deck);
    const total = Math.max(L.total || 0, L.questions.length, 1);
    let html = head('Quiz', esc(deckName(deck)), `<button type="button" class="btn ghost" data-act="quit">End quiz</button>`);
    if (L.done) {
        const r = L.done, pct = r.total ? r.score / r.total : 0, C = 2 * Math.PI * 52;
        html += `<div class="silver quiz-card">
            <div class="score">
                <div class="score-ring"><svg viewBox="0 0 120 120"><circle cx="60" cy="60" r="52" stroke="rgba(0,0,0,.12)"/>
                    <circle cx="60" cy="60" r="52" stroke="#000" stroke-linecap="round" stroke-dasharray="${pct * C} ${C}"/></svg><b>${r.score}/${r.total}</b></div>
                <div><h1 style="margin:0">${pct >= 0.8 ? 'Excellent work.' : pct >= 0.5 ? 'Good going.' : 'Keep at it.'}</h1>
                <p class="muted">${Math.round(pct * 100)}% correct. Review the ones you missed below — each is from the slide shown.</p></div>
            </div>
            <div class="review">${r.review.map((x) => {
                const v = x.verdict || (x.correct ? 'correct' : 'wrong');
                return `<div class="${v === 'correct' ? '' : v}"><b>${VERDICT[v][0]}</b> ${qtext(x.q)}
                    ${x.feedback && v !== 'correct' ? `<small class="fb">${qtext(x.feedback)}</small>` : ''}
                    <small>Answer: ${qtext(x.a)}${v === 'correct' ? '' : ` · You said: ${esc(x.given || '—')}`} · Slide ${x.slide + 1}</small></div>`;
            }).join('')}</div>
            <div class="quiz-row"><button type="button" class="btn primary" data-act="again">${icon('reset')}New quiz</button>
                <button type="button" class="btn" data-act="quit">Done</button></div>
        </div>`;
    } else if (!L.questions[L.i]) {                       // still being written
        html += `<div class="silver quiz-card">
            <div class="quiz-top"><span>Question ${L.i + 1} of ${total}</span></div>
            <div class="quiz-steps">${Array.from({ length: total }, (_, i) => `<i class="${i < L.i ? 'done' : i === L.i ? 'now' : ''}"></i>`).join('')}</div>
            <div class="cr-thinking"><i></i><i></i><i></i> <span>MrSOLIS is writing your next question…</span></div>
        </div>`;
    } else {
        const q = L.questions[L.i];
        const a = L.answers[q.id];
        const v = a && (a.verdict || (a.correct ? 'correct' : 'wrong'));
        html += `<div class="silver quiz-card">
            <div class="quiz-top"><span>Question ${L.i + 1} of ${total}</span><span>Slide ${q.slide + 1}</span></div>
            <div class="quiz-steps">${Array.from({ length: total }, (_, i) => `<i class="${i < L.i ? 'done' : i === L.i ? 'now' : ''}"></i>`).join('')}</div>
            <div class="quiz-q">${qtext(q.q)}</div>
            <textarea class="quiz-answer" id="quiz-answer" placeholder="${q.kind === 'numeric' ? 'Your answer (with units if you like)…' : 'Your answer, in your own words…'}"${a || L.marking ? ' disabled' : ''}>${a ? esc(a.given) : esc(L.typed || '')}</textarea>
            ${a ? `<div class="verdict ${v}"><b>${VERDICT[v][1]}</b>${a.feedback && v !== 'correct' ? ` ${qtext(a.feedback)}` : ''}
                <div class="verdict-answer">The answer: ${qtext(a.answer)}</div>${a.work ? `<pre>${esc(a.work)}</pre>` : ''}</div>` : ''}
            ${L.marking ? `<div class="cr-thinking"><i></i><i></i><i></i> <span>MrSOLIS is marking your answer…</span></div>` : ''}
            <div class="quiz-row">${a
                ? `<button type="button" class="btn primary" data-act="next">${L.i + 1 < total ? 'Next question' : 'See my score'}${icon('arrow')}</button>`
                : `<button type="button" class="btn primary" data-act="check"${L.marking ? ' disabled' : ''}>${icon('check')}Check</button>
                   <button type="button" class="btn" data-act="dunno"${L.marking ? ' disabled' : ''}>I don't know</button>`}</div>
        </div>`;
    }
    pageView.innerHTML = `<div class="page">${html}</div>`;
    const ta = $('quiz-answer');
    if (ta && !ta.disabled) {
        ta.focus();
        ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ACT.check(); } });
    }

    const answer = async (given) => {
        if (L.marking) return;
        L.marking = true;
        L.typed = given;
        drawQuiz();
        const q = L.questions[L.i];
        try {
            const r = await api('/api/quiz/answer', { method: 'POST', body: { quiz_id: L.id, qid: q.id, answer: given } });
            L.answers[q.id] = { ...r, given };
        } catch (e) { showToast(e.message); }
        L.marking = false;
        L.typed = '';
        if (QZ.live === L && currentPage === 'quizzes') drawQuiz();
    };
    ACT.check = () => { const v = ($('quiz-answer') || {}).value || ''; if (v.trim()) answer(v); else $('quiz-answer').focus(); };
    ACT.dunno = () => answer('');
    ACT.next = async () => {
        if (L.i + 1 < Math.max(L.total || 0, L.questions.length)) {
            L.i++;
            if (!L.questions[L.i]) {
                drawQuiz();
                await fetchQuestion(L, L.i);
                if (QZ.live !== L) return;
            }
            if (L.questions[L.i]) {
                fetchQuestion(L, L.i + 1);                // and start waiting for the one after
                if (currentPage === 'quizzes') drawQuiz();
                return;
            }
            L.i--;                                        // no more could be written: score what was asked
        }
        try { L.done = await api(`/api/quiz/${L.id}/finish`, { method: 'POST' }); } catch (e) { showToast(e.message); }
        if (currentPage === 'quizzes') drawQuiz();
    };
    ACT.again = () => { QZ.deck = L.deck; QZ.live = null; startQuiz(); };
    ACT.quit = async () => {
        if (!L.done) {
            const answered = Object.keys(L.answers).length;
            try { await api(answered ? `/api/quiz/${L.id}/finish` : `/api/quiz/${L.id}`, { method: answered ? 'POST' : 'DELETE' }); }
            catch (e) { /* ended */ }
        }
        QZ.live = null;
        refresh();
    };
}

// ══════════════════════════════════════════════════════════════════════
//   HISTORY
// ══════════════════════════════════════════════════════════════════════
PAGES.history = async () => {
    const [{ events }] = await Promise.all([api('/api/history'), loadLib()]);
    const name = (id) => (id && deckById(id) ? deckName(deckById(id)) : id ? 'a deleted deck' : '');
    // stats
    const days = [...new Set(events.map((e) => new Date(e.t * 1000).toDateString()))];
    let streak = 0;
    for (let d = new Date(); days.includes(d.toDateString()); d.setDate(d.getDate() - 1)) streak++;
    const quizzes = events.filter((e) => e.type === 'quiz');
    const avg = quizzes.length ? Math.round((quizzes.reduce((n, q) => n + (q.total ? q.score / q.total : 0), 0) / quizzes.length) * 100) : null;
    const plural = (n, one, many) => (n === 1 ? one : many);
    const nSlides = events.filter((e) => e.type === 'slide').length;
    const nAsked = events.filter((e) => ['ask', 'explain', 'solve'].includes(e.type)).length;
    const stats = [
        [nSlides, plural(nSlides, 'slide studied', 'slides studied')],
        [nAsked, plural(nAsked, 'question asked', 'questions asked')],
        [quizzes.length, (quizzes.length ? plural(quizzes.length, 'quiz', 'quizzes') + ` · ${avg}% average` : 'quizzes taken')],
        [streak, plural(streak, 'day in a row', 'days in a row')],
    ];
    let html = head('History', 'Everything you studied, asked and scored — kept on this computer only.',
        events.length ? `<button type="button" class="btn" data-act="clear">${icon('trash')}Clear history</button>` : '');
    html += '<div class="stats">' + stats.map(([n, l]) => `<div class="stat"><b>${n}</b><span>${l}</span></div>`).join('') + '</div>';

    if (!events.length) {
        html += '<div class="panel empty"><b>Nothing yet</b>Your study sessions will show up here.</div>';
    } else {
        // newest first, by day; runs of slides in the same deck fold into one line
        const byDay = new Map();
        for (const e of events) {
            const day = new Date(e.t * 1000).toDateString();
            if (!byDay.has(day)) byDay.set(day, []);
            const list = byDay.get(day), last = list[list.length - 1];
            if (e.type === 'open') continue;
            if (e.type === 'slide' && last && last.type === 'slide' && last.deck_id === e.deck_id) { last.slides.add(e.slide); continue; }
            if (e.type === 'note' && last && last.type === 'note' && last.deck_id === e.deck_id) { last.n++; continue; }
            list.push({ ...e, slides: new Set([e.slide]), n: 1 });
        }
        const today = new Date().toDateString(), yest = new Date(Date.now() - 86400000).toDateString();
        const ranges = (set) => {
            const xs = [...set].filter(Number.isInteger).sort((a, b) => a - b).map((x) => x + 1), out = [];
            for (let i = 0; i < xs.length; i++) {
                let j = i;
                while (j + 1 < xs.length && xs[j + 1] === xs[j] + 1) j++;
                out.push(j > i ? `${xs[i]}–${xs[j]}` : `${xs[i]}`);
                i = j;
            }
            return out.join(', ');
        };
        const line = (e) => {
            switch (e.type) {
                case 'slide': return ['book', `Studied ${esc(name(e.deck_id))}`, `Slide${e.slides.size === 1 ? '' : 's'} ${ranges(e.slides)}`];
                case 'ask': return ['send', `Asked: “${esc(e.text || '')}”`, e.deck_id ? esc(name(e.deck_id)) : 'Chat, no slides open'];
                case 'explain': return ['search', `Explain: “${esc(e.text || '')}”`, esc(name(e.deck_id))];
                case 'solve': return ['sigma', `Solve: “${esc(e.text || '')}”`, e.deck_id ? esc(name(e.deck_id)) : 'Tools → Solver'];
                case 'quiz': return ['quiz', `Quiz on ${esc(name(e.deck_id))}: ${e.score}/${e.total}`, `${e.total ? Math.round((e.score / e.total) * 100) : 0}% correct`];
                case 'practice': return ['sigma', `Practised maths: “${esc(e.text || '')}”: ${e.score}/${e.total}`,
                    `MrSOLIS 2-AL · ${e.total ? Math.round((e.score / e.total) * 100) : 0}% correct`];
                case 'upload': return ['upload', `Uploaded ${esc(name(e.deck_id))}`, ''];
                case 'note': return ['bookmark', `Saved ${e.n} note${e.n === 1 ? '' : 's'}`, esc(name(e.deck_id))];
                default: return ['clock', esc(e.type), ''];
            }
        };
        for (const [day, list] of byDay) {
            if (!list.length) continue;
            const label = day === today ? 'Today' : day === yest ? 'Yesterday' : new Date(day).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
            html += `<div class="day"><h3>${label}</h3>` + list.map((e) => {
                const [ic, text, sub] = line(e);
                return `<div class="event"><time>${clock(e.t)}</time>${icon(ic)}<div>${text}${sub ? `<small>${sub}</small>` : ''}</div></div>`;
            }).join('') + '</div>';
        }
    }
    pageView.innerHTML = `<div class="page">${html}</div>`;
    ACT.clear = async (el) => {
        if (!armed(el, 'Clear everything?')) return;
        try { await api('/api/history', { method: 'DELETE' }); showToast('History cleared'); refresh(); } catch (e) { showToast(e.message); }
    };
};

// ══════════════════════════════════════════════════════════════════════
//   HOW TO USE — a short guide to everything MrSOLIS does
// ══════════════════════════════════════════════════════════════════════
const GUIDE = [
    ['upload', 'Start a lesson', [
        'Drop a PDF, PowerPoint, Word file or photo of your notes in the middle of the screen — or press <b>+</b> at the top.',
        'Or type <b>/find</b> and part of the file name (e.g. <b>/find EE 172</b>) to open it from your computer.',
        'Each slide opens large in the middle and MrSOLIS teaches it in the panel on the right. Move with the arrows beside the slide, or the <b>←</b> <b>→</b> keys. <b>Interactive mode</b>, under the slide, teaches it out loud at a blackboard.',
        'Zoom the slide with <b>−</b> and <b>+</b> at its bottom-left, <b>Ctrl</b> + the mouse wheel (or a pinch), or <b>Ctrl +</b> / <b>Ctrl −</b>. Click the percentage (or <b>Ctrl 0</b>) to fit it again; scroll to move around a zoomed slide.',
        'Your place is saved. Reopen any deck from <b>Uploads</b>; group decks by course in <b>Subjects</b>.']],
    ['send', 'Ask anything', [
        'Type a question in the chat box at the bottom right. MrSOLIS answers about the slide you are on.',
        'Highlight part of a slide or a lesson, then tap <b>Explain</b> for a closer look or <b>Solve</b> for a worked answer.',
        '<b>Think</b>, by the chat box: with an online brain (Settings → Brain), MrSOLIS thinks before it answers your questions — better answers to hard ones, but a slightly longer wait.',
        'Got a lecture video or a recording? Drop it on the window (or press the picture button) and ask about it — MrSOLIS listens to what is said and looks at what is shown. It stays attached for more questions until you remove it.',
        'Stuck on a question in your notebook? Press the picture button (or paste a screenshot) and ask about it.',
        'No slides open? You can still chat — MrSOLIS answers and reminds you to upload your material.']],
    ['live', 'Talk with MrSOLIS', [
        '<b>Mic</b>: speak, and your words are typed into the chat box.',
        '<b>Interactive mode</b> (the button above the board, or type /class): MrSOLIS teaches your slides at a blackboard, writing and talking. Raise your hand ✋ (or press H) to ask a question; he stops, listens, answers, then carries on.',
        '<b>Read aloud</b> under any answer reads it to you.']],
    ['quiz', 'Test yourself', [
        'Open <b>Quizzes</b>, pick a deck and how many questions.',
        'MrSOLIS writes the questions from your slides while you answer, and marks each answer against the slide — telling you what you left out.',
        'A question is never asked twice, so every quiz is new. Past scores stay in Quizzes and History.',
        'For a <b>maths</b> quiz, use <b>SQE</b> instead — highly recommended. See <b>Practise maths (SQE)</b>.']],
    ['sigma', 'Practise maths (SQE)', [
        '<b>Highly recommended for maths quizzes.</b> MrSOLIS’s brains are great at explaining, but they are not good at '
            + 'maths and never will be: they can get a number or a step wrong and still sound sure. SQE doesn’t guess — '
            + 'CUSTOM-SQE works every answer out exactly, then checks it a second way.',
        'Open <b>Quizzes</b> and press <b>SQE</b>, or press <b>Practise more like this</b> under a solved problem.',
        'Type or paste <b>one maths question of your own</b> — from your notes, homework or a past paper — as it is written, '
            + 'with its numbers. For example <b>Differentiate f(x) = 3x² + 2x</b>, <b>Solve 2x + 3 = 11</b> or '
            + '<b>A lamp uses 200 W at 100 V. Calculate the current.</b>',
        'MrSOLIS 2-AL makes fresh versions of it with new numbers, and CUSTOM-SQE works out every answer exactly. Answer one '
            + 'at a time: pick from four or type your own, with a timer if you like. Press <b>Calculator</b> for a '
            + 'scientific calculator beside the question; press its answer to put it in your answer box.',
        'At the end you see your score, <b>your own question answered</b> and the working for every question. '
            + '<b>Again with new numbers</b> gives a new set.',
        'It knows calculus, equations and inequalities, algebra, indices and logs, numbers and percentages, sequences, '
            + 'statistics and probability, trigonometry, coordinates and vectors, matrices, complex numbers, and word problems '
            + 'in physics, money and areas or volumes.',
        'Tips: one question at a time; give the numbers with their units and say what to find. For a word problem, look at '
            + 'the <b>Read as</b> line — it shows how your question was understood. Not yet: trigonometric identities, and '
            + 'proofs other than “√p is irrational”.',
        'CUSTOM-SQE is great, but not perfect: now and then it may read a question wrongly or not manage one. '
            + 'Behemoth Group will keep updating it to make it better.'], 'Highly recommended'],
    ['notes', 'Keep what matters', [
        'Press <b>Save</b> on any lesson or answer, or the bookmark after highlighting, to keep it in <b>Notes</b>.',
        'Notes holds your saved parts and your own notes for each deck. Export them as a file.',
        '<b>Find anything</b> at the top finds any word or slide number in the lesson you have open.']],
    ['download', 'Summarise your slides', [
        'Open your slides, then type <b>/summarize</b> in the chat box and press Enter.',
        'MrSOLIS goes through the deck one slide at a time and writes a short summary of each: the key points, with '
            + 'every formula, definition and number as the slide gives it. Title, contents and “thank you” slides are skipped.',
        'While it works, the card in the chat shows what MrSOLIS is doing — <b>Working</b>, <b>Reading</b>, '
            + '<b>Explaining</b>, <b>Summarising</b>, <b>Breaking down</b>… — and which slide it is on. Press '
            + '<b>Stop</b> to end it.',
        'When it is done, your summary arrives in the chat as a <b>PDF</b>, one section per slide. Press '
            + '<b>Export</b> to save it, print it or share it.',
        'You can keep asking questions while it works; your questions are answered first. A long deck takes a while, '
            + 'longest on Smarts. Summarising the same deck again is instant, and one you stopped carries on from where it stopped.',
        'It needs a brain: download one in Settings → <b>Brain</b> first. MrSOLIS writes the summary from your slides, '
            + 'but check anything important against them.']],
    ['grid', 'Tools and commands', [
        '<b>Tools</b>: a scientific calculator, a step-by-step solver and a study timer.',
        'Type <b>/calculator</b> in the chat box to put the calculator on the board.',
        'Type <b>/summarize</b> for a PDF summary of the slides on the board — see <b>Summarise your slides</b>.',
        'Type <b>/mx</b> to give the maths engine an exact command — e.g. <b>/mx find power given V = 240 V, I = 5 A</b>. It does exactly what you write, or tells you why it can’t. <b>/mx help</b> lists what it understands.',
        'Or type your question normally and press <b>Σ</b> (or <b>Make it exact</b> in the Solver): it is turned into a /mx command for you to check — fix anything that isn’t what you meant, then send it.',
        'CUSTOM-Mx, the engine behind <b>/mx</b> and <b>Σ</b>, is great, but not perfect. Behemoth Group will keep updating it to make it better.',
        'The focus button at the top hides everything but the board. <b>Esc</b> stops MrSOLIS writing or leaves focus mode.',
        'The button under the slide arrows clears the board; the deck stays in Uploads.']],
    ['gear', 'Make it yours', [
        'Settings → <b>Brain</b>: choose <b>Speedy</b>, <b>Middler</b> or <b>Smarts</b>. Speedy is the fastest; Smarts is the smartest but slower and needs more memory; Middler sits between them.',
        'Change how long lessons are, the size of MrSOLIS\'s writing, and how fast MrSOLIS speaks.',
        'Under <b>Brain</b>, <b>Online brain</b> plugs in your own AI account with an API key — DeepSeek, OpenAI, Claude, Gemini, NVIDIA or any OpenAI-compatible server — for a stronger brain. Without internet, MrSOLIS uses its own.',
        'The <b>Look at slides</b> switch under the slide lets MrSOLIS read pictures and diagrams; turn it off for faster lessons on a slow computer.']],
];

PAGES.help = async () => {
    let html = head('How to use MrSOLIS', 'Your study tutor, on this computer. Nothing you upload, type or say leaves it.');
    html += '<div class="guide">' + GUIDE.map(([ic, title, steps, tag]) => `<div class="panel guide-card">
        <div class="tool-head">${icon(ic)}<h3>${title}</h3>${tag ? `<span class="bc-tag">${tag}</span>` : ''}</div>
        <ul>${steps.map((s) => `<li>${s}</li>`).join('')}</ul></div>`).join('') + '</div>';
    html += `<div class="panel guide-start"><div><b>Ready?</b><span>Drop your slides in the middle of the screen and class starts straight away.</span></div>
        <div class="row"><button type="button" class="btn primary" data-act="upload">${icon('upload')}Upload slides</button>
        <button type="button" class="btn" data-act="home">${icon('home')}Go to the board</button></div></div>`;
    pageView.innerHTML = `<div class="page">${html}</div>`;
    ACT.upload = () => pickFile();
    ACT.home = () => go('home');
};

// ══════════════════════════════════════════════════════════════════════
//   SETTINGS
// ══════════════════════════════════════════════════════════════════════
PAGES.settings = async () => {
    const { settings: st, engine } = await api('/api/settings');
    const seg = (key, opts) => `<div class="seg">${opts.map(([v, l]) => `<button type="button" data-act="set" data-key="${key}" data-val="${v}" class="${st[key] === v ? 'on' : ''}">${l}</button>`).join('')}</div>`;
    const engineName = engine.online ? `Online brain — your own ${engine.chat_model} account (the brain on this computer is the backup)`
        : engine.backend === 'brain' ? 'Built-in (llama.cpp server, this computer’s processor)'
        : engine.backend === 'llama' ? 'Built-in (llama.cpp)' : engine.backend === 'ollama' ? 'Ollama (development)' : engine.backend;
    let html = head('Settings', 'How MrSOLIS teaches and looks. Everything stays on this computer.');
    html += `<div class="section-title">Lessons</div><div class="panel">
        <div class="setting"><div><b>Lesson length</b><span>How much MrSOLIS writes under each slide.</span></div>
            ${seg('lesson_length', [['short', 'Short'], ['standard', 'Standard'], ['detailed', 'Detailed']])}</div>
    </div>`;
    html += `<div class="section-title">Board</div><div class="panel">
        <div class="setting"><div><b>Text size</b><span>The size of MrSOLIS's lessons and answers on the right, and of slides that are only words.</span></div>
            ${seg('board_text', [['normal', 'Normal'], ['large', 'Large'], ['xlarge', 'Extra large']])}</div>
        <div class="setting"><div><b>Reduce motion</b><span>Turn off animations and glows that move.</span></div>
            <button type="button" class="switch${st.reduce_motion ? ' on' : ''}" data-act="motion" aria-pressed="${!!st.reduce_motion}"></button></div>
    </div>`;
    html += `<div class="section-title">Voice</div><div class="panel">
        <div class="setting"><div><b>Speaking speed</b><span>How fast MrSOLIS talks when he reads aloud and in Interactive mode.</span></div>
            <div class="row">${seg('voice_speed', [['slow', 'Slower'], ['normal', 'Normal'], ['fast', 'Faster']])}
            <button type="button" class="btn" data-act="preview"${VOICE.speak ? '' : ' disabled'}>${icon('speaker')}Preview</button></div></div>
        <div class="setting"><div><b>Two ways to talk</b><span><b style="display:inline;font-size:inherit">Mic</b> types what you say into the chat box. <b style="display:inline;font-size:inherit">Interactive mode</b> is a spoken class at a blackboard — raise your hand ✋ to ask, and MrSOLIS stops to listen.</span></div></div>
        <div class="setting"><div><b>On this computer</b><span>Hearing: NVIDIA Parakeet (CC BY 4.0) · Voice: Supertonic 2 by Supertone (OpenRAIL-M). ${VOICE.hear && VOICE.speak ? 'Installed — nothing you say leaves this computer.' : 'Not installed yet.'}</span></div></div>
    </div>`;
    // the brain: the model MrSOLIS thinks and looks with (cards from mrsolis-brain.js)
    html += `<div class="section-title" id="brain">Brain</div><div class="panel">
        <p class="bc-intro">${BRAIN_INTRO}</p>
        <div id="brain-cards"></div>
        <div id="online-brain"></div>
    </div>`;
    html += `<div class="section-title">AI engine</div><div class="panel"><dl class="kv">
        <dt>Status</dt><dd>${engine.ok ? (engine.brain_state === 'starting' ? 'Loading the brain…' : 'Online') : 'Offline' + (engine.error ? ' — ' + esc(engine.error) : '')}</dd>
        <dt>Runs on</dt><dd>${esc(engineName || '—')}</dd>
        <dt>Brain</dt><dd>${engine.online ? esc(engine.model || engine.chat_model) : engine.backend === 'brain' ? esc(engine.chat_model || '—') : 'Classic (reads text only)'}</dd>
        <dt>Search model</dt><dd>${esc(engine.embed_model || '—')}</dd>
    </dl></div>`;
    html += `<div class="section-title">Your data</div><div class="panel">
        <div class="setting"><div><b>Study history</b><span>Clears the History page and past quiz scores. Your decks and notes stay.</span></div>
            <button type="button" class="btn" data-act="clear">${icon('trash')}Clear history</button></div>
    </div>`;
    html += `<div class="section-title">About</div><div class="panel"><dl class="kv">
        <dt>App</dt><dd>MrSOLIS 3.1 — Study Oriented Local Intelligence System</dd>
        <dt>Engines</dt><dd class="words"><b>CUSTOM-Mx</b> works the maths exactly · <b>CUSTOM-SQE</b> makes maths practice from your own questions · <b>CUSTOM-Kx</b> keeps the brain light on this computer’s memory</dd>
        <dt>Privacy</dt><dd>Offline-first: with the brain on this computer, your slides and questions never leave it. Only if you turn on an online brain (your own AI account) do they go to that company.</dd>
    </dl>
    <div class="row about-row"><button type="button" class="btn" data-act="terms">${icon('notes')}Terms of use</button>
        <button type="button" class="btn" data-act="licences">${icon('book')}Licences &amp; credits</button></div></div>`;
    pageView.innerHTML = `<div class="page">${html}</div>`;
    mountBrainCards($('brain-cards'));
    mountOnlineBrain($('online-brain'));

    const save = async (changes) => {
        try {
            const r = await api('/api/settings', { method: 'PUT', body: changes });
            applySettings(r.settings);
            refresh();
        } catch (e) { showToast(e.message); }
    };
    ACT.set = (el) => save({ [el.dataset.key]: el.dataset.val });
    ACT.motion = () => save({ reduce_motion: !st.reduce_motion });
    ACT.preview = () => previewVoice();
    ACT.licences = () => go('licences');
    ACT.terms = () => go('terms');
    ACT.clear = async (el) => {
        if (!armed(el, 'Clear history?')) return;
        try { await api('/api/history', { method: 'DELETE' }); showToast('History cleared'); } catch (e) { showToast(e.message); }
    };
};

// ══════════════════════════════════════════════════════════════════════
//   LICENCES & CREDITS (Settings → About) — what MrSOLIS is built with
// ══════════════════════════════════════════════════════════════════════
// The licence texts live in static/licences/. The brains are described, never named (the user's rule).
// Web addresses are plain text: a link would take the app window away from MrSOLIS.
const ENGINES = [
    ['CUSTOM-Mx', 'MrSOLIS’s maths engine. It works calculations out exactly instead of letting the brain guess. '
        + 'A word problem becomes a command you can check before it runs — type <b>/mx</b>, or press <b>Σ</b>. '
        + 'It is great, but not perfect: Behemoth Group will keep updating it to make it better.'],
    ['CUSTOM-SQE', 'MrSOLIS’s similar-questions engine, built from MrSOLIS 2-AL. You bring one maths question; it makes fresh '
        + 'versions with new numbers in your own words, picks numbers so the answers come out as clean as yours, and works '
        + 'every answer out exactly — then checks it a second way. Open it from Quizzes → SQE. '
        + 'It is great, but not perfect: Behemoth Group will keep updating it to make it better.'],
    ['CUSTOM-Kx', 'MrSOLIS’s memory engine. It keeps the brain light on this computer: memory no longer piles up '
        + 'through a long study session, the brain is never held twice, the brain’s picture reader is rebuilt at '
        + '8-bit on this computer the first time it starts (it reads slides the same, in about half the memory), '
        + 'and slide pictures are sized so MrSOLIS reads them sooner. Measured on a laptop: Middler needs about 30% '
        + 'less memory once loaded, and about 45% less after ten slides. Smarts keeps its hearing on disk until '
        + 'MrSOLIS needs it, which saves about 320 MB.'],
];
const CREDITS = [
    ['The brains (Speedy, Middler, Smarts)', 'The models MrSOLIS thinks, writes and looks with. Speedy was trained further for MrSOLIS.',
        'Apache License 2.0, from their original authors', ['apache-2.0.txt']],
    ['llama.cpp', 'The AI engine that runs the brain on this computer.', 'MIT · LLVM OpenMP runtime: Apache 2.0 with LLVM exceptions',
        ['llama.cpp-mit.txt', 'llvm-openmp.txt'], 'github.com/ggml-org/llama.cpp'],
    ['FFmpeg', 'Takes the sound and still frames out of videos you attach.', 'GNU LGPL 3.0 or later',
        ['lgpl-3.0.txt', 'gpl-3.0.txt'], 'FFmpeg n9.0.2, built without GPL or non-free parts (BtbN FFmpeg-Builds). '
        + 'Its source: github.com/FFmpeg/FFmpeg and ffmpeg.org. You may swap in your own FFmpeg build (runtime/ffmpeg). '
        + 'FFmpeg is a trademark of Fabrice Bellard.'],
    ['NVIDIA Parakeet TDT 110M', 'Hearing: turns speech into text — the mic, Interactive mode and videos.', 'Creative Commons Attribution 4.0 (CC BY 4.0)',
        [], 'By NVIDIA, prepared for sherpa-onnx by the k2-fsa project. Licence: creativecommons.org/licenses/by/4.0'],
    ['Supertonic 2', 'MrSOLIS’s speaking voice.', 'BigScience OpenRAIL-M (the voice model) · MIT (its code)',
        ['supertonic-model-openrail-m.txt', 'supertonic-code-mit.txt'], 'By Supertone Inc. The model licence forbids harmful uses (its Attachment A).'],
    ['Silero VAD', 'Tells when you start and stop talking.', 'MIT', ['silero-vad-mit.txt'], 'By the Silero Team.'],
    ['sherpa-onnx', 'Runs the hearing and speaking models.', 'Apache License 2.0', ['apache-2.0.txt'], 'By the k2-fsa project.'],
    ['The blackboard’s handwriting', 'The letters and signs MrSOLIS writes with in Interactive mode.',
        'SIL Open Font License 1.1 · the Hershey fonts: free to use with credit', ['board-handwriting-ofl.txt'],
        'EMS Tech by Sheldon B. Michaels, a single-line font made from Architects Daughter by Kimberly Geswein '
        + '(MrSOLIS draws a few characters again and adds maths signs). Greek letters: the Hershey fonts, created by '
        + 'Dr. A. V. Hershey at the U.S. National Bureau of Standards.'],
    ['OpenStax', 'Formulas and textbook problems that CUSTOM-Mx uses.', 'Creative Commons Attribution 4.0 (CC BY 4.0)', [],
        'From the Key Equations and exercises of OpenStax textbooks (OpenStax, Rice University, openstax.org). Licence: creativecommons.org/licenses/by/4.0'],
    ['PDFium (through pypdfium2)', 'The engine under MrSOLIS’s own PDF layer: reads and draws the pages of your PDFs and slides.',
        'BSD-3-Clause and Apache 2.0, with the licences of its parts', ['pdfium-and-parts.txt'],
        'PDFium by Google and the PDFium authors (the PDF engine in Chrome); pypdfium2 by its authors. Its parts include '
        + 'FreeType (portions © The FreeType Project, freetype.org), libjpeg-turbo (based in part on the work of the '
        + 'Independent JPEG Group), OpenJPEG, libpng, libtiff, zlib, Little CMS, ICU and Abseil.'],
    ['RapidOCR and ONNX Runtime', 'Reads the words in pictures and scanned pages.', 'Apache License 2.0 · MIT', ['apache-2.0.txt']],
    ['nomic-embed-text', 'The search model behind “Find anything”.', 'Apache License 2.0', ['apache-2.0.txt'], 'By Nomic AI.'],
    ['Electron and Chromium', 'The app window.', 'MIT, and the licences of Chromium’s parts', [],
        'Their full notices are in the app’s folder: LICENSE and LICENSES.chromium.html.'],
    ['Python and its libraries', 'The engine room behind the window.', 'Permissive licences', [],
        'Python (PSF licence) · FastAPI, Pydantic, python-pptx, python-docx, openpyxl (MIT) · Uvicorn, HTTPX, NumPy, SymPy, '
        + 'mpmath, lxml, PyPDF2 (BSD) · Pillow (MIT-CMU) · python-multipart, Requests (Apache 2.0) · for the online brain: '
        + 'the Anthropic Python SDK, jiter, truststore, docstring-parser (MIT), httpx2, httpcore2 (BSD).'],
];

// The Terms of Use (built from TERMS-OF-USE.md by scripts/make_terms.py; the installer shows the same text).
PAGES.terms = async () => {
    const res = await fetch('/static/licences/terms-of-use.html', { cache: 'no-cache' });
    if (!res.ok) throw new Error('The terms of use are missing from this copy of MrSOLIS');
    pageView.innerHTML = `<div class="page"><div class="panel terms">${await res.text()}</div>
        <div class="row"><button type="button" class="btn" data-act="back">${icon('gear')}Back to Settings</button></div></div>`;
    ACT.back = () => go('settings');
};

PAGES.licences = async () => {
    let html = head('Licences & credits', 'MrSOLIS 3.1 is built with open software and open models, all running on this computer. Thank you to everyone who made them.');
    html += '<div class="section-title">Made for MrSOLIS</div><div class="guide">' + ENGINES.map(([name, text]) =>
        `<div class="panel guide-card"><div class="tool-head">${icon('bulb')}<h3>${name}</h3></div><p class="lic-what">${text}</p></div>`).join('') + '</div>'
        + '<p class="lic-note">The CUSTOM engines and their names belong to Behemoth Group. Please don’t use the names anywhere '
        + 'else (Terms of use, section 2.6).</p>';
    html += '<div class="section-title">Built with</div>' + CREDITS.map(([name, what, lic, files, note], i) =>
        `<div class="panel lic-item"><div class="lic-head"><div><b>${esc(name)}</b><span>${esc(what)}</span></div><em>${esc(lic)}</em></div>`
        + (note ? `<p class="lic-note">${esc(note)}</p>` : '')
        + (files.length ? `<div class="row">${files.map((f) => `<button type="button" class="btn" data-act="lic" data-file="${f}" data-i="${i}">${icon('book')}${
            esc(f.replace(/\.txt$/, '').replace(/-/g, ' '))}</button>`).join('')}</div><pre class="lic-text" id="lic-${i}" hidden></pre>` : '')
        + '</div>').join('');
    html += `<div class="row"><button type="button" class="btn" data-act="back">${icon('gear')}Back to Settings</button></div>`;
    pageView.innerHTML = `<div class="page">${html}</div>`;
    ACT.back = () => go('settings');
    ACT.lic = async (el) => {
        const box = $(`lic-${el.dataset.i}`);
        if (!box.hidden && box.dataset.file === el.dataset.file) { box.hidden = true; return; }    // a second press closes it
        try {
            const res = await fetch(`/static/licences/${el.dataset.file}`);
            if (!res.ok) throw new Error('That licence text is missing');
            box.textContent = await res.text();
            box.dataset.file = el.dataset.file;
            box.hidden = false;
        } catch (e) { showToast(e.message); }
    };
};

// ══════════════════════════════════════════════════════════════════════
//   TOOLS — calculator (mrsolis-calc.js), solver, study timer
// ══════════════════════════════════════════════════════════════════════
const SOLVER = { problem: '', verified: '', engine: '', text: '', busy: false, savedTo: '', exact: null };   // exact: CUSTOM-Mx's draft for a word problem   // savedTo: where this solution was saved
PAGES.tools = async () => {
    await loadLib();
    let html = head('Tools', 'A scientific calculator, a step-by-step solver and a study timer.');
    html += `<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(380px,1fr))">
        <div class="panel calc-panel" id="calc-panel" style="grid-row:span 2"></div>
        <div class="panel" style="grid-row:span 2">
            <div class="tool-head">${icon('sigma')}<h3>Solver</h3></div>
            <textarea class="textarea" id="solve-in" placeholder="Type a maths or science problem — e.g.  2x + 5 = 17   or   A 4 kg cart accelerates at 3 m/s². What net force acts on it?">${esc(SOLVER.problem)}</textarea>
            <div class="row" style="margin-top:10px;justify-content:flex-end">
                ${SOLVER.text && !SOLVER.busy ? (SOLVER.savedTo
                    ? `<button type="button" class="btn armed" data-act="open-notes" title="Open Notes">${icon('check')}Saved to ${esc(SOLVER.savedTo)}</button>`
                    : `<button type="button" class="btn" data-act="solve-save">${icon('bookmark')}Save to notes</button>`) : ''}
                ${SOLVER.text && !SOLVER.busy && looksMathsy(SOLVER.problem) && !/^\/(custom-?mx|mx)\b/i.test(SOLVER.problem)
                    ? `<button type="button" class="btn" data-act="solve-sqe" title="Fresh versions of this problem in MrSOLIS 2-AL">${icon('quiz')}Practise more like this</button>` : ''}
                <button type="button" class="btn" data-act="solve-exact" title="Turn the problem into a CUSTOM-Mx command you can check before solving"${SOLVER.busy ? ' disabled' : ''}>${icon('sigma')}Make it exact</button>
                <button type="button" class="btn primary" data-act="solve"${SOLVER.busy ? ' disabled' : ''}>${SOLVER.busy ? 'Solving…' : icon('check') + 'Solve'}</button>
            </div>
            <div class="silver solve-out" id="solve-out"${SOLVER.text || SOLVER.busy ? '' : ' hidden'}></div>
        </div>
        <div class="panel">
            <div class="tool-head">${icon('timer')}<h3>Study timer</h3></div>
            <div class="timer">
                <div class="seg">${Object.entries(TIMER_MODES).map(([k, [, l]]) => `<button type="button" data-act="tmode" data-mode="${k}" class="${TIMER.mode === k ? 'on' : ''}">${l}</button>`).join('')}</div>
                <div class="timer-ring"><svg viewBox="0 0 120 120"><circle class="t-track" cx="60" cy="60" r="54"/><circle class="t-arc" id="t-arc" cx="60" cy="60" r="54"/></svg>
                    <div><b id="t-time">--:--</b><span id="t-label"></span></div></div>
                <div class="row"><button type="button" class="btn primary" data-act="tgo" id="t-go"></button>
                    <button type="button" class="btn" data-act="treset">${icon('reset')}Reset</button></div>
            </div>
        </div>
    </div>`;
    pageView.innerHTML = `<div class="page">${html}</div>`;
    mountCalc($('calc-panel'));
    drawSolver();
    drawTimer();

    ACT.solve = solve;
    ACT['solve-save'] = async (el) => {
        el.disabled = true;                                  // one click, one note
        const text = `**Problem:** ${SOLVER.problem}\n\n${SOLVER.text}`;
        const deck = S.sessionId ? deckById(S.sessionId) : null;
        try {
            await api('/api/notes', { method: 'POST', body: { deck_id: deck ? deck.id : null, text, kind: 'saved' } });
            SOLVER.savedTo = deck ? deckName(deck) : 'General notes';
            notesDeck = deck ? deck.id : 'general';          // Notes opens where it went
            showToast(`Saved to ${SOLVER.savedTo}`);
            render('tools');
        } catch (e) {
            el.disabled = false;
            showToast(e.message);
        }
    };
    ACT['open-notes'] = () => go('notes');
    ACT['solve-sqe'] = () => openSqe(SOLVER.problem);
    ACT['sx-run'] = () => {                                  // run the draft CUSTOM-Mx offered for this problem
        if (!SOLVER.exact) return;
        $('solve-in').value = `/mx ${SOLVER.exact.command}`;
        solve();
    };
    ACT['sx-edit'] = () => {
        if (!SOLVER.exact) return;
        const input = $('solve-in');
        input.value = `/mx ${SOLVER.exact.command}`;
        input.focus();
    };
    ACT['solve-exact'] = async (el) => {                     // the problem → a /mx command, checked before Solve
        const input = $('solve-in');
        const text = input.value.trim();
        if (!text) { showToast('Type a problem first'); input.focus(); return; }
        if (/^\/(custom-?mx|mx)\b/i.test(text)) { showToast('That is already an exact command — press Solve'); return; }
        el.disabled = true;
        try {
            const d = await draftExact(text);
            input.value = d.command;
            input.focus();
            showToast(d.note, 8000);
        } catch (e) {
            showToast(`Couldn't make that exact: ${e.message}`, 6000);
        }
        el.disabled = false;
    };
    $('solve-in').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) solve(); });
    ACT.tmode = (el) => timerMode(el.dataset.mode);
    ACT.tgo = () => (TIMER.running ? timerPause() : timerStart());
    ACT.treset = () => timerMode(TIMER.mode);
};

function drawSolver() {
    const out = $('solve-out');
    if (!out) return;
    out.hidden = !(SOLVER.text || SOLVER.busy);
    out.innerHTML = (SOLVER.verified ? `<span class="chip">${icon('check')}${SOLVER.engine ? esc(SOLVER.engine) : 'Exact answer'}: ${esc(SOLVER.verified)}</span>` : '') +
        (SOLVER.text ? formatLecture(SOLVER.text) : '') +
        (SOLVER.exact && !SOLVER.busy ? exactCardHTML(SOLVER.exact, 'data-act="sx-run"', 'data-act="sx-edit"') : '') +
        (SOLVER.busy && !SOLVER.text ? '<div class="cr-thinking"><i></i><i></i><i></i> <span>Working it out…</span></div>' : '') +
        (SOLVER.busy && SOLVER.text ? '<span class="cr-cursor">▋</span>' : '');
}

async function solve() {
    const input = $('solve-in');
    const problem = input ? input.value.trim() : '';
    if (!problem || SOLVER.busy) { if (input) input.focus(); return; }
    if (S.busy) { showToast('MrSOLIS is still teaching — try again in a moment'); return; }
    Object.assign(SOLVER, { problem, verified: '', engine: '', text: '', busy: true, savedTo: '', exact: null });
    if (currentPage === 'tools') render('tools');
    try {
        await streamNDJSON('/api/tools/solve', { problem }, (msg) => {
            if (msg.verified) { SOLVER.verified = msg.verified; SOLVER.engine = msg.engine || ''; }
            if (msg.exact) SOLVER.exact = msg.exact[0];       // a word problem: CUSTOM-Mx's draft to check, then Run
            if (msg.token) SOLVER.text += msg.token;
            if (msg.error) throw new Error(msg.error);
            drawSolver();
        });
    } catch (e) {
        if (!SOLVER.text) SOLVER.text = `Sorry, I couldn't solve that: ${e.message}`;
    }
    SOLVER.busy = false;
    if (currentPage === 'tools') render('tools');
}

// study timer (keeps running while you move around the app; the Tools button shows the time left)
const TIMER_MODES = { focus: [25, 'Focus'], short: [5, 'Short break'], long: [15, 'Long break'] };
const TIMER = { mode: 'focus', total: 25 * 60, left: 25 * 60, running: false, endAt: 0, iv: null };
const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;

function drawTimer() {
    const badge = $('timer-badge');
    badge.hidden = !TIMER.running;
    badge.textContent = mmss(TIMER.left);
    const t = $('t-time');
    if (!t) return;
    const C = 2 * Math.PI * 54;
    t.textContent = mmss(TIMER.left);
    $('t-label').textContent = TIMER_MODES[TIMER.mode][1];
    $('t-arc').style.strokeDasharray = `${(TIMER.left / TIMER.total) * C} ${C}`;
    $('t-go').innerHTML = TIMER.running ? icon('pause') + 'Pause' : icon('play') + (TIMER.left < TIMER.total ? 'Resume' : 'Start');
}
function timerTick() {
    TIMER.left = Math.max(0, Math.round((TIMER.endAt - Date.now()) / 1000));
    if (TIMER.left === 0) {
        timerPause();
        chime();
        const next = TIMER.mode === 'focus' ? 'short' : 'focus';
        showToast(TIMER.mode === 'focus' ? 'Focus session done — take a short break' : 'Break over — back to it', 6000);
        timerMode(next);
        return;
    }
    drawTimer();
}
function timerStart() {
    TIMER.running = true;
    TIMER.endAt = Date.now() + TIMER.left * 1000;
    clearInterval(TIMER.iv);
    TIMER.iv = setInterval(timerTick, 1000);
    drawTimer();
}
function timerPause() {
    TIMER.running = false;
    clearInterval(TIMER.iv);
    drawTimer();
}
function timerMode(mode) {
    timerPause();
    TIMER.mode = mode;
    TIMER.total = TIMER.left = TIMER_MODES[mode][0] * 60;
    if (currentPage === 'tools') render('tools'); else drawTimer();
}
function chime() {
    try {
        const ac = new AudioContext();
        [0, 0.28, 0.56].forEach((t) => {
            const o = ac.createOscillator(), g = ac.createGain();
            o.frequency.value = 880; o.type = 'sine';
            g.gain.setValueAtTime(0.0001, ac.currentTime + t);
            g.gain.exponentialRampToValueAtTime(0.25, ac.currentTime + t + 0.02);
            g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + t + 0.22);
            o.connect(g).connect(ac.destination);
            o.start(ac.currentTime + t); o.stop(ac.currentTime + t + 0.25);
        });
    } catch (e) { /* no audio device */ }
}
