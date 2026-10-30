/* ═══════════════════════════════════════════════════════════════════
   MrSOLIS 3 Brain — which AI model MrSOLIS thinks (and looks) with.

     Cards     one per brain (backend/brain.py CATALOG): what it's good at,
               speed / smarts dots and estimates, download / use / remove.
               Shown in Settings → Brain, and as a chooser on the first start
               after an update (when no brain is downloaded yet).
     Pictures  a photo or screenshot attached in the chat box (button, paste,
               or drop on the chat box) goes to a brain that sees.

   Every figure on a card is an estimate from published tests; once a brain
   has run, its card also shows the speed measured on this computer.
   Uses api / icon / esc / armed from mrsolis-pages.js.
   ═══════════════════════════════════════════════════════════════════ */
'use strict';

const BRAIN = { st: null, poll: null, mounts: new Set(), wasEmpty: false };

const BRAIN_INTRO = 'Smaller brains are <b>faster</b> and use <b>less memory</b>, but make more mistakes. ' +
    'Bigger brains are <b>smarter</b>, but slower and need more memory. ' +
    'Every figure on these cards is an <b>estimate</b> from published tests — real speed depends on your computer. ' +
    'You can switch brains any time in Settings.';

const dots = (n) => `<span class="bc-dots">${[1, 2, 3, 4, 5].map((i) => `<i class="${i <= n ? 'on' : ''}"></i>`).join('')}</span>`;
const gbText = (n) => `${Math.round(n * 100) / 100} GB`;          // 0.74 GB, 1.95 GB, 3.5 GB

function brainCardHTML(c, st) {
    const dl = st.download || {};
    const mine = dl.id === c.id;
    const downloading = mine && dl.state === 'downloading';
    const otherBusy = dl.state === 'downloading' && !mine;
    let actions;
    if (downloading) {
        const pct = dl.total ? Math.floor((dl.done / dl.total) * 100) : 0;
        actions = `<div class="bc-progress"><i style="width:${pct}%"></i></div>
            <div class="bc-row"><span class="muted">${dl.total ? `${pct}% · ${gbText(dl.done / 1e9)} of ${gbText(dl.total / 1e9)}` : 'Starting the download…'}</span>
            <button type="button" class="btn small" data-brain="cancel">Cancel</button></div>`;
    } else if (c.installed) {
        const loading = c.selected && st.state === 'starting';
        actions = `<div class="bc-row">${c.selected
            ? `<span class="bc-inuse">${icon('check')}${loading ? 'In use — loading…' : 'In use'}</span>`
            : `<button type="button" class="btn small primary" data-brain="use" data-id="${c.id}">Use this brain</button>`}
            <button type="button" class="btn small ghost" data-brain="remove" data-id="${c.id}">${icon('trash')}Remove</button></div>`;
    } else {
        actions = `<div class="bc-row"><button type="button" class="btn small${c.recommended ? ' primary' : ''}" data-brain="get" data-id="${c.id}"${otherBusy ? ' disabled' : ''}>` +
            `${icon('download')}Download · ${gbText(c.download_gb)}</button></div>`;
    }
    const failed = mine && (dl.state === 'error' || dl.state === 'cancelled') && !c.installed
        ? `<div class="bc-error">${dl.state === 'error' ? `The download stopped: ${esc(dl.error || 'no connection')}.` : 'Download cancelled.'} Press Download to carry on from where it stopped.</div>` : '';
    const measured = c.measured
        ? `<div class="bc-measured">${icon('check')}Measured on this computer: about ${Math.max(1, Math.round(c.measured.gen * 0.75))} words a second</div>` : '';
    return `<article class="bcard${c.selected && c.installed ? ' in-use' : ''}${c.recommended ? ' rec' : ''}">
        <header><h3>${esc(c.name)}</h3>${c.recommended ? '<span class="bc-tag">Recommended</span>' : ''}</header>
        <p class="bc-tagline">${esc(c.tagline)}</p>
        <p class="bc-for">${esc(c.for)}</p>
        <div class="bc-meters">
            <div><span>Speed</span>${dots(c.speed)}</div>
            <div><span>Brain power</span>${dots(c.smarts)}</div>
            <div><span>Reading slides</span>${dots(c.slides)}</div>
        </div>
        <dl class="bc-est">
            <dt>Writes</dt><dd>${esc(c.writing)}</dd>
            <dt>Pictures</dt><dd>${esc(c.picture)}</dd>
            <dt>Memory</dt><dd>needs about ${gbText(c.ram_gb)} free</dd>
            <dt>Download</dt><dd>${gbText(c.download_gb)}, once</dd>
        </dl>
        <ul class="bc-facts">${c.facts.map((f) => `<li>${esc(f)}</li>`).join('')}</ul>
        ${measured}
        <p class="bc-licence">Estimates, not promises · ${esc(c.licence)} licence</p>
        ${failed}${actions}
    </article>`;
}

function brainCardsHTML(st) {
    if (!st.engine) return '<p class="muted">The AI engine (llama-server) is missing from this install, so brains can’t run here.</p>';
    return `<div class="bcards">${st.cards.map((c) => brainCardHTML(c, st)).join('')}</div>`;
}

async function brainRefresh() {
    try { BRAIN.st = await api('/api/brain'); } catch (e) { return null; }
    for (const el of [...BRAIN.mounts]) {
        if (!el.isConnected) { BRAIN.mounts.delete(el); continue; }
        el.innerHTML = brainCardsHTML(BRAIN.st);
    }
    const st = BRAIN.st;
    const dl = st.download || {};
    // a download just finished and there was no brain before: start using it straight away
    if (dl.state === 'done' && BRAIN.wasEmpty && dl.id) {
        BRAIN.wasEmpty = false;
        try { BRAIN.st = await api('/api/brain/select', { method: 'POST', body: { id: dl.id } }); } catch (e) { /* keep going */ }
        showToast('Brain downloaded — MrSOLIS is loading it');
        return brainRefresh();
    }
    pickerUpdate();
    const busy = dl.state === 'downloading' || st.state === 'starting';
    clearTimeout(BRAIN.poll);
    if (busy && (BRAIN.mounts.size || $('brain-picker'))) BRAIN.poll = setTimeout(brainRefresh, 1000);
    if (!busy && typeof checkHealth === 'function') checkHealth();
    return st;
}

async function brainAct(btn) {
    const what = btn.dataset.brain, id = btn.dataset.id;
    try {
        if (what === 'get') {
            BRAIN.wasEmpty = !BRAIN.st.cards.some((c) => c.installed);
            BRAIN.st = await api('/api/brain/download', { method: 'POST', body: { id } });
        } else if (what === 'cancel') {
            await api('/api/brain/cancel', { method: 'POST' });
        } else if (what === 'use') {
            await api('/api/brain/select', { method: 'POST', body: { id } });
            showToast('Switching brains — the first answer may take a few seconds longer');
        } else if (what === 'remove') {
            if (!armed(btn, 'Remove it?')) return;
            await api(`/api/brain/${encodeURIComponent(id)}`, { method: 'DELETE' });
            showToast('Brain removed');
        }
    } catch (e) { showToast(e.message, 4500); }
    brainRefresh();
}

/** Draw the cards into `el` and keep them live (downloads, loading). */
function mountBrainCards(el) {
    BRAIN.mounts.add(el);
    el.addEventListener('click', (e) => {
        const b = e.target.closest('[data-brain]');
        if (b && !b.disabled) brainAct(b);
    });
    if (BRAIN.st) el.innerHTML = brainCardsHTML(BRAIN.st);
    brainRefresh();
}

// ── the chooser on the first start after an update ───────────────────
function showBrainPicker() {
    if ($('brain-picker')) return;
    const box = document.createElement('div');
    box.id = 'brain-picker';
    box.innerHTML = `<div class="bp-box" role="dialog" aria-labelledby="bp-title">
        <h1 id="bp-title">Choose MrSOLIS’s new brain</h1>
        <p class="bp-sub">MrSOLIS can now <b>look at</b> your slides, diagrams and photos, not just read their words. Pick the brain that suits your computer — it downloads once, then works offline.</p>
        <p class="bp-intro">${BRAIN_INTRO}</p>
        <div id="bp-cards"></div>
        <div class="bp-foot"><span id="bp-note" class="muted"></span>
            <button type="button" class="btn ghost" data-bp="later">Later</button>
            <button type="button" class="btn primary" data-bp="done" disabled>Start learning</button></div>
    </div>`;
    document.body.appendChild(box);
    box.addEventListener('click', (e) => {
        const b = e.target.closest('[data-bp]');
        if (!b || b.disabled) return;
        box.remove();
        if (b.dataset.bp === 'later') showToast('You can choose a brain any time in Settings → Brain', 4500);
    });
    mountBrainCards($('bp-cards'));
}

function pickerUpdate() {
    if (!$('brain-picker') || !BRAIN.st) return;
    const st = BRAIN.st, dl = st.download || {};
    const have = st.cards.some((c) => c.installed);
    $('brain-picker').querySelector('[data-bp="done"]').disabled = !have;
    $('bp-note').textContent = dl.state === 'downloading' ? 'Keep MrSOLIS open while the brain downloads.'
        : have && st.state === 'starting' ? 'Loading the brain…' : have ? 'Ready.' : '';
}

/** On start-up: no brain downloaded yet (a fresh install, or just updated from v1) → offer the chooser. */
async function brainStartup() {
    const st = await brainRefresh();
    if (st && st.engine && !st.cards.some((c) => c.installed)) showBrainPicker();
}

// ══════════════════════════════════════════════════════════════════════
//   A PICTURE IN THE CHAT BOX
// ══════════════════════════════════════════════════════════════════════
const PIC = { url: null, canSee: false };
const picChip = $('pic-chip');
const picInput = $('pic-input');

/** The brain can see: show the picture button and the "Look at slides" switch (called from checkHealth). */
function setCanSee(on) {
    PIC.canSee = !!on;
    $('chat-pic').hidden = !PIC.canSee;
    $('look-chip').hidden = !PIC.canSee;
    if (!PIC.canSee) clearPicture();
}

// ── "Look at slides": under the board (the user moved it there from Settings, 2026-10-21) ──
// On: a brain that sees also looks at slides with pictures, charts or diagrams while it teaches.
// Off: lessons are taught from the slide's words only — faster on a slow computer.
const LOOK = { on: true };
function drawLook() {
    const chip = $('look-chip');
    chip.classList.toggle('on', LOOK.on);
    chip.setAttribute('aria-pressed', String(LOOK.on));
    chip.title = LOOK.on
        ? 'MrSOLIS looks at slides with pictures, charts or diagrams while he teaches. Click to turn off for faster lessons.'
        : 'MrSOLIS reads only the words on each slide (faster). Click to let him look at pictures and diagrams too.';
}
$('look-chip').addEventListener('click', async () => {
    try {
        const r = await api('/api/settings', { method: 'PUT', body: { look_at_slides: !LOOK.on } });
        LOOK.on = r.settings.look_at_slides !== false;
        drawLook();
        showToast(LOOK.on ? 'MrSOLIS will look at slides with pictures and diagrams'
            : 'MrSOLIS will read only the words on each slide — faster lessons', 3500);
    } catch (e) { showToast(e.message); }
});
api('/api/settings').then((r) => { LOOK.on = r.settings.look_at_slides !== false; drawLook(); }).catch(() => drawLook());

/** Shrink a picture to at most 1280 px a side and keep it as a JPEG data: URL. */
function shrinkPicture(file) {
    return new Promise((resolve, reject) => {
        const src = URL.createObjectURL(file);
        const img = new Image();
        img.onload = () => {
            const k = Math.min(1, 1280 / Math.max(img.naturalWidth, img.naturalHeight));
            const c = document.createElement('canvas');
            c.width = Math.max(1, Math.round(img.naturalWidth * k));
            c.height = Math.max(1, Math.round(img.naturalHeight * k));
            const g = c.getContext('2d');
            g.fillStyle = '#fff';                       // transparent PNGs: white paper, not black
            g.fillRect(0, 0, c.width, c.height);
            g.drawImage(img, 0, 0, c.width, c.height);
            URL.revokeObjectURL(src);
            resolve(c.toDataURL('image/jpeg', 0.88));
        };
        img.onerror = () => { URL.revokeObjectURL(src); reject(new Error('That picture couldn’t be opened')); };
        img.src = src;
    });
}

async function attachPicture(file) {
    if (!file || !/^image\//.test(file.type)) return false;
    if (!PIC.canSee) { showToast('This brain can’t see pictures — choose one in Settings → Brain'); return true; }
    try {
        PIC.url = await shrinkPicture(file);
    } catch (e) { showToast(e.message); return true; }
    if (typeof clearVideo === 'function') clearVideo();          // one attachment at a time (mrsolis-video.js)
    picChip.querySelector('img').src = PIC.url;
    picChip.hidden = false;
    chatInput.placeholder = 'Ask about this picture — or just press Enter';
    chatInput.focus();
    return true;
}

function clearPicture() {
    PIC.url = null;
    picChip.hidden = true;
    picChip.querySelector('img').removeAttribute('src');
    if (typeof lessonUi === 'function') lessonUi();
}

/** The attached picture, handed over once (ask() sends it with the question). */
function takePicture() {
    const url = PIC.url;
    if (url) clearPicture();
    return url;
}

$('chat-pic').addEventListener('click', () => picInput.click());
picInput.addEventListener('change', () => {
    const f = picInput.files && picInput.files[0];
    picInput.value = '';
    if (f) attachPicture(f);
});
picChip.querySelector('button').addEventListener('click', clearPicture);
chatInput.addEventListener('paste', (e) => {
    const f = [...((e.clipboardData && e.clipboardData.files) || [])].find((x) => /^image\//.test(x.type));
    if (f) { e.preventDefault(); attachPicture(f); }
});

brainStartup();
