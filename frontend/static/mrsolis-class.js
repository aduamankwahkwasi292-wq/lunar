/* ═══════════════════════════════════════════════════════════════════
   MrSOLIS Interactive mode — a class at the blackboard.

   The student opens their slides and starts the class. MrSOLIS takes a full-screen blackboard and
   teaches the slides one after another: the lesson for each slide is NORMAL MODE'S OWN LESSON (the same
   words a student reads under the slide), written by hand on the board (static/mrsolis-board.js) a
   sentence at a time while that sentence is said. Maths is CUSTOM-Mx's: a question it sets up shows on
   the board with ▶ Run it / Skip (icOffer), and its exact working is written and said line by line.
   A slide is finished before the next: MrSOLIS says it is moving on, wipes the board and starts the
   next one.

   The student RAISES A HAND (✋, or H) to speak — the microphone is never on while MrSOLIS talks (the
   user, 2026-11-11: always listening, it heard its own voice: an echo, and the voice dipping). With the
   hand up, MrSOLIS stops talking and writing, listens, then answers (on the board when that helps) and
   picks the lesson up where it stopped. Said with the hand up: a question, or "continue", "say that
   again", "next slide", "go back", "slower", "faster", "end the class".

   Backend: backend/boardclass.py through /api/class/teach_stream and /api/class/ask_stream, which send
   steps: {board: [lines to write], say: "what is said", kind, gap, fin, offer, end}. The next
   slide is prepared while the current one is taught. The brain does one thing at a time: a question
   stops the preparing, which carries on afterwards from the next point.

   Uses Mic, micError and VOICE (mrsolis-voice.js) and S, $, streamNDJSON, showToast (mrsolis-wire.js).
   ═══════════════════════════════════════════════════════════════════ */
'use strict';

const IC = {
    on: false, run: 0,            // run: bumped when a class ends, so anything still in flight from it stops
    board: null, font: null,
    steps: [],                    // the class so far, in order: {board, say, slide, p, end}
    at: 0,                        // the step being taught
    scripts: {},                  // per slide: {steps, complete, title}
    loader: null,                 // {slide, ctrl}: the slide being prepared now
    count: 0, slide: -1, first: 0,
    token: null,                  // the step in progress: {cut, stop}
    audio: null,                  // the sentence being spoken
    paused: false,                // the student asked for a pause
    held: false,                  // stopped because the student's hand is up
    hand: null,                   // the raised hand: {heard, timer, quiet}
    mic: null,
    ask: null,                    // what the student said, waiting for its answer
    asking: false, answering: null,
    again: false, redo: false,    // "say that again"; say the step again without writing it again
    jump: null, wipe: false, skipSlide: -1,
    waiters: [],
    rate: 1, cc: true, finished: false, bridge: 0,
    voices: new Map(),            // sentence → Promise of its sound (an object URL), or null without a voice
};

const IC_TEXT = {
    preparing: 'Preparing the lesson…',
    teaching: () => (VOICE.hear ? 'Raise your hand ✋ to ask a question' : 'Type a question below to ask'),
    opening: 'Getting the microphone ready…',
    hearing: 'I’m listening — tap ✋ when you’re done',
    thinking: 'Thinking…',
    offer: 'Check CUSTOM-Mx’s setup — then Run it, or Skip',
    paused: 'Paused — press Space to carry on',
    done: 'That’s the lesson — raise your hand to ask, or end the class',
};
const IC_BRIDGES = ['Okay. Back to the lesson.', 'Good. Let’s carry on.', 'Right. Where were we?'];
const IC_CLOSING = 'And that is the end of the lesson. If anything was not clear, raise your hand and ask me, or end the class when you are ready.';

const icWake = () => { const w = IC.waiters; IC.waiters = []; w.forEach((f) => f()); };

function icState(state, caption) {
    const t = IC_TEXT[state];
    $('iclass').dataset.state = state;
    $('ic-state').textContent = typeof t === 'function' ? t() : t;
    if (caption !== undefined) icCaption(caption, state === 'hearing' || state === 'thinking');
}

function icCaption(text, theirs = false) {
    const el = $('ic-caption');
    el.textContent = text || '';
    el.classList.toggle('theirs', theirs);                  // what the student said, not MrSOLIS
    el.hidden = !text || (!IC.cc && !theirs);
}

// ══════════════════════════════════════════════════════════════════════
//   STARTING AND ENDING
// ══════════════════════════════════════════════════════════════════════
async function startClass() {
    if (IC.on || IC.starting) return;
    if (!S.sessionId) { showToast('Open your slides first — then MrSOLIS can teach them at the board', 4200); return; }
    IC.starting = true;
    if (typeof stopDictation === 'function') stopDictation();
    if (typeof stopReading === 'function') stopReading();
    if (S.busy) stopWriting();
    try {
        if (!IC.font) IC.font = await (await fetch('/static/board-font.json')).json();
    } catch (e) { IC.starting = false; showToast('The blackboard couldn’t be loaded'); return; }
    const run = ++IC.run;
    Object.assign(IC, {
        on: true, starting: false, steps: [], at: 0, scripts: {}, loader: null, count: S.count, slide: -1, token: null,
        audio: null, paused: false, held: false, hand: null, mic: null, ask: null, asking: false, answering: null,
        again: false, redo: false, jump: null, wipe: false, skipSlide: -1, waiters: [], finished: false, first: S.index,
        offer: null, offerChoice: null, history: [],
    });
    $('ic-run').hidden = true;
    $('ic-skip').hidden = true;
    try { IC.cc = localStorage.getItem('mrsolis-class-cc') !== '0'; } catch (e) { IC.cc = true; }
    const root = $('iclass');
    root.hidden = false;
    $('ic-cc').classList.toggle('on', IC.cc);
    $('ic-title').textContent = (S.filename || 'Your slides').replace(/\.[a-z0-9]+$/i, '');
    $('ic-progress').textContent = '';
    $('ic-ask').value = '';
    $('ic-hand').hidden = !VOICE.hear;
    icHandButton();
    icPauseButton();
    // the whole page goes full screen (not just the board), so the app's own messages still show over it
    try { await document.documentElement.requestFullscreen(); } catch (e) { /* a window-sized board is fine too */ }
    if (run !== IC.run) return;
    IC.board = new Blackboard($('ic-board'), IC.font, { em: 46 });   // the lesson is whole sentences: a smaller hand
    IC.board.rate = IC.rate;
    icState('preparing', '');
    if (!VOICE.speak) showToast('The voice model isn’t installed — the class will be written, not spoken', 5000);
    icLoad(IC.first);
    icDirect(run);
}

function endClass() {
    if (!IC.on) return;
    IC.on = false;
    IC.run++;
    icCloseHand();
    if (IC.offerChoice) IC.offerChoice(null);
    if (IC.loader) IC.loader.ctrl.abort();
    if (IC.answering) IC.answering.abort();
    IC.loader = null;
    if (IC.token) { IC.token.cut = true; if (IC.token.stop) IC.token.stop(); }
    if (IC.audio) { try { IC.audio.pause(); } catch (e) { /* gone */ } IC.audio = null; }
    icWake();
    if (IC.board) IC.board.destroy();
    IC.board = null;
    IC.voices.forEach((p) => p.then((url) => url && URL.revokeObjectURL(url)).catch(() => {}));
    IC.voices.clear();
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    $('iclass').hidden = true;
    // the classroom behind the board opens the slide the class reached
    if (S.sessionId && IC.slide >= 0 && IC.slide !== S.index) teachSlide(IC.slide);
    else { try { updateProgress(); } catch (e) { /* the sidebar ring catches up on the next slide */ } }
}

// ══════════════════════════════════════════════════════════════════════
//   PREPARING THE LESSON — one slide at a time, a little ahead of the teaching
// ══════════════════════════════════════════════════════════════════════
async function icLoad(k) {
    if (!IC.on || IC.loader || k >= IC.count) return;
    const script = IC.scripts[k] || (IC.scripts[k] = { steps: [], complete: false, title: '' });
    if (script.complete) return;
    const ctrl = new AbortController(), run = IC.run;
    IC.loader = { slide: k, ctrl };
    try {
        await streamNDJSON('/api/class/teach_stream', {
            session_id: S.sessionId, slide_index: k,
            done: script.steps.map((s) => ({ kind: s.kind, board: s.board, say: s.say, md: s.md, gap: s.gap, fin: s.fin, offer: s.offer, end: s.end })),
        }, (msg) => {
            if (run !== IC.run) return;
            if (msg.slide) script.title = msg.slide.title || '';
            else if (msg.step) {
                const step = { ...msg.step, board: msg.step.board || [], say: msg.step.say || '', slide: k, end: !!msg.step.end };
                script.steps.push(step);
                IC.steps.push(step);
                icWake();
            } else if (msg.done) script.complete = true;
            else if (msg.error) throw new Error(msg.error);
        }, ctrl.signal);
    } catch (e) {
        if (run !== IC.run) return;
        if (e.name !== 'AbortError') {                      // this slide can't be taught: say so once, move on
            script.complete = true;
            showToast(`MrSOLIS couldn’t prepare slide ${k + 1}: ${e.message}`, 5000);
        }
    }
    if (run !== IC.run) return;
    if (IC.loader && IC.loader.ctrl === ctrl) IC.loader = null;
    icWake();
    icAhead();
}

/** Prepare the next slide that isn't ready — but no further than one beyond the slide being taught. */
function icAhead(starved = false) {
    if (!IC.on || IC.loader || IC.asking || IC.hand) return;
    for (let k = Math.max(IC.first, IC.slide); k < IC.count; k++) {
        if (IC.scripts[k] && IC.scripts[k].complete) continue;
        if (starved || k <= IC.slide + 1) icLoad(k);
        return;
    }
}

const icMore = () => { for (let k = IC.first; k < IC.count; k++) if (!(IC.scripts[k] && IC.scripts[k].complete)) return true; return false; };

/** The step to teach now; null when the class has run out; 'poke' when something else needs attention. */
function icNext(run) {
    return new Promise((resolve) => {
        const check = () => {
            if (run !== IC.run || !IC.on) return resolve(null);
            if (IC.ask || IC.jump !== null) return resolve('poke');
            if (IC.at < IC.steps.length) return resolve(IC.steps[IC.at]);
            if (!icMore()) return resolve(null);
            if (!IC.hand) icState('preparing');
            icAhead(true);
            IC.waiters.push(check);
        };
        check();
    });
}

// ══════════════════════════════════════════════════════════════════════
//   TEACHING
// ══════════════════════════════════════════════════════════════════════
async function icDirect(run) {
    while (IC.on && run === IC.run) {
        if (IC.jump !== null) {                             // "next slide" / "go back"
            IC.at = IC.jump; IC.jump = null; IC.redo = false; IC.finished = false;
            if (IC.wipe) { IC.wipe = false; await IC.board.erase(); IC.slide = -1; }
            continue;
        }
        if (IC.ask) { const q = IC.ask; IC.ask = null; await icAnswer(q, run); continue; }
        if (IC.hand) { await new Promise((r) => IC.waiters.push(r)); continue; }   // listening: the class waits
        const step = await icNext(run);
        if (run !== IC.run) return;
        if (step === 'poke') continue;
        if (!step) {
            if (!IC.finished) { IC.finished = true; await icTeach({ board: [], say: IC_CLOSING, slide: IC.slide }, run); continue; }
            icState('done');
            await new Promise((r) => IC.waiters.push(r));    // a question, or "go back"
            continue;
        }
        if (step.slide === IC.skipSlide) { IC.at++; continue; }
        if (step.slide !== IC.slide) {                       // a new slide: a clean board, like a teacher's
            if (IC.slide >= 0 && IC.board.lines.length) await IC.board.erase();
            if (run !== IC.run) return;
            icEnter(step.slide);
        }
        const whole = await icTeach(step, run, { sayOnly: IC.redo });
        if (run !== IC.run) return;
        if (whole && step.offer && !IC.redo) await icOffer(step.offer, run);   // CUSTOM-Mx's setup: the student checks it
        if (run !== IC.run) return;
        IC.redo = false;
        if (IC.again) { IC.again = false; IC.redo = true; continue; }
        if (IC.jump !== null) continue;
        if (IC.ask || IC.hand) { IC.redo = !whole; if (whole) IC.at++; continue; }
        if (whole) IC.at++;
    }
}

function icEnter(k) {
    IC.slide = k;
    IC.skipSlide = -1;
    $('ic-progress').textContent = `Slide ${k + 1} of ${IC.count}`;
    icAhead();
}

const icSentences = (text) => {
    const clean = String(text || '').replace(/[*#_`]+/g, '').replace(/\s+/g, ' ').trim();
    const parts = clean.split(/(?<=[.!?])\s+(?=["'“(]?[A-Z0-9])/).filter((p) => /[a-z0-9]/i.test(p));
    const out = [];
    for (const p of parts) {                                 // a very short sentence rides with the next one
        if (out.length && out[out.length - 1].length < 28) out[out.length - 1] += ' ' + p; else out.push(p);
    }
    return out;
};

/** The sound of a sentence (fetched once; null when there is no voice). */
function icVoice(text) {
    if (!VOICE.speak) return Promise.resolve(null);
    if (!IC.voices.has(text)) {
        IC.voices.set(text, fetch('/api/voice/speak', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }),
        }).then(async (r) => (r.ok && r.status !== 204 ? URL.createObjectURL(await r.blob()) : null)).catch(() => null));
    }
    return IC.voices.get(text);
}

const icSleep = (ms, tk) => new Promise((resolve) => {
    let waited = 0, last = performance.now();
    const tick = () => {                                     // time stands still while the class is stopped
        const now = performance.now();
        if (!IC.paused && !IC.held) waited += now - last;
        last = now;
        if (tk.cut || waited >= ms) resolve(); else setTimeout(tick, 80);
    };
    tick();
});

function icPlay(url, text, tk) {
    return new Promise((resolve) => {
        const a = new Audio(url);
        a.playbackRate = IC.rate;
        a.volume = 1;
        IC.audio = a;
        icCaption(text);
        let at = -1, still = 0;
        const done = () => {
            clearInterval(watch);
            try { a.pause(); } catch (e) { /* gone */ }      // never two voices at once
            if (IC.audio === a) IC.audio = null;
            tk.stop = null;
            resolve();
        };
        // a sound that stops moving without ending (seen in a background window) must not stop the class
        const watch = setInterval(() => {
            if (a.paused || IC.paused || IC.held) { still = 0; return; }
            if (a.currentTime !== at) { at = a.currentTime; still = 0; } else if (++still >= 6) done();
        }, 500);
        a.onended = done;
        a.onerror = done;
        tk.stop = done;
        if (!IC.paused && !IC.held) a.play().catch(done);    // otherwise icGo() starts it
    });
}

async function icSay(pieces, tk) {
    for (const p of pieces) {
        const url = await icVoice(p);
        if (tk.cut) return;
        if (url) await icPlay(url, p, tk);
        else { icCaption(p); await icSleep(Math.max(1200, p.length * 62) / IC.rate, tk); }
        if (tk.cut) return;
    }
}

/** Teach one step: write its lines while saying what they mean. False if it was cut short. */
async function icTeach(step, run, opts = {}) {
    const tk = IC.token = { cut: false, stop: null };
    const pieces = icSentences(step.say);
    const next = IC.steps[IC.at + 1];
    if (pieces[0]) await icVoice(pieces[0]);                 // pen and voice start together
    if (next && !opts.answer) { const n = icSentences(next.say)[0]; if (n) icVoice(n); }   // no gap before the next step
    if (tk.cut || run !== IC.run) return false;
    if (!IC.paused && !IC.held) icState('teaching');
    const lines = opts.sayOnly ? [] : (step.board || []);
    if (lines.length && step.gap) IC.board.space(0.45);       // a new paragraph of the lesson
    const letters = lines.reduce((n, l) => n + l.length, 0) || 1;
    const time = Math.max(1500, String(step.say).length * 64) / IC.rate * 0.92;      // about how long the saying takes
    const writes = lines.map((l) => IC.board.write(l, {
        duration: time * l.length / letters, color: opts.color || step.color, indent: opts.indent, scale: step.scale,
    }));
    await Promise.all([icSay(pieces, tk), ...writes]);
    if (IC.token === tk) IC.token = null;
    return !tk.cut && run === IC.run;
}

/** Stop the step in progress at once (the student wants something). What was being written is finished. */
function icCut() {
    const tk = IC.token;
    if (tk) { tk.cut = true; if (tk.stop) tk.stop(); }
    if (IC.board) IC.board.finish();
    icWake();
}

/** CUSTOM-Mx has set up a question (the slide's, or the student's): the student checks the setup on the board,
 *  then Run it (CUSTOM-Mx works it exactly, line by line) or Skip. Word problems are never worked unchecked. */
async function icOffer(offer, run) {
    IC.offer = offer;
    $('ic-run').hidden = false;
    $('ic-skip').hidden = false;
    icState('offer');
    const choice = await new Promise((resolve) => { IC.offerChoice = resolve; });
    IC.offerChoice = null;
    IC.offer = null;
    $('ic-run').hidden = true;
    $('ic-skip').hidden = true;
    if (choice !== 'run' || run !== IC.run || !IC.on) return;
    icState('thinking', '');
    let res = null;
    try {
        const r = await fetch('/api/class/run', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command: offer.command }),
        });
        res = await r.json();
        if (!r.ok) throw new Error(res.detail || `failed (${r.status})`);
    } catch (e) {
        showToast(`CUSTOM-Mx couldn’t work it: ${e.message}`, 4500);
        return;
    }
    for (const s of res.steps || []) {
        if (!(await icTeach(s, run)) || IC.ask || IC.jump !== null) break;
    }
}

function icStop() {                                          // freeze: the voice and the pen stop where they are
    if (IC.audio) { try { IC.audio.pause(); } catch (e) { /* gone */ } }
    if (IC.board) IC.board.pause();
}

function icGo() {                                            // carry on from the freeze
    if (!IC.on || IC.paused || IC.held) return;
    if (IC.audio) IC.audio.play().catch(() => {});
    if (IC.board) IC.board.resume();
    icWake();
    const s = $('iclass').dataset.state;
    if (s === 'paused' || s === 'hearing' || s === 'opening') {
        icState(IC.asking ? 'thinking' : IC.finished && IC.at >= IC.steps.length ? 'done' : 'teaching');
    }
}

function icPause(on) {
    IC.paused = on;
    icPauseButton();
    if (on) { icStop(); icState('paused'); } else icGo();
}

function icPauseButton() {
    $('ic-pause').innerHTML = `<svg class="ico"><use href="#${IC.paused ? 'i-play' : 'i-pause'}"/></svg>`;
    $('ic-pause').title = IC.paused ? 'Carry on (Space)' : 'Pause (Space)';
}

// ══════════════════════════════════════════════════════════════════════
//   THE STUDENT RAISES A HAND
// ══════════════════════════════════════════════════════════════════════
function icLevel(level) {
    const bars = $('ic-ear').children;
    for (let i = 0; i < bars.length; i++) {
        const shape = 1 - Math.abs(i - 2) / 3;
        bars[i].style.setProperty('--h', Math.min(1, level * (0.5 + shape * 0.7) * (0.75 + Math.random() * 0.5)).toFixed(2));
    }
}

function icHandButton() {
    const up = !!IC.hand;
    $('ic-hand').classList.toggle('up', up);
    $('ic-hand').querySelector('span').textContent = up ? 'Done' : 'Raise hand';
    $('ic-hand').title = up ? 'Done talking (H) — or wait a moment and MrSOLIS answers' : 'Raise your hand to ask a question (H)';
}

/** ✋: the teacher stops talking and writing, then listens. Pressed again: done talking. */
async function icRaiseHand() {
    if (!IC.on) return;
    if (IC.hand) { icHandDone(); return; }
    if (!VOICE.hear) { $('ic-ask').focus(); return; }
    const hand = IC.hand = { heard: [], partial: '', timer: null, quiet: null };
    IC.held = true;
    icStop();                                                // silence first: the microphone never hears MrSOLIS
    icHandButton();
    icState('opening', '');
    const mic = IC.mic = new Mic('live', icHeard, icLevel);
    try {
        await mic.start();
    } catch (e) {
        if (IC.mic === mic) { IC.mic = null; micError(e); icLowerHand(); }
        return;
    }
    if (IC.hand !== hand || IC.mic !== mic) { mic.stop(); return; }    // lowered while the microphone started
    icState('hearing', '');
    hand.quiet = setTimeout(() => icLowerHand('I didn’t hear anything — carrying on'), 10000);
}

function icHeard(ev) {
    const hand = IC.hand;
    if (!hand || !IC.on) return;
    if (ev.type === 'speech_start') {
        clearTimeout(hand.quiet);
        clearTimeout(hand.timer);
    } else if (ev.type === 'partial') {
        hand.partial = ev.text || '';
        icCaption(`“${[...hand.heard, hand.partial].join(' ').trim()}”`, true);
    } else if (ev.type === 'final') {
        hand.partial = '';
        if (ev.text && ev.text.trim()) hand.heard.push(ev.text.trim());
        icCaption(hand.heard.length ? `“${hand.heard.join(' ')}”` : '', true);
        clearTimeout(hand.timer);
        hand.timer = setTimeout(icHandDone, 1500);         // they stopped talking: that was the question
    }
}

/** The student finished: what they said goes to the teacher (a question, or a word like "continue"). */
function icHandDone() {
    const hand = IC.hand;
    if (!hand) return;
    const text = [...hand.heard, hand.partial].join(' ').trim();
    icCloseHand();
    if (!text) { IC.held = false; icGo(); return; }
    icStudent(text);
}

function icLowerHand(note) {
    icCloseHand();
    IC.held = false;
    if (note) showToast(note, 2600);
    icGo();
}

function icCloseHand() {
    const hand = IC.hand;
    IC.hand = null;
    if (hand) { clearTimeout(hand.timer); clearTimeout(hand.quiet); }
    if (IC.mic) { IC.mic.stop(); IC.mic = null; }            // the microphone is off before MrSOLIS speaks again
    icLevel(0);
    if (IC.on) icHandButton();
    icWake();
}

/** Something the student said (or typed): a word to the teacher, or a question. */
function icStudent(text) {
    const t = String(text || '').toLowerCase().replace(/[^a-z0-9\s']/g, ' ').replace(/\s+/g, ' ').trim();
    IC.held = false;
    if (IC.offer && IC.offerChoice) {                        // CUSTOM-Mx's setup is waiting for the student's check
        if (/^(yes|yeah|yep|run|run it|correct|that's right|thats right|it's right|right|go ahead|work it out)$/.test(t)) { IC.offerChoice('run'); return; }
        if (/^(no|nope|skip|skip it|wrong|that's wrong|not right|never ?mind)$/.test(t)) { IC.offerChoice('skip'); return; }
        IC.offerChoice('skip');                              // anything else is a new question or a word to the teacher
    }
    if (!t) { icGo(); return; }
    if (/^(end|stop|close|exit|leave|finish) (the |this )?(class|lesson|interactive mode)$|^goodbye$/.test(t)) { endClass(); return; }
    if (/^(stop|wait|pause|hold on|one moment|one second|just a (moment|second|minute)|okay (stop|wait))$/.test(t)) { icPause(true); return; }
    if (/^((okay |ok |please |you can )?(continue|go on|carry on|resume|keep going|go ahead|proceed)|okay|ok|yes|yeah|alright|all right|no|nothing|never ?mind|no question|sorry)$/.test(t)) { icPause(false); return; }
    if (/^(repeat|repeat that|say (it|that) again|come again|pardon|can you repeat( that)?)$/.test(t)) { IC.paused = false; icPauseButton(); IC.again = true; icGo(); icCut(); return; }
    if (/^(next|skip|skip (this|that|it)|move on|next (slide|part|topic|one)|go to the next slide)$/.test(t)) { icSkip(1); return; }
    if (/^(go back|back|previous|previous (slide|part|topic|one)|start (this|that|it) again)$/.test(t)) { icSkip(-1); return; }
    if (/^(slower|slow down|too fast|you('re| are) (going )?too fast)$/.test(t)) { icPace(-1); return; }
    if (/^(faster|speed up|too slow)$/.test(t)) { icPace(1); return; }
    if (/^(thank you|thanks|i see|got it|i understand|makes sense|that makes sense|mhm|uh huh|hmm|oh|wow|nice|cool|great)$/.test(t)) { icGo(); return; }
    IC.paused = false;                                       // anything else is for the teacher to answer
    icPauseButton();
    IC.ask = String(text).trim();
    if (IC.board) IC.board.resume();
    icState('thinking', `“${IC.ask}”`);
    icCut();
}

function icSkip(dir) {
    IC.paused = false;
    icPauseButton();
    const here = IC.slide;
    if (dir > 0) {
        let j = IC.steps.findIndex((s, i) => i > IC.at && s.slide > here);
        if (j < 0) {                                         // the next slide isn't prepared yet: drop the rest of this one
            if (here >= IC.count - 1 && !icMore()) { showToast('That’s the last slide'); icGo(); return; }
            IC.skipSlide = here;
            if (IC.loader && IC.loader.slide === here) { IC.loader.ctrl.abort(); IC.loader = null; }
            (IC.scripts[here] || (IC.scripts[here] = { steps: [], title: '' })).complete = true;
            j = IC.steps.length;
        }
        IC.jump = j;
    } else {
        const first = IC.steps.findIndex((s) => s.slide === here);
        let to = Math.max(0, first);
        if (IC.at <= first + 1 && first > 0) to = IC.steps.findIndex((s) => s.slide === IC.steps[first - 1].slide);
        IC.jump = Math.max(0, to);
        IC.wipe = true;
    }
    if (IC.board) IC.board.resume();
    icCut();
}

function icPace(dir) {
    IC.rate = Math.max(0.7, Math.min(1.45, IC.rate + dir * 0.15));
    if (IC.board) IC.board.rate = IC.rate;
    if (IC.audio) IC.audio.playbackRate = IC.rate;
    showToast(dir < 0 ? 'Slower' : 'Faster');
    icGo();
}

/** Answer what the student asked, then hand the class back. */
async function icAnswer(question, run) {
    IC.asking = true;
    if (IC.loader) { IC.loader.ctrl.abort(); IC.loader = null; }    // the brain answers now; preparing ahead waits
    icState('thinking', `“${question}”`);
    IC.board.resume();
    IC.board.space(0.3);
    IC.board.write('? ' + question, { color: 'purple', scale: 0.74, indent: 0.5, kind: 'plain' });   // what was heard
    const queue = [], said = [];
    let finished = false, failed = null, taught = 0;
    const ctrl = IC.answering = new AbortController();
    streamNDJSON('/api/class/ask_stream', {
        session_id: S.sessionId, slide_index: IC.slide >= 0 ? IC.slide : IC.first, message: question, board: IC.board.lines.slice(-9, -1),
        history: IC.history.slice(-6),
    }, (msg) => {
        if (msg.step) { queue.push(msg.step); icWake(); } else if (msg.error) throw new Error(msg.error);
    }, ctrl.signal).catch((e) => { if (e.name !== 'AbortError') failed = e; }).finally(() => { finished = true; icWake(); });
    while (IC.on && run === IC.run && !IC.ask && IC.jump === null) {
        if (IC.hand) { await new Promise((r) => IC.waiters.push(r)); continue; }
        if (!queue.length) {
            if (finished) break;
            await new Promise((r) => IC.waiters.push(r));
            continue;
        }
        const step = queue.shift();
        const whole = await icTeach({ ...step, board: step.board || [], say: step.say || '', slide: IC.slide }, run,
            { color: step.kind === 'answer' ? 'orange' : undefined, indent: 0.5, answer: true });
        taught++;
        said.push(step.say || '');
        if (whole && step.offer) await icOffer(step.offer, run);
        if (!whole && !IC.hand) break;
    }
    if (said.length) IC.history.push({ role: 'user', content: question }, { role: 'assistant', content: said.join(' ').slice(0, 600) });
    ctrl.abort();
    if (IC.answering === ctrl) IC.answering = null;
    IC.asking = false;
    if (!IC.on || run !== IC.run) return;
    if (IC.again) { IC.again = false; IC.redo = true; }
    if (failed && !taught) showToast(`MrSOLIS couldn’t answer: ${failed.message}`, 5000);
    if (!IC.ask && IC.jump === null && !IC.redo) {
        const back = failed && !taught ? 'Sorry, I could not answer that just now. Let’s carry on.'
            : IC.finished ? '' : IC_BRIDGES[IC.bridge++ % IC_BRIDGES.length];
        if (back) await icTeach({ board: [], say: back, slide: IC.slide }, run, { answer: true });
    }
    if (IC.board) IC.board.space(0.3);
    icAhead();
}

// ══════════════════════════════════════════════════════════════════════
//   BUTTONS AND KEYS
// ══════════════════════════════════════════════════════════════════════
$('ic-start').addEventListener('click', startClass);
$('iclass').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) b.blur(); });
$('ic-end').addEventListener('click', endClass);
$('ic-hand').addEventListener('click', icRaiseHand);
$('ic-run').addEventListener('click', () => IC.offerChoice && IC.offerChoice('run'));
$('ic-skip').addEventListener('click', () => IC.offerChoice && IC.offerChoice('skip'));
$('ic-pause').addEventListener('click', () => icPause(!IC.paused));
$('ic-back').addEventListener('click', () => icStudent('say that again'));
$('ic-cc').addEventListener('click', () => {
    IC.cc = !IC.cc;
    $('ic-cc').classList.toggle('on', IC.cc);
    try { localStorage.setItem('mrsolis-class-cc', IC.cc ? '1' : '0'); } catch (e) { /* not kept */ }
    if (!IC.cc) $('ic-caption').hidden = !$('ic-caption').classList.contains('theirs');
});
$('ic-ask').addEventListener('focus', () => { if (IC.on && !IC.hand) { IC.held = true; icStop(); } });   // typing: the teacher waits
$('ic-ask').addEventListener('blur', () => { if (IC.on && !IC.hand && !IC.ask) { IC.held = false; icGo(); } });
$('ic-ask').addEventListener('keydown', (e) => {
    e.stopPropagation();
    if (e.key === 'Enter' && e.target.value.trim()) { const q = e.target.value; e.target.value = ''; IC.ask = '…'; e.target.blur(); IC.ask = null; icStudent(q); }
    else if (e.key === 'Escape') e.target.blur();
});
document.addEventListener('keydown', (e) => {
    if (!IC.on || e.target.id === 'ic-ask') return;
    if (e.key === 'Escape') { e.preventDefault(); endClass(); }
    else if (e.key === ' ') { e.preventDefault(); icPause(!IC.paused); }
    else if (e.key === 'h' || e.key === 'H') { e.preventDefault(); icRaiseHand(); }
    else if (IC.offerChoice && (e.key === 'Enter' || e.key === 'r' || e.key === 'R')) { e.preventDefault(); IC.offerChoice('run'); }
    else if (IC.offerChoice && (e.key === 's' || e.key === 'S')) { e.preventDefault(); IC.offerChoice('skip'); }
}, true);

// the button shows once slides are open
setInterval(() => { const b = $('ic-start'); if (b.hidden !== !S.sessionId) b.hidden = !S.sessionId; }, 500);

COMMANDS.push({
    name: 'class', alias: ['interactive', 'board', 'teach'],
    desc: 'Interactive mode — MrSOLIS teaches your slides at a blackboard, out loud; raise your hand to ask',
    run: () => startClass(),
});
