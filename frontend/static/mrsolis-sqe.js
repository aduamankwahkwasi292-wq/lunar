'use strict';
/* ═══════════════════════════════════════════════════════════════════
   The SQE window: MrSOLIS 2-AL inside MrSOLIS 3. The student brings one maths question; CUSTOM-SQE
   (backend/sqe, /api/sqe/*) makes fresh versions of it with new numbers and works every answer out exactly.
   One question at a time, a live score, an optional timer, then the working for every question.
   ═══════════════════════════════════════════════════════════════════ */
(() => {
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
    const icon = (id) => `<svg class="ico"><use href="#i-${id}"/></svg>`;
    const say = (id, text, kind = '') => { $(id).textContent = text; $(id).className = 'msg ' + kind; };

    async function api(path, body) {
        const r = await fetch(path, body ? { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) } : {});
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
    }

    /** Maths text as students read it: x^2 → x², sqrt( → √(, pi → π, -> → →, <= → ≤ … (escaped first). */
    function pretty(text) {
        let s = esc(text);
        s = s.replace(/\bsqrt\(/g, '√(').replace(/\bpi\b/g, 'π').replace(/-&gt;/g, '→')
            .replace(/&lt;=/g, '≤').replace(/&gt;=/g, '≥').replace(/!=/g, '≠').replace(/\b(?:infinity|oo)\b/g, '∞');
        s = s.replace(/\^\(([^()]{1,24})\)/g, '<sup>$1</sup>').replace(/\^(-?[\w.]+)/g, '<sup>$1</sup>');
        return s.replace(/(\d)\*(?=[a-zA-Z(])/g, '$1').replace(/\*/g, '×');
    }

    const KINDS = { word_problem: 'Word problem', differentiation: 'Differentiation', integration: 'Integration', limit: 'Limits',
        algebra: 'Algebra', proof: 'Proof', inequalities: 'Inequalities', indices: 'Indices, surds and logs', number: 'Number',
        sequences: 'Sequences and series', statistics: 'Statistics and probability', trigonometry: 'Trigonometry',
        coordinates: 'Coordinates and vectors', matrices: 'Matrices', complex: 'Complex numbers' };
    const kindName = (k) => KINDS[k] || (k ? k.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()) : 'Maths');
    const EXAMPLES = [
        'Differentiate f(x) = 3x^2 + 2x',
        'Solve 2x + 3 = 11',
        'A lamp uses 200 W of power at 100 V. Calculate the current.',
        'Find the simple interest on GHS 5000 at 8% per annum for 3 years.',
        'Factorise x^2 - 7x + 12',
        'Find the mean of 4, 8, 6, 10, 12',
        'Find the 20th term of the AP 3, 7, 11, ...',
        'Evaluate lim x->2 of (x^2 - 4)/(x - 2)',
    ];

    const S = {
        n: 10, minutes: 0, mode: 'choose', busy: false,
        session: Math.random().toString(36).slice(2) + Date.now().toString(36),   // nothing repeats in this window
        question: '', items: [], i: 0, answers: [], answered: false, endAt: 0, timer: null, timeUp: false, kbTarget: 'q',
    };
    const score = () => S.answers.filter((a) => a && a.ok).length;

    function show(view) {
        for (const v of ['vStart', 'vRun', 'vReview']) $(v).hidden = v !== view;
        $('sqe-stage').scrollTop = 0;
    }

    function seg(el, options, value, pick) {
        el.innerHTML = options.map(([v, label]) => `<button type="button" data-v="${v}" class="${String(v) === String(value) ? 'on' : ''}">${label}</button>`).join('');
        el.addEventListener('click', (e) => {
            const b = e.target.closest('button');
            if (!b) return;
            el.querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b));
            pick(b.dataset.v);
        });
    }

    // ── start ────────────────────────────────────────────────────────────────────────
    seg($('segN'), [[5, '5'], [10, '10'], [15, '15'], [20, '20']], S.n, (v) => { S.n = +v; });
    seg($('segT'), [[0, 'Off'], [5, '5 min'], [10, '10 min'], [20, '20 min']], S.minutes, (v) => { S.minutes = +v; });
    seg($('segA'), [['choose', 'Choose'], ['type', 'Type']], S.mode, (v) => { S.mode = v; });
    $('examples').insertAdjacentHTML('beforeend', EXAMPLES.map((q) => `<button type="button" class="ex-chip" data-q="${esc(q)}">${pretty(q)}</button>`).join(''));
    $('examples').addEventListener('click', (e) => {
        const b = e.target.closest('.ex-chip');
        if (!b) return;
        $('q').value = b.dataset.q;
        $('q').focus();
        say('startMsg', '');
    });

    async function make(question) {
        if (S.busy) return;
        S.busy = true;
        $('go').disabled = $('again').disabled = true;
        say('startMsg', 'Making your practice…');
        try {
            const r = await api('/api/sqe/generate', { question, n: S.n, session: S.session });
            if (!r.ok) { show('vStart'); say('startMsg', r.message || 'CUSTOM-SQE couldn’t read that question.', 'bad'); return; }
            S.question = question;
            S.items = r.questions;
            S.original = r.original || null;                // the student's own question, answered
            S.understood = r.understood || '';              // how a word problem was read ("P = VI, finding the current")
            S.i = 0;
            S.answers = [];
            S.timeUp = false;
            say('startMsg', '');
            show('vRun');
            startTimer();
            renderQuestion();
        } catch (_) {
            show('vStart');
            say('startMsg', 'MrSOLIS couldn’t reach its maths engine. Is MrSOLIS still open?', 'bad');
        } finally {
            S.busy = false;
            $('go').disabled = $('again').disabled = false;
        }
    }
    $('go').addEventListener('click', () => {
        const q = $('q').value.trim();
        if (!q) { $('q').focus(); say('startMsg', 'Type or paste a maths question first, or try one of the examples.'); return; }
        make(q);
    });
    $('q').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || !e.shiftKey)) { e.preventDefault(); $('go').click(); } });

    // ── practice ─────────────────────────────────────────────────────────────────────
    function renderQuestion() {
        const it = S.items[S.i];
        S.answered = false;
        $('rNum').textContent = `Question ${S.i + 1} of ${S.items.length}`;
        $('rBar').style.width = `${(S.i / S.items.length) * 100}%`;
        $('rScore').textContent = `Score ${score()} / ${S.i}`;
        $('rKind').textContent = kindName(it.fact_type);
        $('rQ').innerHTML = pretty(it.question);
        $('rRead').hidden = !S.understood;                  // so a misread word problem is plain to see
        $('rRead').innerHTML = S.understood ? `Read as: <b>${pretty(S.understood)}</b>` : '';
        $('rFeedback').innerHTML = '';
        $('rFeedback').className = 'feedback';
        $('rNext').hidden = true;
        const proof = it.fact_type === 'proof';
        const mcq = !proof && S.mode === 'choose' && Array.isArray(it.options) && it.options.length >= 2;
        $('rOptions').hidden = !mcq;
        $('rTyped').hidden = mcq || proof;
        $('rSelf').hidden = !proof;
        $('rSelfMark').hidden = true;
        $('rReveal').hidden = false;
        if (mcq) {
            $('rOptions').innerHTML = it.options.map((o, k) => `<button type="button" class="opt" data-k="${k}"><span class="key">${'ABCD'[k] || k + 1}</span><span>${pretty(o)}</span></button>`).join('');
        } else if (!proof) {
            $('rAns').value = '';
            $('rAns').disabled = $('rCheck').disabled = false;
            $('rAns').focus();
            S.kbTarget = 'rAns';
        }
    }

    function mark(ok, given) {
        if (S.answered) return;
        const it = S.items[S.i];
        S.answered = true;
        S.answers[S.i] = { ok, given };
        $('rScore').textContent = `Score ${score()} / ${S.i + 1}`;
        $('rFeedback').className = 'feedback ' + (ok ? 'good' : 'bad');
        $('rFeedback').innerHTML = it.fact_type === 'proof' ? (ok ? 'Well done.' : 'Keep at it — compare yours with the working at the end.')
            : ok ? `${icon('check')} Correct.` : `Not quite. The answer is <b>${pretty(it.answer)}</b>.`;
        $('rNext').hidden = false;
        $('rNext').innerHTML = S.i + 1 < S.items.length ? `Next${icon('arrow')}` : `See your score${icon('arrow')}`;
        $('rNext').focus();
    }

    $('rOptions').addEventListener('click', (e) => {
        const b = e.target.closest('.opt');
        if (!b || S.answered) return;
        const it = S.items[S.i];
        const chosen = it.options[+b.dataset.k];
        const ok = chosen === it.answer;
        $('rOptions').querySelectorAll('.opt').forEach((x) => {
            x.disabled = true;
            if (it.options[+x.dataset.k] === it.answer) x.classList.add('right');
        });
        if (!ok) b.classList.add('wrong');
        mark(ok, chosen);
    });

    async function checkTyped() {
        if (S.answered) return;
        const given = $('rAns').value.trim();
        if (!given) { $('rAns').focus(); return; }
        const it = S.items[S.i];
        $('rCheck').disabled = true;
        let ok = false;
        try { ok = !!(await api('/api/sqe/check', { given, correct: it.answer, kind: it.fact_type || '' })).correct; } catch (_) { ok = false; }
        $('rAns').disabled = true;
        mark(ok, given);
    }
    $('rCheck').addEventListener('click', checkTyped);
    $('rAns').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); checkTyped(); } });

    $('rReveal').addEventListener('click', () => {
        const it = S.items[S.i];
        $('rReveal').hidden = true;
        $('rFeedback').className = 'feedback';
        $('rFeedback').innerHTML = `<div class="silver steps">${stepsHtml(it)}</div>`;
        $('rSelfMark').hidden = false;
    });
    $('rGotIt').addEventListener('click', () => mark(true, 'self-marked'));
    $('rNotYet').addEventListener('click', () => mark(false, 'self-marked'));

    function next() {
        if (!S.answered) return;
        if (S.i + 1 < S.items.length) { S.i++; renderQuestion(); } else finish(false);
    }
    $('rNext').addEventListener('click', next);

    document.addEventListener('keydown', (e) => {
        if ($('vRun').hidden || !$('confirm').hidden) return;
        const typing = document.activeElement && document.activeElement.tagName === 'INPUT';
        if (S.answered && e.key === 'Enter' && !typing) { e.preventDefault(); next(); return; }
        if (!S.answered && !$('rOptions').hidden && !typing) {
            const k = '1234'.indexOf(e.key) >= 0 ? '1234'.indexOf(e.key) : 'abcd'.indexOf(e.key.toLowerCase());
            const b = k >= 0 && $('rOptions').querySelector(`.opt[data-k="${k}"]`);
            if (b) b.click();
        }
    });

    // the timer, for the whole practice
    function startTimer() {
        clearInterval(S.timer);
        $('rTimer').hidden = !S.minutes;
        if (!S.minutes) return;
        S.endAt = Date.now() + S.minutes * 60000;
        tick();
        S.timer = setInterval(tick, 500);
    }
    function tick() {
        const left = Math.max(0, S.endAt - Date.now());
        $('rTimer').querySelector('b').textContent = `${Math.floor(left / 60000)}:${String(Math.floor((left % 60000) / 1000)).padStart(2, '0')}`;
        $('rTimer').classList.toggle('low', left < 60000);
        if (left <= 0) { clearInterval(S.timer); S.timeUp = true; finish(true); }
    }

    $('exit').addEventListener('click', () => { $('confirm').hidden = false; $('leaveNo').focus(); });
    $('leaveNo').addEventListener('click', () => { $('confirm').hidden = true; });
    $('leaveYes').addEventListener('click', () => {
        $('confirm').hidden = true;
        clearInterval(S.timer);
        show('vStart');
        $('q').focus();
    });

    // ── review ───────────────────────────────────────────────────────────────────────
    function stepsHtml(it) {
        const steps = Array.isArray(it.steps) ? it.steps : [];
        return steps.length ? `<ol>${steps.map((s) => `<li>${pretty(s)}</li>`).join('')}</ol>` : `<p>${pretty(it.answer)}</p>`;
    }

    function finish(timeUp) {
        clearInterval(S.timer);
        const total = S.items.length;
        const got = score();
        $('vScore').textContent = `${got} / ${total}`;
        $('vSub').textContent = `${total ? Math.round((got / total) * 100) : 0}% · from your question “${S.question}”${timeUp ? ' · time ran out' : ''}`;
        $('reviewList').innerHTML = S.items.map((it, k) => {
            const a = S.answers[k];
            const ok = a && a.ok;
            const yours = !a ? 'Not answered' : a.given === 'self-marked' ? (ok ? 'You said yours matched' : 'You said not yet') : pretty(a.given);
            return `<div class="rv ${ok ? 'ok' : 'no'}">
                <div class="rv-top"><div class="rv-mark">${ok ? '✓' : '✗'}</div>
                    <div class="rv-q">${pretty(it.question)}
                        <div class="rv-ans">Your answer: <b>${yours}</b>${ok ? '' : ` · Answer: <b>${pretty(it.answer)}</b>`}</div>
                    </div></div>
                <button type="button" class="btn small ghost" data-steps="${k}">Show the working</button>
                <div class="silver steps" id="steps-${k}" hidden>${stepsHtml(it)}</div>
            </div>`;
        }).join('');
        const own = S.original;
        $('ownBox').hidden = !own;
        if (own) {
            $('ownQ').innerHTML = pretty(own.question);
            $('ownA').innerHTML = pretty(own.answer);
            $('ownSteps').innerHTML = stepsHtml(own);
            $('ownSteps').hidden = true;
            $('ownShow').textContent = 'Show the working';
        }
        show('vReview');
        api('/api/sqe/done', { question: S.question, score: got, total }).catch(() => {});
    }
    $('ownShow').addEventListener('click', () => {
        const box = $('ownSteps');
        box.hidden = !box.hidden;
        $('ownShow').textContent = box.hidden ? 'Show the working' : 'Hide the working';
    });
    $('reviewList').addEventListener('click', (e) => {
        const b = e.target.closest('[data-steps]');
        if (!b) return;
        const box = $(`steps-${b.dataset.steps}`);
        box.hidden = !box.hidden;
        b.textContent = box.hidden ? 'Show the working' : 'Hide the working';
    });
    $('again').addEventListener('click', () => make(S.question));
    $('newQ').addEventListener('click', () => { show('vStart'); $('q').select(); $('q').focus(); });

    // ── the maths keyboard ───────────────────────────────────────────────────────────
    const KEYS = [
        ['Operators', ['+', '−', '×', '÷', '=', '(', ')', '/', ',']],
        ['Powers and roots', [['x²', '^2'], ['x³', '^3'], ['xⁿ', '^'], ['√', 'sqrt()'], ['π', 'π'], ['e', 'e']]],
        ['Functions', [['sin', 'sin()'], ['cos', 'cos()'], ['tan', 'tan()'], ['ln', 'ln()'], ['log', 'log()'], ['eˣ', 'e^()'], ['|x|', '||']]],
        ['Calculus', [['d/dx', 'Differentiate '], ['∫', 'Integrate '], ['lim', 'lim x->'], ['→', '->'], ['∞', '∞']]],
        ['Compare', ['<', '>', '≤', '≥', '≠']],
        ['Letters', ['x', 'y', 'n', 'θ', 'i']],
    ];
    $('kbBody').innerHTML = KEYS.map(([title, keys]) => `<div class="kb-group"><span>${title}</span><div class="kb-keys">${keys.map((k) => {
        const [label, text] = Array.isArray(k) ? k : [k, k];
        return `<button type="button" data-ins="${esc(text)}">${esc(label)}</button>`;
    }).join('')}</div></div>`).join('');
    document.querySelectorAll('.kb-toggle').forEach((b) => b.addEventListener('click', () => {
        S.kbTarget = b.dataset.kb;
        $('kb').hidden = !$('kb').hidden;
        $(S.kbTarget).focus();
    }));
    $('kbClose').addEventListener('click', () => { $('kb').hidden = true; });
    $('kbBody').addEventListener('mousedown', (e) => e.preventDefault());          // keep the cursor in the box
    $('kbBody').addEventListener('click', (e) => {
        const b = e.target.closest('[data-ins]');
        const box = $(S.kbTarget);
        if (!b || !box || box.disabled) return;
        const ins = b.dataset.ins;
        const at = box.selectionStart ?? box.value.length;
        box.value = box.value.slice(0, at) + ins + box.value.slice(box.selectionEnd ?? at);
        const inside = ins.endsWith('()') || ins === '||' ? ins.length - 1 : ins.length;   // the cursor goes between ( )
        box.setSelectionRange(at + inside, at + inside);
        box.focus();
    });
    for (const id of ['q', 'rAns']) $(id).addEventListener('focus', () => { S.kbTarget = id; });

    // ── the calculator: MrSOLIS 3's own (mrsolis-calc.js — same keys, DEG/RAD, Ans and history), docked beside
    //    the question so nothing is covered. Pressing its "= answer" puts it in the answer box when there is one.
    const dock = $('calcDock');
    function setCalc(open) {
        dock.hidden = !open;
        document.body.classList.toggle('calc-open', open);
        $('calcBtn').classList.toggle('on', open);
        $('calcBtn').setAttribute('aria-pressed', String(open));
        if (!open) {
            if (!$('rTyped').hidden && !$('rAns').disabled) $('rAns').focus();
            return;
        }
        if (!dock.firstChild) {
            mountCalc(dock, true, { tape: true, drag: false, onClose: () => setCalc(false), onCopy: useResult,
                copyTitle: 'Put this in your answer' });
        }
        const inp = dock.querySelector('.calc-in');
        inp.focus();
        inp.setSelectionRange(inp.value.length, inp.value.length);
    }
    function useResult(v) {
        const text = calcPlain(v);
        const box = $('rAns');
        if (!$('vRun').hidden && !$('rTyped').hidden && !box.disabled) {
            const at = box.selectionStart ?? box.value.length;
            box.value = box.value.slice(0, at) + text + box.value.slice(box.selectionEnd ?? at);
            box.focus();
            box.setSelectionRange(at + text.length, at + text.length);
        } else if (navigator.clipboard) {
            navigator.clipboard.writeText(text).catch(() => {});      // choosing from four: copied, to compare
        }
    }
    $('calcBtn').addEventListener('click', () => setCalc(dock.hidden));

    // ── window buttons, a question passed in, the stars ────────────────────────────────
    const win = window.mrsolisWindow;
    if (win) {
        $('win-min').addEventListener('click', () => win.minimize());
        $('win-max').addEventListener('click', () => win.toggleMaximize());
        $('win-close').addEventListener('click', () => win.close());
    } else {
        $('winCtrls').hidden = true;                    // a browser tab has its own
    }
    function prefill(q) {
        if (!q) return;
        if (!$('vRun').hidden) { S.pending = q; return; }   // don't break a practice in progress
        $('q').value = q;
        show('vStart');
        $('q').focus();
    }
    prefill(new URLSearchParams(location.search).get('q') || '');
    if (window.mrsolisSqe) window.mrsolisSqe.onPrefill(prefill);
    $('leaveYes').addEventListener('click', () => { if (S.pending) { $('q').value = S.pending; S.pending = ''; } });

    (function stars() {                                  // a quiet starfield, like the main window's sky
        const c = $('stars');
        const g = c.getContext('2d');
        const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        let pts = [];
        const size = () => {
            const dpr = window.devicePixelRatio || 1;
            c.width = innerWidth * dpr;
            c.height = innerHeight * dpr;
            pts = Array.from({ length: Math.round((innerWidth * innerHeight) / 7000) }, () => ({
                x: Math.random(), y: Math.random(), r: (Math.random() * 1.0 + 0.25) * dpr, a: Math.random() * 0.55 + 0.15, t: Math.random() * 6.28,
            }));
        };
        const draw = () => {
            const now = performance.now();
            g.clearRect(0, 0, c.width, c.height);
            g.fillStyle = '#fff';
            for (const p of pts) {
                g.globalAlpha = p.a * (still ? 1 : 0.7 + 0.3 * Math.sin(now / 1600 + p.t));
                g.beginPath();
                g.arc(p.x * c.width, p.y * c.height, p.r, 0, 6.283);
                g.fill();
            }
        };
        size();
        draw();
        addEventListener('resize', () => { size(); draw(); });
        if (!still) setInterval(() => { if (!document.hidden) draw(); }, 120);   // gentle, and cheap on slow laptops
    })();
})();
