/* ═══════════════════════════════════════════════════════════════════
   MrSOLIS 3 Voice — everything on this computer.

     Transcription  (mic button)   speak, and your words are typed
                                   into the chat box as you talk.
     Read aloud     (under every lesson and answer) MrSOLIS reads it out.

   The spoken class is Interactive mode (mrsolis-class.js), which uses this
   file's Mic and VOICE. "Live" (the wave button: a spoken chat that was
   always listening) was removed on 2026-11-11 at the user's request:
   Interactive mode does more than it did.

   The microphone is streamed (16 kHz) to the backend, which detects
   speech and transcribes it (Parakeet + Silero, backend/voice.py);
   text is spoken a sentence at a time (Supertonic, male voice).
   Uses the classroom's helpers from mrsolis-wire.js.
   ═══════════════════════════════════════════════════════════════════ */
'use strict';

const VOICE = { hear: false, speak: false };
fetch('/api/voice/status').then((r) => r.json()).then((s) => {
    Object.assign(VOICE, s);
    if (S.parts.length) renderTalk();                   // the Read aloud buttons appear once the voice is known
}).catch(() => {});

// ── microphone → backend listening session ───────────────────────────
const TAP = `class Tap extends AudioWorkletProcessor {
  process(inputs) { const ch = inputs[0] && inputs[0][0]; if (ch) this.port.postMessage(ch.slice(0)); return true; }
}
registerProcessor('mrsolis-tap', Tap);`;

class Mic {
    constructor(mode, onEvent, onLevel) {
        this.mode = mode; this.onEvent = onEvent; this.onLevel = onLevel;
        this.chunks = []; this.inflight = false; this.closed = false;
    }

    async start() {
        // open the backend session and the microphone at the same time — every bit of start-up
        // delay is speech lost if the student talks as soon as they click
        const listen = fetch('/api/voice/listen', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: this.mode }),
        }).then(async (r) => {
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || 'Could not start listening');
            return d.id;
        });
        const media = navigator.mediaDevices.getUserMedia({
            audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
        try {
            [this.id, this.stream] = await Promise.all([listen, media]);
        } catch (e) {
            media.then((st) => st.getTracks().forEach((t) => t.stop())).catch(() => {});
            listen.then((id) => fetch(`/api/voice/listen/${id}`, { method: 'DELETE' })).catch(() => {});
            throw e;
        }
        if (this.closed) { this.stop(); return; }                   // stopped while starting
        try { this.ctx = new AudioContext({ sampleRate: 16000 }); } catch (e) { this.ctx = new AudioContext(); }
        const url = URL.createObjectURL(new Blob([TAP], { type: 'application/javascript' }));
        await this.ctx.audioWorklet.addModule(url);
        URL.revokeObjectURL(url);
        this.node = new AudioWorkletNode(this.ctx, 'mrsolis-tap');
        this.node.port.onmessage = (e) => this.push(e.data);
        const silent = this.ctx.createGain();
        silent.gain.value = 0;                                   // keeps the tap running, plays nothing
        this.ctx.createMediaStreamSource(this.stream).connect(this.node);
        this.node.connect(silent).connect(this.ctx.destination);
        this.timer = setInterval(() => this.flush(), 220);
        // only report "listening" once sound is really arriving (Windows mics take a moment)
        await new Promise((resolve) => { this.ready = resolve; setTimeout(resolve, 1500); });
        this.ready = null;
    }

    push(frame) {
        if (this.closed) return;
        if (this.ready) this.ready();
        let x = frame;
        const rate = this.ctx.sampleRate;
        if (rate !== 16000) {                                    // fallback: resample to 16 kHz
            const n = Math.floor(x.length * 16000 / rate), out = new Float32Array(n);
            for (let i = 0; i < n; i++) {
                const p = i * rate / 16000, j = Math.floor(p), f = p - j;
                out[i] = x[j] * (1 - f) + (x[j + 1] !== undefined ? x[j + 1] : x[j]) * f;
            }
            x = out;
        }
        this.chunks.push(x);
        let sum = 0;
        for (let i = 0; i < x.length; i++) sum += x[i] * x[i];
        if (this.onLevel) this.onLevel(Math.min(1, Math.sqrt(sum / x.length) * 9));
    }

    async flush() {
        if (this.inflight || this.closed || !this.chunks.length) return;
        const total = this.chunks.reduce((n, c) => n + c.length, 0), audio = new Float32Array(total);
        let o = 0;
        for (const c of this.chunks) { audio.set(c, o); o += c.length; }
        this.chunks = [];
        this.inflight = true;
        try {
            const r = await fetch(`/api/voice/listen/${this.id}`, {
                method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: audio.buffer,
            });
            if (r.ok && !this.closed) (await r.json()).events.forEach((ev) => this.onEvent(ev));
        } catch (e) { /* the next flush retries */ }
        this.inflight = false;
    }

    stop() {
        this.closed = true;
        clearInterval(this.timer);
        try { this.stream.getTracks().forEach((t) => t.stop()); } catch (e) { /* not started */ }
        try { this.ctx.close(); } catch (e) { /* not started */ }
        if (this.id) fetch(`/api/voice/listen/${this.id}`, { method: 'DELETE' }).catch(() => {});
    }

    // Stop, but first send the last bit of audio and get the sentence in progress heard properly
    // (otherwise pressing stop straight after speaking keeps only the rough words-so-far).
    async finish() {
        clearInterval(this.timer);
        try { this.stream.getTracks().forEach((t) => t.stop()); } catch (e) { /* not started */ }
        for (let i = 0; i < 50 && this.inflight; i++) await new Promise((r) => setTimeout(r, 40));
        const total = this.chunks.reduce((n, c) => n + c.length, 0), audio = new Float32Array(total);
        let o = 0;
        for (const c of this.chunks) { audio.set(c, o); o += c.length; }
        this.chunks = [];
        this.closed = true;
        try { this.ctx.close(); } catch (e) { /* not started */ }
        if (!this.id) return;
        try {
            const r = await fetch(`/api/voice/listen/${this.id}?final=1`, {
                method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: audio.buffer,
            });
            if (r.ok) (await r.json()).events.forEach((ev) => this.onEvent(ev));
        } catch (e) {
            fetch(`/api/voice/listen/${this.id}`, { method: 'DELETE' }).catch(() => {});
        }
    }
}

function micError(e) {
    const denied = e && (e.name === 'NotAllowedError' || e.name === 'SecurityError');
    showToast(denied ? 'Microphone blocked — allow it in Windows Settings → Privacy → Microphone'
        : `Couldn't use the microphone: ${e.message || e}`, 6000);
}

// ══════════════════════════════════════════════════════════════════════
//   TRANSCRIPTION — words typed into the chat box as you speak
// ══════════════════════════════════════════════════════════════════════
const micBtn = $('chat-mic');
const DICT = { mic: null, finishing: null, base: '', lastHeard: 0, idle: null };

async function startDictation() {
    if (!VOICE.hear) { showToast('The speech model isn\'t installed'); return; }
    DICT.base = chatInput.value.trim() ? chatInput.value.trim() + ' ' : '';
    DICT.lastHeard = Date.now();
    const mic = DICT.mic = new Mic('dictate', (ev) => {
        if (DICT.mic !== mic && DICT.finishing !== mic) return;          // sent or abandoned meanwhile
        if (ev.type === 'speech_start' || ev.type === 'partial' || ev.type === 'final') DICT.lastHeard = Date.now();
        if (ev.type === 'partial') chatInput.value = DICT.base + ev.text;
        if (ev.type === 'final') { DICT.base += ev.text + ' '; chatInput.value = DICT.base; }
    }, (level) => micBtn.style.setProperty('--level', level.toFixed(2)));
    micBtn.classList.add('starting');
    micBtn.title = 'Stop transcription';
    chatInput.placeholder = 'Starting the microphone…';
    try {
        await mic.start();
    } catch (e) {
        stopDictation();
        micError(e);
        return;
    }
    if (DICT.mic !== mic) return;                                     // stopped while starting
    micBtn.classList.replace('starting', 'on');
    chatInput.placeholder = 'Listening… speak, then press the mic again (or Send)';
    // stop by itself after 20 s without speech
    DICT.idle = setInterval(() => { if (Date.now() - DICT.lastHeard > 20000) stopDictation(); }, 1000);
}

// finish = true (mic button, Esc): the sentence being spoken is heard properly before stopping.
// finish = false (Send, idle): stop at once and keep what's in the box.
function stopDictation(finish = false) {
    DICT.finishing = null;
    if (!DICT.mic) return;
    const mic = DICT.mic;
    DICT.mic = null;
    if (finish) {
        DICT.finishing = mic;
        mic.finish().then(() => {
            if (DICT.finishing !== mic) return;
            DICT.finishing = null;
            chatInput.value = chatInput.value.trim();
        });
    } else {
        mic.stop();
    }
    clearInterval(DICT.idle);
    micBtn.classList.remove('on', 'starting');
    micBtn.style.removeProperty('--level');
    micBtn.title = 'Transcription — speak and your words are typed here';
    chatInput.placeholder = chatPlaceholder();
    chatInput.value = chatInput.value.trim();
    chatInput.focus();
}

micBtn.addEventListener('click', () => (DICT.mic ? stopDictation(true) : startDictation()));

// ══════════════════════════════════════════════════════════════════════
//   THE VOICE QUEUE — text said a sentence or two at a time (Read aloud)
// ══════════════════════════════════════════════════════════════════════
const SPEECH = { queue: [], chain: Promise.resolve(), playing: null };

function silence() {
    SPEECH.queue.forEach((it) => { it.cancelled = true; });
    SPEECH.queue = [];
    SPEECH.chain = Promise.resolve();
    if (SPEECH.playing) { SPEECH.playing.pause(); SPEECH.playing = null; }
}

// a very long sentence takes a while to voice: say it in two halves, cut at a comma
function splitLong(t) {
    if (t.length <= 170) return [t];
    const cut = t.lastIndexOf(', ', Math.floor(t.length / 2) + 40);
    return cut > 50 ? [t.slice(0, cut + 1), t.slice(cut + 2)] : [t];
}

function enqueue(text) {
    if (!VOICE.speak) return;
    const sentences = text.replace(/\s+/g, ' ').match(/[^.!?]+[.!?]*/g) || [];
    // pair up very short sentences so the voice flows — but when nothing is playing yet, let a short
    // first one (a heading, "Good question.") go alone so the voice starts at once
    const quiet = !SPEECH.playing && !SPEECH.queue.length;
    const pieces = [];
    for (const s of sentences) {
        const t = s.trim();
        if (!t || !/[a-z0-9]/i.test(t)) continue;
        const prev = pieces[pieces.length - 1];
        if (prev && prev.length < 60 && !(quiet && pieces.length === 1)) pieces[pieces.length - 1] += ' ' + t;
        else pieces.push(...splitLong(t));
    }
    for (const t of pieces) {
        const item = { text: t, url: null, cancelled: false };
        item.ready = SPEECH.chain = SPEECH.chain.then(async () => {
            if (item.cancelled) return;
            try {
                const r = await fetch('/api/voice/speak', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: t }) });
                if (r.ok && r.status !== 204 && !item.cancelled) item.url = URL.createObjectURL(await r.blob());
            } catch (e) { /* skip this sentence */ }
        });
        SPEECH.queue.push(item);
    }
    playNext();
}

async function playNext() {
    if (!SPEECH.queue.length && !SPEECH.playing) { doneReading(); return; }
    if (SPEECH.playing || !SPEECH.queue.length) return;
    const item = SPEECH.queue[0];
    await item.ready;
    if (item.cancelled || SPEECH.queue[0] !== item) return;
    SPEECH.queue.shift();
    if (!item.url) { playNext(); return; }
    const audio = new Audio(item.url);
    SPEECH.playing = audio;
    const done = () => {
        URL.revokeObjectURL(item.url);
        if (SPEECH.playing === audio) SPEECH.playing = null;
        playNext();
    };
    audio.onended = done;
    audio.onerror = done;
    audio.play().catch(done);
}

/** Settings → Voice → Preview. */
async function previewVoice() {
    try {
        const r = await fetch('/api/voice/speak', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: 'Hi, I\'m MrSOLIS. Ask me anything about your slides, and I\'ll explain it out loud.' }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || 'Voice unavailable');
        const url = URL.createObjectURL(await r.blob());
        const a = new Audio(url);
        a.onended = () => URL.revokeObjectURL(url);
        await a.play();
    } catch (e) { showToast(e.message); }
}

// Esc ends transcription and reading aloud
document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (DICT.mic) stopDictation(true);
    if (READ.part) stopReading();
});

// ══════════════════════════════════════════════════════════════════════
//   READ ALOUD — the button under each lesson / answer on the board
// ══════════════════════════════════════════════════════════════════════
const READ = { part: null };

function readAloud(part) {
    if (READ.part === part) { stopReading(); return; }          // pressing it again stops
    if (!VOICE.speak) { showToast('The voice model isn’t installed'); return; }
    silence();                                                   // one voice at a time
    READ.part = part;
    renderTalk();
    enqueue(speechText(part.text));
}

// headings and list lines become sentences of their own ("Worked Example." rather than run-on)
function speechText(md) {
    return md.split(/\n+/).map((l) => l.trim()).filter(Boolean)
        .map((l) => (/[.!?:;]["'”’)]?$/.test(l) ? l : l + '.')).join(' ');
}

function stopReading() {
    const was = READ.part;
    READ.part = null;
    silence();
    if (was) renderTalk();
}

// the voice queue ran dry: the reading is over
function doneReading() {
    if (!READ.part) return;
    READ.part = null;
    renderTalk();
}
