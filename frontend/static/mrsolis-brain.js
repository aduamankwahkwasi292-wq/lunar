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
const ONLINE = { st: null, pid: null, models: {}, mounts: new Set(), busy: false, note: '', poll: null };   // the online brain (below)

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
        const backup = ONLINE.st && ONLINE.st.on && ONLINE.st.ready;     // the online brain thinks; this one waits
        actions = `<div class="bc-row">${c.selected
            ? `<span class="bc-inuse">${icon('check')}${backup ? 'Backup — used without internet' : loading ? 'In use — loading…' : 'In use'}</span>`
            : `<button type="button" class="btn small primary" data-brain="use" data-id="${c.id}">Use this brain</button>`}
            <button type="button" class="btn small ghost" data-brain="remove" data-id="${c.id}">${icon('trash')}Remove</button></div>`;
    } else {
        actions = `<div class="bc-row"><button type="button" class="btn small" data-brain="get" data-id="${c.id}"${otherBusy ? ' disabled' : ''}>` +
            `${icon('download')}Download · ${gbText(c.download_gb)}</button></div>`;
    }
    const failed = mine && (dl.state === 'error' || dl.state === 'cancelled') && !c.installed
        ? `<div class="bc-error">${dl.state === 'error' ? `The download stopped: ${esc(dl.error || 'no connection')}.` : 'Download cancelled.'} Press Download to carry on from where it stopped.</div>` : '';
    const measured = c.measured
        ? `<div class="bc-measured">${icon('check')}Measured on this computer: about ${Math.max(1, Math.round(c.measured.gen * 0.75))} words a second</div>` : '';
    return `<article class="bcard${c.selected && c.installed ? ' in-use' : ''}">
        <header><h3>${esc(c.name)}</h3></header>
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
    idleBrainNote();
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
        <div id="bp-online"></div>
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
    mountOnlineBrain($('bp-online'));
}

function pickerUpdate() {
    if (!$('brain-picker') || !BRAIN.st) return;
    const st = BRAIN.st, dl = st.download || {};
    const have = st.cards.some((c) => c.installed) || !!(ONLINE.st && ONLINE.st.on && ONLINE.st.ready);
    $('brain-picker').querySelector('[data-bp="done"]').disabled = !have;
    $('bp-note').textContent = dl.state === 'downloading' ? 'Keep MrSOLIS open while the brain downloads.'
        : have && st.state === 'starting' ? 'Loading the brain…' : have ? 'Ready.' : '';
}

/** The empty board says "First, download a brain" until a brain — or the online brain — is ready (the user,
 *  2026-11-14: tell users to download a model first, under "New here?"). Its button opens the chooser. */
function idleBrainNote() {
    const el = $('idle-brain');
    if (!el || !BRAIN.st) return;
    el.hidden = BRAIN.st.cards.some((c) => c.installed) || !!(ONLINE.st && ONLINE.st.on && ONLINE.st.ready);
}
$('idle-brain-go')?.addEventListener('click', showBrainPicker);

/** On start-up: no brain downloaded yet (a fresh install, or just updated from v1) → offer the chooser. */
async function brainStartup() {
    const [st, on] = await Promise.all([brainRefresh(), onlineRefresh()]);
    const online = !!(on && on.on && on.ready);
    if (st && st.engine && !st.cards.some((c) => c.installed) && !online) showBrainPicker();
}

// ══════════════════════════════════════════════════════════════════════
//   THE ONLINE BRAIN — the student's own AI account (backend/cloud.py, 2026-11-11)
//   The user: "make MrSOLIS offline-first instead of fully offline … users can bring their own LLM API key".
//   An API key from DeepSeek, OpenAI, Anthropic (Claude), Google Gemini, NVIDIA or any OpenAI-compatible server;
//   MrSOLIS's own brain stays the backup when there's no internet. The key never comes back to the page.
// ══════════════════════════════════════════════════════════════════════
const ONLINE_INTRO = 'Use an AI account you already have, with its <b>API key</b>. MrSOLIS then thinks with it — the same ' +
    'lessons, Interactive mode, quizzes and maths engines, with a stronger brain, all in this window. ' +
    'Without internet, MrSOLIS goes back to the brain on this computer.';

const onlineProv = (pid) => ONLINE.st.providers.find((p) => p.id === pid);
const onlineWho = (p) => (p.id === 'custom' ? 'your AI server' : p.name);

function onlineModelOptions(p) {
    const list = ONLINE.models[p.id] || (p.model ? [{ id: p.model, name: p.model }] : []);
    if (!list.length) return '<option value="">Load the models first</option>';
    return list.map((m) => `<option value="${esc(m.id)}"${m.id === p.model ? ' selected' : ''}>`
        + `${esc(m.name && m.name !== m.id ? `${m.name} · ${m.id}` : m.id)}</option>`).join('');
}

const USAGE_URL = 'https://chatgpt.com/settings/usage';
const LIMIT_CODE = 'subscription_sharing_usage_limit_exceeded';

/** The ChatGPT plan's rows (OpenAI's wording): sign in, signed in, or plan use not allowed. */
function chatgptRowsHTML(st) {
    const cg = st.chatgpt || {};
    const flow = cg.flow || {};
    if (!cg.signed_in) {
        const waiting = flow.state === 'waiting';
        return `<div class="ob-offer ob-wide"><div><b>Use your ChatGPT plan</b>
                <span>Complete eligible AI requests in this app with usage included in your ChatGPT plan or credits balance.
                It's separate from your MrSOLIS licence: MrSOLIS charges nothing for it.</span></div>
            ${waiting ? `<span class="ob-wait">Finish signing in in your browser…
                    <button type="button" class="btn small ghost" data-ob="cg-cancel">Cancel</button></span>`
                : '<button type="button" class="btn primary cg-btn" data-ob="cg-signin">Continue with ChatGPT</button>'}
            ${flow.state === 'error' || flow.state === 'declined' ? `<span class="ob-bad">${esc(flow.error)}</span>` : ''}</div>`;
    }
    return `<div class="ob-account ob-wide">${icon('check')}<span>Signed in to ChatGPT as <b>${esc(cg.email || 'your account')}</b></span>
            <button type="button" class="btn small ghost" data-ob="cg-signout">Sign out</button></div>
        ${cg.plan ? '' : `<div class="ob-offer ob-wide"><span class="ob-bad">ChatGPT plan use isn't turned on for MrSOLIS, so it
            can't think with your plan.</span><button type="button" class="btn small" data-ob="cg-consent">Turn on plan use</button></div>`}`;
}

function onlineHTML() {
    const st = ONLINE.st;
    if (!st) return '';
    const pid = ONLINE.pid || st.provider;
    const p = onlineProv(pid);
    const cg = p.signin ? (st.chatgpt || {}) : null;
    const limit = cg && (st.last || {}).code === LIMIT_CODE;
    const inUse = st.on && st.ready && st.provider === pid;
    let status = ONLINE.note;
    if (!status && inUse && limit) {
        status = `<span class="ob-bad">Your ChatGPT plan has reached its limit for MrSOLIS for now.</span>
            <a class="btn small primary" href="${USAGE_URL}" target="_blank" rel="noopener noreferrer">Manage usage</a>`;
    } else if (!status && inUse && cg) {
        status = `<span class="ob-good">${icon('check')}Using ChatGPT plan</span> ·
            <a class="ob-link" href="${USAGE_URL}" target="_blank" rel="noopener noreferrer">Manage usage</a>`;
    } else if (!status && inUse) {
        const last = st.last || {};
        status = last.ok === false
            ? `<span class="ob-bad">${esc(last.error)}${last.fallback ? ' — the brain on this computer answered instead.' : ''}</span>`
            : `<span class="ob-good">${icon('check')}In use — MrSOLIS thinks with ${esc(p.short)}</span>`;
    } else if (!status && st.on && !st.ready) {
        status = cg ? '<span class="ob-bad">Sign in with ChatGPT, load the models and pick one, then Save.</span>'
            : '<span class="ob-bad">Add the key, load the models and pick one, then Save.</span>';
    }
    const canModel = !cg || (cg.signed_in && cg.plan);
    return `<article class="bcard obcard${inUse ? ' in-use' : ''}">
        <header><h3>Online brain <span class="ob-sub">your own AI account</span></h3>
            <button type="button" class="switch${st.on ? ' on' : ''}" data-ob="toggle" aria-pressed="${st.on}"
                title="${st.on ? 'Turn the online brain off' : 'Turn the online brain on'}"></button></header>
        <p class="bc-for ob-intro">${ONLINE_INTRO}</p>
        <div class="ob-grid">
            <label class="ob-field"><span>AI company</span>
                <select class="select" data-ob="provider">${st.providers.map((q) =>
                    `<option value="${q.id}"${q.id === pid ? ' selected' : ''}>${esc(q.name)}</option>`).join('')}</select></label>
            ${cg ? chatgptRowsHTML(st) : ''}
            ${p.needs_base ? `<label class="ob-field ob-wide"><span>Server address</span>
                <input class="field" data-ob="base" type="url" spellcheck="false" autocomplete="off"
                    placeholder="https://…/v1, or http://127.0.0.1:1234/v1" value="${esc(p.base)}"></label>` : ''}
            ${cg ? '' : `<label class="ob-field"><span>API key${p.key_optional ? ' (if the server needs one)' : ''}</span>
                <span class="ob-line"><input class="field" data-ob="key" type="password" autocomplete="off" spellcheck="false"
                    placeholder="${p.has_key ? `Saved (${esc(p.key_hint)}) — paste a new one to change it` : 'Paste your key — it stays on this computer'}">
                ${p.keys_url ? `<a class="btn small ghost" href="${esc(p.keys_url)}" target="_blank" rel="noopener noreferrer">Get a key</a>` : ''}</span></label>`}
            ${canModel ? `<label class="ob-field"><span>Model</span>
                <span class="ob-line"><select class="select" data-ob="model">${onlineModelOptions(p)}</select>
                <button type="button" class="btn small" data-ob="load">${icon('reset')}Load models</button></span></label>
            <label class="ob-check"><input type="checkbox" data-ob="sees"${p.sees ? ' checked' : ''}>
                It can see pictures, slides and video frames</label>` : ''}
        </div>
        <div class="bc-row"><span class="ob-status">${status || ''}</span>
            ${canModel ? `<span class="ob-btns"><button type="button" class="btn small" data-ob="test">Test it</button>
                <button type="button" class="btn small primary" data-ob="save">Save</button></span>` : ''}</div>
        ${cg ? `<p class="ob-note">When it's on, your questions and the slides you study go to OpenAI over the internet and
            use your ChatGPT plan; OpenAI's terms apply. MrSOLIS keeps the sign-in on this computer, locked to this Windows
            account.</p>`
            : `<p class="ob-note">When it's on, your questions and the slides you study are sent to ${esc(onlineWho(p))} over the
            internet, and its prices and terms apply. The key is locked to this Windows account and is only ever sent
            to ${esc(onlineWho(p))}.</p>`}
        <p class="ob-note">${st.chatgpt ? 'Claude Pro and Max plans can\'t be plugged in: Anthropic allows them only in its own apps. A Claude API key works.'
            : 'ChatGPT Plus and Claude Pro plans can\'t be plugged in: Anthropic allows Claude plans only in its own apps, and OpenAI must approve an app before it can use ChatGPT plans. An API key works for both.'}</p>
    </article>`;
}

function onlineRender() {
    for (const el of [...ONLINE.mounts]) {
        if (!el.isConnected) { ONLINE.mounts.delete(el); continue; }
        el.innerHTML = onlineHTML();
    }
    chatgptWelcome();                                 // the ChatGPT plan just went on: OpenAI's first-time notice
}

async function onlineRefresh() {
    const before = ONLINE.st && ONLINE.st.chatgpt && ONLINE.st.chatgpt.flow && ONLINE.st.chatgpt.flow.state;
    try { ONLINE.st = await api('/api/brain/online'); } catch (e) { return null; }
    const cg = ONLINE.st.chatgpt;
    const flow = cg && cg.flow && cg.flow.state;
    onlineRender();
    pickerUpdate();
    idleBrainNote();
    clearTimeout(ONLINE.poll);
    if (flow === 'waiting') ONLINE.poll = setTimeout(onlineRefresh, 1500);
    if (before === 'waiting' && flow === 'done' && cg.signed_in && cg.plan) {   // just signed in: fetch the models
        ONLINE.pid = 'chatgpt';
        const card = [...ONLINE.mounts].map((el) => el.isConnected && el.querySelector('.obcard')).find(Boolean);
        if (card) onlineAct(card, 'load');
    }
    chatgptWelcome();
    return ONLINE.st;
}

/** OpenAI's first-time notice, once, when the ChatGPT plan starts thinking for MrSOLIS. */
function chatgptWelcome() {
    const st = ONLINE.st;
    if (!st || !st.chatgpt || st.chatgpt.welcomed || !st.on || !st.ready || st.provider !== 'chatgpt' || $('cg-welcome')) return;
    const box = document.createElement('div');
    box.id = 'cg-welcome';
    box.innerHTML = `<div class="bp-box cg-box" role="dialog" aria-labelledby="cg-title">
        <h1 id="cg-title">You’re using your ChatGPT plan</h1>
        <p class="bp-sub">Eligible usage in this app uses your ChatGPT plan. Manage usage in your
            <a href="${USAGE_URL}" target="_blank" rel="noopener noreferrer">ChatGPT settings</a>.</p>
        <div class="bp-foot"><button type="button" class="btn primary" data-cg="ok">Got it</button></div></div>`;
    document.body.appendChild(box);
    const done = async () => {
        box.remove();
        try { ONLINE.st = await api('/api/brain/chatgpt/welcomed', { method: 'POST' }); } catch (e) { /* shown again next time */ }
    };
    box.querySelector('[data-cg="ok"]').addEventListener('click', done);
    box.addEventListener('click', (e) => { if (e.target === box) done(); });
    document.addEventListener('keydown', function esc1(e) {
        if (e.key === 'Escape' && $('cg-welcome')) { done(); document.removeEventListener('keydown', esc1); }
    });
}

/** What is typed on the card now (a key only when one was pasted). */
function onlineDraft(card) {
    const q = (s) => card.querySelector(`[data-ob="${s}"]`);
    const d = { provider: q('provider').value };
    if (q('sees')) d.sees = q('sees').checked;
    if (q('model') && q('model').value) d.model = q('model').value;
    const key = q('key') && q('key').value.trim();
    if (key) d.key = key;
    if (q('base')) d.base = q('base').value.trim();
    return d;
}

async function onlineAct(card, what) {
    const say = (html) => { ONLINE.note = html; const s = card.querySelector('.ob-status'); if (s) s.innerHTML = html; };
    if (ONLINE.busy) return;
    ONLINE.busy = true;
    try {
        const d = onlineDraft(card);
        if (what === 'cg-signin' || what === 'cg-consent') {
            const r = await api('/api/brain/chatgpt/signin', { method: 'POST', body: { consent: what === 'cg-consent' } });
            window.open(r.url, '_blank', 'noopener');            // the student's own browser (main.js)
            ONLINE.pid = 'chatgpt';
            ONLINE.note = '';
            ONLINE.busy = false;
            await onlineRefresh();
            return;
        }
        if (what === 'cg-cancel') {
            ONLINE.st = await api('/api/brain/chatgpt/cancel', { method: 'POST' });
            onlineRender();
            return;
        }
        if (what === 'cg-signout') {
            if (!armed(card.querySelector('[data-ob="cg-signout"]'), 'Sign out?')) return;
            const r = await api('/api/brain/chatgpt/signout', { method: 'POST' });
            ONLINE.st = r;
            ONLINE.models.chatgpt = null;
            ONLINE.note = '';
            onlineRender();
            showToast(r.revoked ? 'Signed out of ChatGPT' : 'Signed out here — to be sure, also disconnect MrSOLIS in ChatGPT’s settings', 5000);
            return;
        }
        if (what === 'load') {
            say('<span class="muted">Asking for the models…</span>');
            const r = await api('/api/brain/online/models', { method: 'POST', body: { provider: d.provider, key: d.key, base: d.base } });
            ONLINE.models[d.provider] = r.models;
            const p = onlineProv(d.provider);
            const pick = r.models.some((m) => m.id === p.model) ? p.model : r.suggest;
            card.querySelector('[data-ob="model"]').innerHTML = onlineModelOptions({ ...p, model: pick });
            say(`<span class="ob-good">${icon('check')}${r.models.length} models — pick one, then Save</span>`);
        } else if (what === 'save' || what === 'test') {
            if (!d.model) { say('<span class="ob-bad">Load the models and pick one first.</span>'); return; }
            ONLINE.st = await api('/api/brain/online', { method: 'POST', body: d });
            ONLINE.pid = d.provider;
            ONLINE.note = '';
            onlineRender();
            if (what === 'test') {
                const fresh = [...ONLINE.mounts].find((el) => el.isConnected);
                const card2 = fresh && fresh.querySelector('.obcard');
                const say2 = (html) => { ONLINE.note = html; const s = card2 && card2.querySelector('.ob-status'); if (s) s.innerHTML = html; };
                say2('<span class="muted">Asking it to say hello…</span>');
                const r = await api('/api/brain/online/test', { method: 'POST' });
                say2(r.ok ? `<span class="ob-good">${icon('check')}Works — first words in ${(r.ms / 1000).toFixed(1)} s: “${esc(r.reply)}”</span>`
                    : `<span class="ob-bad">${esc(r.error)}</span>`);
            } else {
                showToast(ONLINE.st.ready && ONLINE.st.on ? `Saved — MrSOLIS now thinks with ${onlineProv(d.provider).short}` : 'Saved');
            }
        } else if (what === 'toggle') {
            const want = !ONLINE.st.on;
            const body = want ? { ...d, on: true } : { on: false };
            if (want && !d.model) delete body.model;
            ONLINE.st = await api('/api/brain/online', { method: 'POST', body });
            ONLINE.note = '';
            onlineRender();
            if (want && !ONLINE.st.ready) showToast('Add the key, load the models and pick one, then Save', 4500);
            else showToast(want ? `MrSOLIS now thinks with ${onlineProv(ONLINE.st.provider).short}` : 'Back to the brain on this computer');
        }
    } catch (e) {
        say(`<span class="ob-bad">${esc(e.message)}</span>`);
    } finally {
        ONLINE.busy = false;
    }
    brainRefresh();                                   // the local card becomes "Backup", or "In use" again
}

/** Draw the online brain's card into `el` and keep it live. */
function mountOnlineBrain(el) {
    ONLINE.mounts.add(el);
    el.addEventListener('click', (e) => {
        const b = e.target.closest('[data-ob]');
        const card = e.target.closest('.obcard');
        if (!b || !card || b.tagName === 'SELECT' || b.tagName === 'INPUT') return;
        onlineAct(card, b.dataset.ob);
    });
    el.addEventListener('change', (e) => {
        if (e.target.dataset.ob === 'provider') {
            ONLINE.pid = e.target.value;
            ONLINE.note = '';
            onlineRender();
        }
    });
    if (ONLINE.st) el.innerHTML = onlineHTML();
    onlineRefresh();
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
