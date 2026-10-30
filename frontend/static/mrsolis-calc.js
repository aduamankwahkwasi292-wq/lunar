/* ═══════════════════════════════════════════════════════════════════
   MrSOLIS 3 Calculator — Tools → Calculator.

   A real scientific calculator: the answer is computed exactly here, by
   a small expression parser (no model, no eval). Degrees/radians, a 2nd
   key for the inverse functions, EXP (×10ⁿ), Ans, a live preview while
   typing and a history tape. calcEval() is pure, so it can be tested on
   its own (node: require this file and call calcEval).
   ═══════════════════════════════════════════════════════════════════ */
'use strict';

// ── the maths ────────────────────────────────────────────────────────
class CalcError extends Error {}

const SUP = { '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹', '-': '⁻' };

/** Split the typed expression into tokens. Accepts both the keypad's symbols and plain typing. */
function calcTokens(src) {
    const s = String(src)
        .replace(/[×·∙*]/g, '*').replace(/[÷/]/g, '/').replace(/[−–]/g, '-')
        .replace(/²/g, '^2').replace(/³/g, '^3').replace(/π/g, ' pi ').replace(/\s+/g, ' ');
    const out = [];
    let i = 0;
    while (i < s.length) {
        const c = s[i];
        if (c === ' ') { i++; continue; }
        const num = /^(\d+\.?\d*|\.\d+)(E[+-]?\d+)?/.exec(s.slice(i));
        if (num) {
            if (/^E/.test(s.slice(i + num[0].length))) throw new CalcError('Syntax error');   // "2E" with no power
            out.push({ t: 'num', v: parseFloat(num[0]) });
            i += num[0].length;
            continue;
        }
        if (c === 'E') throw new CalcError('Syntax error');                                // EXP with no number before it
        if (s.startsWith('ˣ√', i)) { out.push({ t: 'op', v: 'root' }); i += 2; continue; }
        if (s.startsWith('⁻¹', i)) { out.push({ t: 'post', v: 'inv' }); i += 2; continue; }
        if (c === '√') { out.push({ t: 'fn', v: 'sqrt' }); i++; continue; }
        if (c === '∛') { out.push({ t: 'fn', v: 'cbrt' }); i++; continue; }
        const word = /^[A-Za-z]+/.exec(s.slice(i));
        if (word) {
            let w = word[0];
            i += w.length;
            if (s.startsWith('⁻¹', i) && /^(sin|cos|tan|sinh|cosh|tanh)$/.test(w)) { w = 'a' + w; i += 2; }
            const lw = w.toLowerCase();
            if (w === 'C' || w === 'P') out.push({ t: 'op', v: w });          // 5 C 2, 5 P 2
            else if (lw === 'pi') out.push({ t: 'num', v: Math.PI, name: 'π' });
            else if (w === 'e') out.push({ t: 'num', v: Math.E, name: 'e' });
            else if (lw === 'ans') out.push({ t: 'ans' });
            else if (CALC_FN[lw]) out.push({ t: 'fn', v: lw });
            else throw new CalcError(`Unknown “${w}”`);
            continue;
        }
        if ('+-'.includes(c)) { out.push({ t: 'add', v: c }); i++; continue; }
        if ('*/'.includes(c)) { out.push({ t: 'mul', v: c }); i++; continue; }
        if (c === '^') { out.push({ t: 'op', v: '^' }); i++; continue; }
        if (c === '!' || c === '%') { out.push({ t: 'post', v: c }); i++; continue; }
        if (c === '(' || c === ')') { out.push({ t: c }); i++; continue; }
        throw new CalcError(`Can’t use “${c}”`);
    }
    return out;
}

const DEG = Math.PI / 180;
// trig in degrees lands exactly on the special angles (sin 180° is 0, not 1.2e-16; tan 90° is undefined)
function trig(name, x, deg) {
    if (deg) {
        const r = ((x % 360) + 360) % 360;
        if (name === 'sin' && r % 180 === 0) return 0;
        if (name === 'cos' && (r - 90) % 180 === 0) return 0;
        if (name === 'tan') {
            if (r % 180 === 0) return 0;
            if ((r - 90) % 180 === 0) throw new CalcError('tan is undefined there');
            if (r === 45 || r === 225) return 1;
            if (r === 135 || r === 315) return -1;
        }
        if (name === 'sin' && (r === 30 || r === 150)) return 0.5;
        if (name === 'sin' && (r === 210 || r === 330)) return -0.5;
        if (name === 'cos' && (r === 60 || r === 300)) return 0.5;
        if (name === 'cos' && (r === 120 || r === 240)) return -0.5;
        x *= DEG;
    }
    const v = Math[name](x);
    return Math.abs(v) < 1e-15 ? 0 : v;
}
const inverse = (name, x, deg) => {
    if ((name === 'asin' || name === 'acos') && (x < -1 || x > 1)) throw new CalcError(`${name.slice(1)}⁻¹ needs a value from −1 to 1`);
    const v = Math[name](x);
    return deg ? v / DEG : v;
};
const positive = (what, x, f) => { if (x <= 0) throw new CalcError(`${what} needs a number above 0`); return f(x); };

const CALC_FN = {
    sin: (x, d) => trig('sin', x, d), cos: (x, d) => trig('cos', x, d), tan: (x, d) => trig('tan', x, d),
    asin: (x, d) => inverse('asin', x, d), acos: (x, d) => inverse('acos', x, d), atan: (x, d) => inverse('atan', x, d),
    sinh: Math.sinh, cosh: Math.cosh, tanh: Math.tanh, asinh: Math.asinh,
    acosh: (x) => { if (x < 1) throw new CalcError('cosh⁻¹ needs a value of 1 or more'); return Math.acosh(x); },
    atanh: (x) => { if (x <= -1 || x >= 1) throw new CalcError('tanh⁻¹ needs a value between −1 and 1'); return Math.atanh(x); },
    ln: (x) => positive('ln', x, Math.log), log: (x) => positive('log', x, Math.log10),
    sqrt: (x) => { if (x < 0) throw new CalcError('√ of a negative number'); return Math.sqrt(x); },
    cbrt: Math.cbrt, abs: Math.abs, exp: Math.exp,
};

function factorial(n) {
    if (!Number.isInteger(n) || n < 0 || n > 170) throw new CalcError('n! needs a whole number from 0 to 170');
    let f = 1;
    for (let k = 2; k <= n; k++) f *= k;
    return f;
}

function power(a, b) {
    if (a === 0 && b < 0) throw new CalcError('Can’t divide by zero');
    if (a < 0 && !Number.isInteger(b)) {
        const q = 1 / b;                            // (−8)^(1/3) = −2: an odd root of a negative is fine
        if (Number.isInteger(Math.round(q)) && Math.abs(q - Math.round(q)) < 1e-9 && Math.round(q) % 2) return -Math.pow(-a, b);
        throw new CalcError('Not a real number');
    }
    return Math.pow(a, b);
}
function root(n, x) {
    if (n === 0) throw new CalcError('A 0th root doesn’t exist');
    if (x < 0) {
        if (Number.isInteger(n) && n % 2) return -Math.pow(-x, 1 / n);
        throw new CalcError('Not a real number');
    }
    return Math.pow(x, 1 / n);
}

function choose(n, r, ordered) {
    if (!Number.isInteger(n) || !Number.isInteger(r) || n < 0 || r < 0 || r > n) {
        throw new CalcError(`${ordered ? 'nPr' : 'nCr'} needs whole numbers with 0 ≤ r ≤ n`);
    }
    let v = 1;
    if (ordered) for (let k = 0; k < r; k++) v *= n - k;
    else for (let k = 1, rr = Math.min(r, n - r); k <= rr; k++) v = (v * (n - rr + k)) / k;
    return Math.round(v);
}

/** Evaluate an expression. `deg` = angles in degrees. Throws CalcError with a readable message. */
function calcEval(src, { deg = true, ans = 0 } = {}) {
    const toks = calcTokens(src);
    if (!toks.length) throw new CalcError('Nothing to work out');
    let p = 0;
    const peek = () => toks[p];
    const startsOperand = (t) => t && (t.t === 'num' || t.t === 'ans' || t.t === 'fn' || t.t === '(');

    function expr() {
        let v = term();
        while (peek() && peek().t === 'add') v = toks[p++].v === '+' ? v + term() : v - term();
        return v;
    }
    function term() {
        let v = unary();
        for (;;) {
            const t = peek();
            if (t && t.t === 'mul') {
                p++;
                const r = unary();
                if (t.v === '/') { if (r === 0) throw new CalcError('Can’t divide by zero'); v /= r; } else v *= r;
            } else if (startsOperand(t)) {
                v *= unary();                          // 2π, 3(4), 2sin(30)
            } else return v;
        }
    }
    function unary() {
        const t = peek();
        if (t && t.t === 'add') { p++; const v = unary(); return t.v === '-' ? -v : v; }   // −2² = −4
        return pow();
    }
    function pow() {
        const base = postfix();
        const t = peek();
        if (t && t.t === 'op') {
            p++;
            const e = unary();                         // right-associative: 2^3^2 = 2^9
            if (t.v === 'C' || t.v === 'P') return choose(base, e, t.v === 'P');
            return t.v === '^' ? power(base, e) : root(base, e);
        }
        return base;
    }
    function postfix() {
        let v = primary();
        while (peek() && peek().t === 'post') {
            const op = toks[p++].v;
            if (op === '!') v = factorial(v);
            else if (op === '%') v /= 100;
            else { if (v === 0) throw new CalcError('Can’t divide by zero'); v = 1 / v; }
        }
        return v;
    }
    function primary() {
        const t = toks[p++];
        if (!t) throw new CalcError('Syntax error');
        if (t.t === 'num') return t.v;
        if (t.t === 'ans') return ans;
        if (t.t === '(') {
            const v = expr();
            if (peek() && peek().t === ')') p++;      // a missing ")" at the end is closed for you
            else if (peek()) throw new CalcError('Syntax error');
            return v;
        }
        if (t.t === 'fn') {
            const x = peek() && peek().t === '(' ? primary() : postfix();     // sin(30) or sin 30
            return CALC_FN[t.v](x, deg);
        }
        throw new CalcError('Syntax error');
    }

    const v = expr();
    if (p < toks.length) throw new CalcError(toks[p].t === ')' ? 'Too many “)”' : 'Syntax error');
    if (!Number.isFinite(v)) throw new CalcError(Number.isNaN(v) ? 'Math error' : 'Too big');
    return Object.is(v, -0) ? 0 : v;
}

/** How a result is shown: 12 significant digits, ×10ⁿ for very big or small numbers. */
function calcFormat(x) {
    return formatNumber(x).replace(/^-/, '−');
}
function formatNumber(x) {
    if (x === 0) return '0';
    const a = Math.abs(x);
    if (a >= 1e12 || a < 1e-6) {
        const [m, e] = x.toExponential(9).split('e');
        const mant = m.replace(/\.?0+$/, '');
        return `${mant}×10${String(+e).split('').map((c) => SUP[c]).join('')}`;
    }
    return String(Number(x.toPrecision(12)));
}
/** The same number written so it can be typed back in (Ans, copy). */
const calcPlain = (x) => String(Number(x.toPrecision(15))).replace(/e\+?/, 'E');

if (typeof module !== 'undefined') module.exports = { calcEval, calcFormat, calcPlain, CalcError };

// ── the calculator on screen: in Tools, on the board ("/calculator") and in the SQE window ──
// One calculator, shown in either place: the same Ans, history and DEG/RAD.
// The SQE window (sqe.html) has none of the main window's helpers, so these stand in for esc() and icon().
const calcEsc = (s) => (typeof esc === 'function' ? esc(s)
    : String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]));
const calcIcon = (name) => `<svg class="ico"><use href="#i-${name}"/></svg>`;
const CALC = {
    expr: '', result: null, error: '', done: false,    // done: "=" was just pressed
    deg: true, second: false, ans: 0, history: [],
    root: null,                                        // the copy on screen being used
    boardPos: null,                                    // where the student dragged it on the board
};

// [label, 2nd label, what it types, what 2nd types, class]
const CALC_KEYS = [
    ['2nd', null, '@2nd', null, 'fn'], ['DEG', null, '@deg', null, 'fn'], ['π', null, 'π', null, 'fn'], ['e', null, 'e', null, 'fn'], ['AC', null, '@ac', null, 'warn'],
    ['x²', 'x³', '²', '³', 'fn'], ['√', '∛', '√(', '∛(', 'fn'], ['xʸ', 'ʸ√x', '^', 'ˣ√', 'fn'], ['n!', '|x|', '!', 'abs(', 'fn'], ['⌫', null, '@back', null, 'warn'],
    ['sin', 'sin⁻¹', 'sin(', 'sin⁻¹(', 'fn'], ['cos', 'cos⁻¹', 'cos(', 'cos⁻¹(', 'fn'], ['tan', 'tan⁻¹', 'tan(', 'tan⁻¹(', 'fn'], ['ln', 'eˣ', 'ln(', 'e^(', 'fn'], ['log', '10ˣ', 'log(', '10^(', 'fn'],
    ['x⁻¹', null, '⁻¹', null, 'fn'], ['(', null, '(', null, 'fn'], [')', null, ')', null, 'fn'], ['%', null, '%', null, 'fn'], ['÷', null, '÷', null, 'op'],
    ['EXP', null, 'E', null, 'fn'], ['7', null, '7'], ['8', null, '8'], ['9', null, '9'], ['×', null, '×', null, 'op'],
    ['Ans', null, 'Ans', null, 'fn'], ['4', null, '4'], ['5', null, '5'], ['6', null, '6'], ['−', null, '−', null, 'op'],
    ['(−)', null, '−', null, 'fn'], ['1', null, '1'], ['2', null, '2'], ['3', null, '3'], ['+', null, '+', null, 'op'],
    ['nCr', 'nPr', ' C ', ' P ', 'fn'], ['0', null, '0'], ['.', null, '.'], ['=', null, '@eq', null, 'eq'],
];
// keys that carry on from the last answer ("= 12" then "× 3" means Ans × 3)
const CONTINUES = /^(?:[+×÷^!%²³−]|⁻¹|ˣ√| [CP] )/;

const cq = (sel) => (CALC.root ? CALC.root.querySelector(sel) : null);
const calcModeLabel = () => (CALC.deg ? 'Degrees' : 'Radians');

function calcKeysHTML() {
    return CALC_KEYS.map(([label, alt, , , cls], i) => {
        const shown = CALC.second && alt ? alt : label === 'DEG' ? (CALC.deg ? 'DEG' : 'RAD') : label;
        const on = label === '2nd' && CALC.second ? ' on' : '';
        return `<button type="button" class="ck ${cls || 'num'}${on}" data-calc="key" data-k="${i}"${alt ? ` title="2nd: ${calcEsc(alt)}"` : ''}>${calcEsc(shown)}</button>`;
    }).join('');
}

function calcHTML(onBoard, tape = !onBoard, drag = onBoard) {
    const head = onBoard
        ? `<div class="calc-bar"${drag ? ' title="Drag to move"' : ''}>${calcIcon('calc')}<b>Calculator</b><span class="calc-mode">${calcModeLabel()}</span>
               <button type="button" class="calc-x" data-calc="close" title="Close (Esc)">${calcIcon('close')}</button></div>`
        : `<div class="tool-head">${calcIcon('calc')}<h3>Calculator</h3><span class="calc-mode">${calcModeLabel()}</span></div>`;
    return `${head}
        <div class="silver calc-screen">
            <input class="calc-in" value="${calcEsc(CALC.expr)}" placeholder="0" autocomplete="off" spellcheck="false" aria-label="Calculation">
            <div class="calc-out"></div>
        </div>
        <div class="calc-keys">${calcKeysHTML()}</div>
        ${tape ? '<div class="calc-tape"></div>' : ''}`;
}

function drawCalcOut() {
    const out = cq('.calc-out');
    if (!out) return;
    if (CALC.error) { out.className = 'calc-out err'; out.textContent = CALC.error; return; }
    if (CALC.done && CALC.result !== null) {
        out.className = 'calc-out done';
        const title = (CALC.root.calcOpts && CALC.root.calcOpts.copyTitle) || 'Copy the answer';
        out.innerHTML = `<button type="button" class="calc-copy" data-calc="copy" title="${calcEsc(title)}">= ${calcEsc(calcFormat(CALC.result))}</button>`;
        return;
    }
    out.className = 'calc-out';
    let preview = '';
    try { if (CALC.expr.trim()) preview = '= ' + calcFormat(calcEval(CALC.expr, { deg: CALC.deg, ans: CALC.ans })); } catch (e) { /* still typing */ }
    out.textContent = preview;
}

function drawCalcTape() {
    const tape = cq('.calc-tape');
    if (!tape) return;
    tape.innerHTML = CALC.history.length
        ? CALC.history.map((h, i) => `<button type="button" class="calc-line" data-calc="reuse" data-i="${i}" title="Use this again">
            <span>${calcEsc(h.expr)}</span><b>= ${calcEsc(calcFormat(h.result))}</b></button>`).join('') +
          '<button type="button" class="btn small ghost" data-calc="clear-tape">Clear history</button>'
        : '<div class="muted calc-empty">Your calculations will be listed here.</div>';
}

/** Relabel the keys in place (2nd, DEG/RAD). Never re-create them: a key pressed while it's being
 *  replaced loses its click. */
function refreshKeys() {
    const keys = CALC.root.querySelectorAll('.ck');
    CALC_KEYS.forEach(([label, alt], i) => {
        if (!keys[i]) return;
        keys[i].textContent = CALC.second && alt ? alt : label === 'DEG' ? (CALC.deg ? 'DEG' : 'RAD') : label;
        keys[i].classList.toggle('on', label === '2nd' && CALC.second);
    });
    cq('.calc-mode').textContent = calcModeLabel();
}

/** Bring a copy up to date when the student starts using it (the other copy may have moved on). */
function useCalc(root) {
    if (CALC.root === root) return;
    CALC.root = root;
    refreshKeys();
    const inp = cq('.calc-in');
    if (inp.value !== CALC.expr) { inp.value = CALC.expr; inp.setSelectionRange(inp.value.length, inp.value.length); }
    drawCalcOut();
    drawCalcTape();
}

function calcInsert(text, fresh = false) {
    const inp = cq('.calc-in');
    if (!inp) return;
    if (CALC.done) {                                   // after "=": an operator carries on from Ans, anything else starts afresh
        inp.value = !fresh && CONTINUES.test(text) ? 'Ans' : '';
        inp.setSelectionRange(inp.value.length, inp.value.length);
        CALC.done = false;
    }
    CALC.error = '';
    const a = inp.selectionStart ?? inp.value.length, b = inp.selectionEnd ?? a;
    inp.value = inp.value.slice(0, a) + text + inp.value.slice(b);
    CALC.expr = inp.value;
    inp.focus();
    inp.setSelectionRange(a + text.length, a + text.length);
}

function calcBackspace() {
    const inp = cq('.calc-in');
    if (!inp) return;
    CALC.done = false;
    CALC.error = '';
    let a = inp.selectionStart, b = inp.selectionEnd;
    if (a === b) {
        const before = inp.value.slice(0, a);
        const unit = /(?:[a-z]+(?:⁻¹)?\(|Ans|⁻¹|ˣ√|[√∛]\()$/i.exec(before);   // "sin(" goes in one press
        a = Math.max(0, a - (unit ? unit[0].length : 1));
    }
    inp.value = inp.value.slice(0, a) + inp.value.slice(b);
    CALC.expr = inp.value;
    inp.focus();
    inp.setSelectionRange(a, a);
}

function calcClear() {
    Object.assign(CALC, { expr: '', result: null, error: '', done: false });
    const inp = cq('.calc-in');
    if (inp) { inp.value = ''; inp.focus(); }
    drawCalcOut();
}

function calcEquals() {
    const expr = CALC.expr.trim();
    if (!expr) return;
    try {
        const v = calcEval(expr, { deg: CALC.deg, ans: CALC.ans });
        Object.assign(CALC, { result: v, ans: v, error: '', done: true });
        const last = CALC.history[0];
        if (!last || last.expr !== expr || last.result !== v) CALC.history = [{ expr, result: v }, ...CALC.history].slice(0, 30);
    } catch (e) {
        CALC.error = e instanceof CalcError ? e.message : 'Math error';
        CALC.done = false;
    }
    drawCalcOut();
    drawCalcTape();
}

function calcKey(i) {
    const [label, , text, alt] = CALC_KEYS[i];
    const type = CALC.second && alt ? alt : text;
    if (type === '@2nd') { CALC.second = !CALC.second; refreshKeys(); return; }
    if (CALC.second && alt) { CALC.second = false; refreshKeys(); }
    if (type === '@deg') { CALC.deg = !CALC.deg; refreshKeys(); drawCalcOut(); return; }
    if (type === '@ac') { calcClear(); return; }
    if (type === '@back') { calcBackspace(); drawCalcOut(); return; }
    if (type === '@eq') { calcEquals(); return; }
    calcInsert(type, label === '(−)');
    drawCalcOut();
}

const calcClose = (root) => ((root.calcOpts && root.calcOpts.onClose) || closeBoardCalc)();

/** Put the calculator into `root` (the Tools panel, #board-calc, or the SQE window's dock). Events are delegated
 *  to the root, so this can be called again whenever the page redraws. opts (the SQE window): { tape, drag,
 *  onClose, onCopy(result), copyTitle } — onCopy replaces copying to the clipboard. */
function mountCalc(root, onBoard = false, opts = {}) {
    root.calcOpts = opts;
    root.innerHTML = calcHTML(onBoard, opts.tape ?? !onBoard, onBoard && opts.drag !== false);
    CALC.root = root;
    if (!root.dataset.calcBound) {
        root.dataset.calcBound = '1';
        // keys don't take the focus from the input, so the cursor stays where the student left it
        root.addEventListener('mousedown', (e) => { if (e.target.closest('.ck, .calc-copy')) e.preventDefault(); });
        root.addEventListener('pointerenter', () => useCalc(root));      // relabel before the first click
        root.addEventListener('pointerdown', () => useCalc(root));
        root.addEventListener('focusin', () => useCalc(root));
        root.addEventListener('click', (e) => {
            const el = e.target.closest('[data-calc]');
            if (!el) return;
            useCalc(root);
            const what = el.dataset.calc;
            if (what === 'key') calcKey(+el.dataset.k);
            else if (what === 'close') calcClose(root);
            else if (what === 'copy') {
                if (root.calcOpts.onCopy) root.calcOpts.onCopy(CALC.result);
                else navigator.clipboard.writeText(calcPlain(CALC.result)).then(() => showToast('Answer copied'), () => {});
            } else if (what === 'clear-tape') { CALC.history = []; drawCalcTape(); }
            else if (what === 'reuse') {
                const h = CALC.history[+el.dataset.i];
                if (!h) return;
                Object.assign(CALC, { expr: h.expr, done: false, error: '' });
                const inp = cq('.calc-in');
                inp.value = h.expr;
                inp.focus();
                inp.setSelectionRange(h.expr.length, h.expr.length);
                drawCalcOut();
            }
        });
        root.addEventListener('keydown', (e) => {
            if (!e.target.classList.contains('calc-in')) return;
            if (e.key === 'Enter' || e.key === '=') { e.preventDefault(); calcEquals(); return; }
            if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                if (onBoard && !CALC.expr) calcClose(root); else calcClear();   // Esc clears, then closes
                return;
            }
            if (CALC.done && e.key.length === 1 && !e.ctrlKey && !e.metaKey) {   // typing after "=": as on the keypad
                e.preventDefault();
                calcInsert({ '*': '×', '/': '÷', '-': '−' }[e.key] || e.key);
                drawCalcOut();
            }
        });
        root.addEventListener('input', (e) => {
            const inp = e.target;
            if (!inp.classList.contains('calc-in')) return;
            // show typed * / - as × ÷ − (same length, so the cursor stays put)
            const pos = inp.selectionStart;
            const pretty = inp.value.replace(/\*/g, '×').replace(/\//g, '÷').replace(/-/g, '−');
            if (pretty !== inp.value) { inp.value = pretty; inp.setSelectionRange(pos, pos); }
            Object.assign(CALC, { expr: inp.value, done: false, error: '' });
            drawCalcOut();
        });
        if (onBoard && opts.drag !== false) dragCalc(root);
    }
    const inp = root.querySelector('.calc-in');
    inp.setSelectionRange(inp.value.length, inp.value.length);       // keys add to the end until the student moves the cursor
    drawCalcOut();
    drawCalcTape();
}

// ── on the board ─────────────────────────────────────────────────────
const boardCalc = typeof document !== 'undefined' ? document.getElementById('board-calc') : null;   // none in the SQE window

function openBoardCalc() {
    if (typeof go === 'function' && typeof currentPage !== 'undefined' && currentPage !== 'home') go('home');
    boardCalc.hidden = false;
    mountCalc(boardCalc, true);
    placeBoardCalc();
    const inp = cq('.calc-in');
    inp.focus();
    inp.setSelectionRange(inp.value.length, inp.value.length);
}

function closeBoardCalc() {
    if (!boardCalc || boardCalc.hidden) return;
    boardCalc.hidden = true;
    if (CALC.root === boardCalc) CALC.root = null;
    chatInput.focus();
}

const boardCalcOpen = () => !!boardCalc && !boardCalc.hidden;

// keep it inside the board (the window may have been resized since it was dragged)
function placeBoardCalc() {
    if (!CALC.boardPos) { boardCalc.style.left = boardCalc.style.top = ''; boardCalc.style.right = ''; return; }
    const box = boardFrame.getBoundingClientRect(), me = boardCalc.getBoundingClientRect();
    const left = Math.max(8, Math.min(CALC.boardPos.left, box.width - me.width - 8));
    const top = Math.max(8, Math.min(CALC.boardPos.top, box.height - me.height - 8));
    Object.assign(boardCalc.style, { left: `${left}px`, top: `${top}px`, right: 'auto' });
}

function dragCalc(el) {
    let from = null;
    el.addEventListener('pointerdown', (e) => {
        if (!e.target.closest('.calc-bar') || e.target.closest('button')) return;
        const box = boardFrame.getBoundingClientRect(), me = el.getBoundingClientRect();
        from = { x: e.clientX, y: e.clientY, left: me.left - box.left, top: me.top - box.top };
        try { el.setPointerCapture(e.pointerId); } catch (err) { /* keeps working without capture */ }
        el.classList.add('dragging');
    });
    el.addEventListener('pointermove', (e) => {
        if (!from) return;
        CALC.boardPos = { left: from.left + e.clientX - from.x, top: from.top + e.clientY - from.y };
        placeBoardCalc();
    });
    const drop = () => { from = null; el.classList.remove('dragging'); };
    el.addEventListener('pointerup', drop);
    el.addEventListener('pointercancel', drop);
}
if (typeof window !== 'undefined') window.addEventListener('resize', () => { if (boardCalcOpen()) placeBoardCalc(); });

