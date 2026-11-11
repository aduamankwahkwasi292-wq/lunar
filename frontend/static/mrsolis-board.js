/* ═══════════════════════════════════════════════════════════════════
   MrSOLIS class board — a blackboard that is written on by hand.

   new Blackboard(hostElement, font)       font: static/board-font.json (single-stroke letters,
                                           scripts/build_board_font.py)
     .write(text, {duration, color})       writes a line with a moving pen; resolves when the pen lifts.
                                           text is what a teacher would write:
                                             "# Ohm's law"            a heading (underlined)
                                             "- current is the flow"  a bullet
                                             "V = I × R"              maths: x^2, v_0, a/b and (a+b)/c stack
                                             "x = √(b^2 − 4ac)"       as fractions, √(…) grows a bar
                                             "the **key term**"       ** ** is written in colour
                                             "Answer: R = 6 Ω"        boxed
     .pause() / .resume() / .finish()      stop the pen, carry on, or complete what is being written at once
     .erase()                              wipe the board
     .lines                                what has been written (plain text), for whoever needs to know

   Everything is drawn in a 1600-wide space that the screen scales, so a lesson looks the same on any display.
   No backend, no other script: this file can be used (and tested) on its own.
   ═══════════════════════════════════════════════════════════════════ */
'use strict';

const BOARD_INK = {
    white: '#f4f1e8', yellow: '#ffd866', red: '#ff6b6b', blue: '#6cb6ff', green: '#6fe39a', orange: '#ffaa5c',
    purple: '#c9a2ff', pink: '#ff9ecb', grey: '#9a9a94',
};
const BOARD_ACCENTS = ['blue', 'red', 'green', 'orange', 'purple'];
const SVGNS = 'http://www.w3.org/2000/svg';

/** LaTeX leftovers and keyboard stand-ins become the signs a teacher writes. */
function boardTidy(text) {
    let s = String(text || '');
    s = s.replace(/\*\*([^*]+)\*\*/g, '\u0002$1\u0003');                     // **key term** → colour on / off
    s = s.replace(/\$\$?|\\\(|\\\)|\\\[|\\\]|`/g, '');
    s = s.replace(/\\(?:left|right|displaystyle|limits)\b/g, '').replace(/\\[,;!: ]|\\q?quad\b/g, ' ');
    s = s.replace(/\\(?:text|mathrm|mathbf|textbf|mathit|operatorname)\s*\{([^{}]*)\}/g, '$1');
    s = s.replace(/\\[dt]?frac\s*(?=\{)/g, '\u0001').replace(/\\sqrt\s*(?=\{)/g, '√').replace(/\\sqrt\b/g, '√');
    s = s.replace(/\bsqrt\s*(?=\()/gi, '√');
    const names = {
        alpha: 'α', beta: 'β', gamma: 'γ', delta: 'δ', epsilon: 'ε', varepsilon: 'ε', zeta: 'ζ', eta: 'η', theta: 'θ',
        iota: 'ι', kappa: 'κ', lambda: 'λ', mu: 'μ', nu: 'ν', xi: 'ξ', pi: 'π', rho: 'ρ', sigma: 'σ', tau: 'τ',
        upsilon: 'υ', phi: 'φ', varphi: 'φ', chi: 'χ', psi: 'ψ', omega: 'ω', Gamma: 'Γ', Delta: 'Δ', Theta: 'Θ',
        Lambda: 'Λ', Xi: 'Ξ', Pi: 'Π', Sigma: 'Σ', Phi: 'Φ', Psi: 'Ψ', Omega: 'Ω',
        times: '×', cdot: '·', div: '÷', pm: '±', mp: '∓', approx: '≈', sim: '∼', leq: '≤', le: '≤', geq: '≥', ge: '≥',
        neq: '≠', ne: '≠', to: '→', rightarrow: '→', leftarrow: '←', Rightarrow: '⇒', implies: '⇒', infty: '∞',
        degree: '°', circ: '°', propto: '∝', sum: 'Σ', int: '∫', partial: '∂', angle: '∠', perp: '⊥', parallel: '∥',
        triangle: '△', therefore: '∴', ldots: '…', dots: '…', cdots: '…', uparrow: '↑', downarrow: '↓',
    };
    s = s.replace(/\\([A-Za-z]+)/g, (m, n) => (names[n] !== undefined ? names[n] : n));
    s = s.replace(/\^\s*°/g, '°').replace(/\\/g, '');
    s = s.replace(/<=/g, '≤').replace(/>=/g, '≥').replace(/!=/g, '≠').replace(/=>/g, '⇒').replace(/->/g, '→')
        .replace(/\+\/?-/g, '±').replace(/~=/g, '≈').replace(/\.\.\./g, '…');
    s = s.replace(/\s\*\s/g, ' × ').replace(/(\w|\))\*(\w|\()/g, '$1×$2').replace(/\*/g, '');
    // ² ³ ₀ … → the same thing written with ^ and _
    const up = '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿ', upTo = '0123456789+-n', down = '₀₁₂₃₄₅₆₇₈₉', downTo = '0123456789';
    s = s.replace(/[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿ]+/g, (m) => '^{' + [...m].map((c) => upTo[up.indexOf(c)]).join('') + '}');
    s = s.replace(/[₀₁₂₃₄₅₆₇₈₉]+/g, (m) => '_{' + [...m].map((c) => downTo[down.indexOf(c)]).join('') + '}');
    // a hyphen doing a minus's job gets a minus's length
    s = s.replace(/(^|[\s(=×·+\-−±/^{,])-(?=[\dA-Za-zα-ωΑ-Ω(√.])/g, '$1−').replace(/\s-\s/g, ' − ');
    s = s.replace(/([0-9A-Za-z)])-(?=\d)/g, '$1−').replace(/(\d)-(?=[A-Za-z(])/g, '$1−');           // n-1, 2-x
    if (/[=≈]/.test(s)) s = s.replace(/(^|[^A-Za-z])([A-Za-z])-(?=[A-Za-z]([^A-Za-z]|$))/g, '$1$2−');   // a-b in an equation
    return s.replace(/\s+/g, ' ').trim();
}

/** A written line as pieces: text runs, spaces, powers, subscripts, fractions and roots. */
function boardParse(s) {
    let i = 0, accent = false;
    const SCRIPT = /^[-+−]?[0-9A-Za-zα-ωΑ-Ω.°′]+/;

    function group(open, close) {                       // s[i] is `open`: the pieces up to its partner
        i++;
        const items = seq(close);
        if (s[i] === close) i++;
        return items;
    }

    function operand(re) {                               // what a ^, _ or √ applies to
        if (s[i] === '{') return group('{', '}');
        if (s[i] === '(') return group('(', ')');
        const m = re.exec(s.slice(i));
        if (!m) return null;
        i += m[0].length;
        return [{ t: 'txt', s: m[0], accent }];
    }

    function seq(stop) {
        const items = [];
        const put = (ch) => {
            const last = items[items.length - 1];
            if (last && last.t === 'txt' && last.accent === accent) last.s += ch;
            else items.push({ t: 'txt', s: ch, accent });
        };
        while (i < s.length && s[i] !== stop) {
            const c = s[i];
            if (c === '\u0002') { accent = true; i++; }
            else if (c === '\u0003') { accent = false; i++; }
            else if (c === ' ') { if (items.length && items[items.length - 1].t !== 'sp') items.push({ t: 'sp' }); i++; }
            else if (c === '\u0001') {                   // \frac{a}{b}
                i++;
                const num = s[i] === '{' ? group('{', '}') : [];
                const den = s[i] === '{' ? group('{', '}') : [];
                items.push({ t: 'frac', num, den });
            } else if (c === '√') {
                i++;
                const kids = operand(/^[0-9A-Za-zα-ωΑ-Ω.]+/);
                if (kids) items.push({ t: 'sqrt', kids }); else put('√');
            } else if ((c === '^' || c === '_') && items.length && items[items.length - 1].t !== 'sp'
                && i + 1 < s.length && s[i + 1] !== ' ' && s[i + 1] !== c) {
                i++;
                const kids = operand(SCRIPT);
                if (kids) items.push({ t: c === '^' ? 'sup' : 'sub', kids }); else put(c);
            } else if (c === '{') { items.push(...group('{', '}')); }
            else if (c === '}') { i++; }
            else { put(c); i++; }
        }
        return items;
    }
    return seq(null);
}

const plain = (items) => items.map((it) => (it.t === 'txt' ? it.s : it.t === 'sp' ? ' ' : it.t === 'frac'
    ? `(${plain(it.num)})/(${plain(it.den)})` : it.t === 'sqrt' ? `√(${plain(it.kids)})` : (it.t === 'sup' ? '^' : '_') + plain(it.kids))).join('');

/** "a/b", "(a+b)/c" and "G m1 m2 / r^2" become fractions, the way they are written on a board;
 *  "m/s", "and/or" and dates stay on the line. */
function boardStack(items, mathsLine) {
    items = items.map((it) => (it.t === 'sqrt' ? { ...it, kids: boardStack(it.kids, mathsLine) }      // √(L/g)
        : it.t === 'frac' ? { ...it, num: boardStack(it.num, mathsLine), den: boardStack(it.den, mathsLine) } : it));
    // chunks: runs between spaces, with brackets kept whole ("(-b ± √x)" is one chunk)
    const chunks = [];
    let cur = [], depth = 0;
    for (const it of items) {
        if (it.t === 'sp' && depth <= 0) { if (cur.length) chunks.push(cur); cur = []; depth = 0; continue; }
        if (it.t === 'txt') for (const ch of it.s) depth += ch === '(' ? 1 : ch === ')' ? -1 : 0;
        cur.push(it);
    }
    if (cur.length) chunks.push(cur);

    const text = (c) => plain(c);
    const OPERATOR = /^[=+\-−±≈<>≤≥≠:,;→⇒]+$/;
    const UNIT = /^[A-Za-zµμΩ°%]{1,4}(\^?[-−]?\d)?$/;
    const WORDS = /^[A-Za-z]+$/;
    const NUMBER = /^[-−]?\d[\d.,]*$/;
    const unwrap = (c) => {                              // "(a+b)" → a+b when the brackets wrap all of it
        const t = text(c);
        if (c.length && t.startsWith('(') && t.endsWith(')')) {
            let d = 0, whole = true;
            for (let k = 0; k < t.length - 1; k++) { d += t[k] === '(' ? 1 : t[k] === ')' ? -1 : 0; if (d === 0) { whole = false; break; } }
            if (whole) {
                const out = c.map((it) => ({ ...it }));
                const first = out[0], last = out[out.length - 1];
                if (first.t === 'txt' && last.t === 'txt') {
                    first.s = first.s.slice(1);
                    last.s = last.s.slice(0, -1);
                    return out.filter((it) => it.t !== 'txt' || it.s);
                }
            }
        }
        return c;
    };
    const worth = (left, right, before) => {
        const a = text(left), b = text(right);
        if (!a || !b) return false;
        if (WORDS.test(a) && WORDS.test(b) && !mathsLine) return false;            // and/or, w/o
        if (UNIT.test(a) && UNIT.test(b) && before && NUMBER.test(before)) return false;   // 5 m/s
        if (WORDS.test(a) && WORDS.test(b) && a.length > 2 && b.length > 2) return false;  // input/output
        return mathsLine || /\d|\(/.test(a + b);
    };
    const join = (list) => list.reduce((acc, c, k) => acc.concat(k ? [{ t: 'sp' }] : [], c), []);

    const out = [];                                      // chunks again, some now fractions
    for (let k = 0; k < chunks.length; k++) {
        const c = chunks[k], t = text(c);
        if (t === '/' && out.length && k + 1 < chunks.length) {
            // everything multiplied together on each side goes over / under the bar
            let a = out.length;
            while (a > 0 && !OPERATOR.test(text(out[a - 1])) && text(out[a - 1]) !== '/') a--;
            let b = k + 1;
            while (b < chunks.length && !OPERATOR.test(text(chunks[b])) && text(chunks[b]) !== '/'
                && !(b > k + 1 && /[.?!]$/.test(text(chunks[b - 1])))) b++;
            const left = out.slice(a), right = chunks.slice(k + 1, b);
            const before = a > 0 ? text(out[a - 1]) : '';
            if (left.length && right.length && left.length <= 4 && right.length <= 4
                && worth(join(left), join(right), before)) {
                out.length = a;
                out.push([{ t: 'frac', num: unwrap(join(left)), den: unwrap(join(right)) }]);
                k = b - 1;
                continue;
            }
        }
        // one slash inside the chunk, outside any bracket: V/R, (a+b)/c, 1/2
        let at = null, d = 0, slashes = 0;
        c.forEach((it, n) => {
            if (it.t !== 'txt') return;
            [...it.s].forEach((ch, m) => {
                d += ch === '(' ? 1 : ch === ')' ? -1 : 0;
                if (ch === '/' && d === 0) { slashes++; at = [n, m]; }
            });
        });
        if (slashes === 1) {
            const [n, m] = at;
            const left = c.slice(0, n).concat(c[n].s.slice(0, m) ? [{ ...c[n], s: c[n].s.slice(0, m) }] : []);
            const right = (c[n].s.slice(m + 1) ? [{ ...c[n], s: c[n].s.slice(m + 1) }] : []).concat(c.slice(n + 1));
            // a comma or full stop after it belongs to the sentence, not under the bar
            let tail = null;
            const end = right[right.length - 1], stop = end && end.t === 'txt' && /[.,;:!?]+$/.exec(end.s);
            if (stop) {
                tail = { ...end, s: stop[0] };
                right[right.length - 1] = { ...end, s: end.s.slice(0, -stop[0].length) };
                if (!right[right.length - 1].s) right.pop();
            }
            const before = out.length ? text(out[out.length - 1]) : '';
            if (worth(left, right, before)) { out.push([{ t: 'frac', num: unwrap(left), den: unwrap(right) }].concat(tail ? [tail] : [])); continue; }
        }
        out.push(c);
    }
    return join(out);
}

class Blackboard {
    constructor(host, font, opts = {}) {
        this.host = host;
        this.font = font;
        this.W = 1600;
        this.em = opts.em || 60;                         // the size of ordinary writing
        this.pad = { x: 110, top: 110, bottom: 200 };    // bottom: room for whatever sits under the board
        this.rate = 1;                                   // 1 = a teacher's pace; the student can change it
        this.lines = [];
        this.jobs = [];                                  // every pen stroke, in order, with its times
        this.head = 0;                                   // the first stroke not finished yet
        this.clock = 0;                                  // writing time, in ms (stands still while paused)
        this.end = 0;                                    // when the last scheduled stroke finishes
        this.waiters = [];
        this.paused = false;
        this.y = this.pad.top;                           // where the next line starts
        this.scroll = 0;
        this.scrollTo = 0;
        this.accentAt = 0;
        this.seed = 20261110;
        this.svg = document.createElementNS(SVGNS, 'svg');
        this.svg.setAttribute('class', 'bb-svg');
        this.ink = document.createElementNS(SVGNS, 'g');
        this.pen = document.createElementNS(SVGNS, 'circle');
        this.pen.setAttribute('r', '5.5');
        this.pen.setAttribute('class', 'bb-pen');
        this.pen.style.opacity = '0';
        this.ink.appendChild(this.pen);
        this.svg.appendChild(this.ink);
        host.appendChild(this.svg);
        this.fit = () => {
            const r = host.getBoundingClientRect();
            this.H = r.width > 0 ? this.W * r.height / r.width : 900;
            this.svg.setAttribute('viewBox', `0 0 ${this.W} ${this.H.toFixed(1)}`);
        };
        this.fit();
        this.observer = new ResizeObserver(this.fit);
        this.observer.observe(host);
        this.onWheel = (e) => {                          // looking back at what was written earlier
            const max = Math.max(0, this.y - this.H * 0.5);
            this.scrollTo = Math.max(0, Math.min(max, this.scrollTo + e.deltaY * (this.W / host.clientWidth)));
            this.looking = true;
        };
        host.addEventListener('wheel', this.onWheel, { passive: true });
        this.last = performance.now();
        this.alive = true;
        const tick = (now) => {
            if (!this.alive) return;
            this.frame(Math.min(80, now - this.last));
            this.last = now;
            this.raf = requestAnimationFrame(tick);
        };
        this.raf = requestAnimationFrame(tick);
    }

    destroy() {
        this.alive = false;
        cancelAnimationFrame(this.raf);
        this.observer.disconnect();
        this.host.removeEventListener('wheel', this.onWheel);
        this.svg.remove();
        this.waiters.forEach((w) => w.done());
        this.waiters = [];
    }

    random() {                                           // the same wobble every time (mulberry32)
        let t = this.seed += 0x6D2B79F5;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    }

    glyph(ch) {
        const g = this.font.glyphs;
        if (g[ch]) return g[ch];
        const base = ch.normalize('NFKD')[0];
        return g[base] || null;
    }

    // ── measuring ────────────────────────────────────────────────────
    width(str, size) {
        let w = 0;
        for (const ch of str) { const g = this.glyph(ch); w += (g ? g.a : 420) * size / 1000; }
        return w;
    }

    /** How far these pieces reach above and below their baseline. A row of writing always takes a full line's
     *  room (`tight` false); the top and bottom of a fraction take only what their own letters need. */
    measure(items, size, tight = false) {
        const f = this.font;
        let w = 0, asc = (tight ? f.xh : f.asc + 50) / 1000 * size, desc = (tight ? 20 : f.desc * 0.8) / 1000 * size;
        for (const it of items) {
            const m = this.box(it, size);
            w += m.w; asc = Math.max(asc, m.asc); desc = Math.max(desc, m.desc);
        }
        return { w, asc, desc };
    }

    reach(g) {                                           // a letter's own top and bottom, found once
        if (g.hi === undefined) {
            g.hi = 0; g.lo = 0;
            for (const s of g.s) for (let p = 1; p < s.length; p += 2) { g.hi = Math.max(g.hi, s[p]); g.lo = Math.min(g.lo, s[p]); }
        }
        return g;
    }

    box(it, size) {
        const f = this.font, cap = f.cap / 1000 * size, axis = f.xh / 1000 * size * 0.56;
        if (it.t === 'txt') {
            let w = 0, hi = 0, lo = 0;
            for (const ch of it.s) {
                const g = this.glyph(ch);
                w += (g ? g.a : 420) * size / 1000;
                if (g) { this.reach(g); hi = Math.max(hi, g.hi); lo = Math.min(lo, g.lo); }
            }
            return { w, asc: hi / 1000 * size, desc: -lo / 1000 * size };
        }
        if (it.t === 'sp') return { w: size * 0.34, asc: 0, desc: 0 };
        if (it.t === 'sup') { const m = this.measure(it.kids, size * 0.6, true); return { w: m.w + size * 0.05, asc: cap * 0.58 + m.asc, desc: 0, m }; }
        if (it.t === 'sub') { const m = this.measure(it.kids, size * 0.6, true); return { w: m.w + size * 0.05, asc: 0, desc: size * 0.14 + m.desc, m }; }
        if (it.t === 'frac') {
            const n = this.measure(it.num, size * 0.84, true), d = this.measure(it.den, size * 0.84, true), gap = size * 0.1;
            return { w: Math.max(n.w, d.w) + size * 0.36, asc: axis + gap + n.desc + n.asc, desc: gap + d.asc + d.desc - axis, n, d, gap, axis };
        }
        if (it.t === 'sqrt') { const m = this.measure(it.kids, size, true); return { w: m.w + size * 0.66, asc: m.asc + size * 0.2, desc: m.desc, m }; }
        return { w: 0, asc: 0, desc: 0 };
    }

    // ── placing: pieces become pen strokes, in the order a hand would make them ─────────────
    stroke(points, color, width, lift = 0) {
        let len = 0;
        for (let k = 2; k < points.length; k += 2) len += Math.hypot(points[k] - points[k - 2], points[k + 1] - points[k - 1]);
        return { points, color, width, len: Math.max(len, 0.5), lift };
    }

    place(items, x, base, size, color, out, slope) {
        for (const it of items) {
            const m = this.box(it, size);
            if (it.t === 'txt') {
                const ink = it.accent ? this.accent : color;
                for (const ch of it.s) {
                    const g = this.glyph(ch);
                    if (g) {
                        const k = size / 1000 * (1 + (this.random() - 0.5) * 0.05);
                        const turn = (this.random() - 0.5) * 0.045, dy = (this.random() - 0.5) * size * 0.035;
                        const cos = Math.cos(turn), sin = Math.sin(turn), cx = g.a / 2;
                        const y0 = base + (x - slope.x0) * slope.k + dy;
                        g.s.forEach((s, n) => {
                            const pts = new Array(s.length);
                            for (let p = 0; p < s.length; p += 2) {
                                const px = s[p] - cx, py = s[p + 1];
                                pts[p] = x + (cx + px * cos - py * sin) * k;
                                pts[p + 1] = y0 - (px * sin + py * cos) * k;
                            }
                            out.push(this.stroke(pts, ink, this.penWidth(size), n ? 0 : 1));
                        });
                    }
                    x += (g ? g.a : 420) * size / 1000;
                }
            } else if (it.t === 'sp') {
                x += m.w;
                if (out.length) out[out.length - 1].space = true;
            } else if (it.t === 'sup') {
                this.place(it.kids, x + size * 0.03, base - this.font.cap / 1000 * size * 0.58, size * 0.6, color, out, slope); x += m.w;
            } else if (it.t === 'sub') {
                this.place(it.kids, x + size * 0.03, base + size * 0.14, size * 0.6, color, out, slope); x += m.w;
            } else if (it.t === 'frac') {
                const tilt = (x - slope.x0) * slope.k, bar = base - m.axis + tilt, s2 = size * 0.84;
                this.place(it.num, x + (m.w - m.n.w) / 2, bar - m.gap - m.n.desc - tilt, s2, color, out, slope);
                const wob = (this.random() - 0.5) * size * 0.05;
                out.push(this.stroke([x + size * 0.05, bar + wob, x + m.w / 2, bar - wob * 0.6, x + m.w - size * 0.05, bar + wob * 0.4],
                    color, this.penWidth(size), 1));
                this.place(it.den, x + (m.w - m.d.w) / 2, bar + m.gap + m.d.asc - tilt, s2, color, out, slope);
                x += m.w;
            } else if (it.t === 'sqrt') {                // the tick, up the slope, then the bar over what is inside
                const y = base + (x - slope.x0) * slope.k, top = y - m.m.asc - size * 0.12, low = y + Math.max(m.m.desc - size * 0.04, size * 0.02);
                out.push(this.stroke([x + size * 0.04, y - size * 0.3, x + size * 0.17, y - size * 0.34, x + size * 0.3, low,
                    x + size * 0.5, top, x + m.w - size * 0.04, top + (this.random() - 0.5) * size * 0.04], color, this.penWidth(size), 1));
                this.place(it.kids, x + size * 0.58, base, size, color, out, slope); x += m.w;
            }
        }
        return x;
    }

    penWidth(size) { return Math.max(2.2, size * 0.052); }

    /** Break the pieces into rows that fit the board (only at spaces; a fraction stays whole). */
    rows(items, size, room) {
        const rows = [];
        let row = [], w = 0, word = [], ww = 0;
        const flush = () => {
            if (!word.length) return;
            if (row.length && w + ww > room) { while (row.length && row[row.length - 1].t === 'sp') row.pop(); rows.push(row); row = []; w = 0; }
            row.push(...word); w += ww; word = []; ww = 0;
        };
        for (const it of items) {
            if (it.t === 'sp') { flush(); if (row.length) { row.push(it); w += this.box(it, size).w; } }
            else { word.push(it); ww += this.box(it, size).w; }
        }
        flush();
        while (row.length && row[row.length - 1].t === 'sp') row.pop();
        if (row.length) rows.push(row);
        return rows;
    }

    // ── writing ──────────────────────────────────────────────────────
    /** Write one line of a lesson. Resolves when the pen has finished it. */
    write(text, opts = {}) {
        let raw = String(text || '').trim();
        if (!raw) return Promise.resolve();
        let kind = 'plain';
        const h = /^#{1,3}\s+(.*)$/.exec(raw), b = /^(?:[-•–]\s+)(.*)$/.exec(raw);
        if (h) { kind = 'heading'; raw = h[1]; }
        else if (b) { kind = 'bullet'; raw = b[1]; }
        else if (/^\W*(final\s+)?answer\W*:/i.test(raw)) kind = 'answer';
        if (opts.kind) kind = opts.kind;
        const tidy = boardTidy(raw);
        if (!tidy) return Promise.resolve();
        this.lines.push((kind === 'heading' ? '# ' : kind === 'bullet' ? '- ' : '') + tidy.replace(/[\u0001-\u0003]/g, ''));
        const maths = /[=≈≤≥<>]/.test(tidy) && kind !== 'heading';
        const items = boardStack(boardParse(tidy), maths);
        const size = this.em * (kind === 'heading' ? 1.34 : 1) * (opts.scale || 1);
        const color = BOARD_INK[opts.color] || opts.color || (kind === 'heading' ? BOARD_INK.yellow : kind === 'answer' ? BOARD_INK.green : BOARD_INK.white);
        this.accent = BOARD_INK[BOARD_ACCENTS[this.accentAt % BOARD_ACCENTS.length]];
        if (tidy.includes('\u0002')) this.accentAt++;
        const indent = (kind === 'bullet' ? size * 0.95 : 0) + (opts.indent || 0) * size + (maths && kind === 'plain' ? size * 0.5 : 0);
        const x0 = this.pad.x + indent, room = this.W - this.pad.x - x0;
        const rows = this.rows(items, size, room);
        const strokes = [];
        const top = this.y;
        let right = x0, first = true;
        for (const row of rows) {
            const m = this.measure(row, size);
            const base = this.y + m.asc;
            const slope = { x0, k: (this.random() - 0.5) * 0.012 };
            const from = strokes.length;
            if (first && kind === 'bullet') {
                const cy = base - size * 0.2, bx = this.pad.x + (opts.indent || 0) * size + size * 0.3;
                strokes.push(this.stroke([bx - size * 0.16, cy + (this.random() - 0.5) * 3, bx + size * 0.16, cy + (this.random() - 0.5) * 3],
                    this.accent, this.penWidth(size) * 1.15, 1));
            }
            const end = this.place(row, x0, base, size, color, strokes, slope);
            if (strokes.length > from) strokes[from].newRow = true;
            right = Math.max(right, end);
            this.y = base + m.desc + size * 0.16;
            first = false;
        }
        const pw = this.penWidth(size);
        if (kind === 'heading') {                        // underlined by hand
            const y = this.y - size * 0.2, w1 = (this.random() - 0.5) * 6, w2 = (this.random() - 0.5) * 6;
            strokes.push(this.stroke([x0 - 6, y + w1, (x0 + right) / 2, y + w2, right + 10, y - w1], color, pw, 1));
            this.y += size * 0.3;
        } else if (kind === 'answer') {                  // boxed
            const a = x0 - size * 0.32, c = right + size * 0.32, t = top - size * 0.06, u = this.y - size * 0.02, j = () => (this.random() - 0.5) * 5;
            strokes.push(this.stroke([a + j(), t + j(), c + j(), t + j(), c + j(), u + j(), a + j(), u + j(), a + j(), t + j() - 3], color, pw, 1));
            this.y += size * 0.34;
        }
        this.y += (opts.gap !== undefined ? opts.gap : 0.1) * size;
        return this.schedule(strokes, top, this.y, opts.duration);
    }

    /** Leave some empty board before the next thing. */
    space(lines = 0.6) { this.y += this.em * lines; }

    schedule(strokes, top, bottom, duration) {
        if (!strokes.length) return Promise.resolve();
        const speed = this.em * 26;                      // board units a second with the pen down
        let t = 0;
        const times = strokes.map((s, n) => {
            const prev = strokes[n - 1];
            if (prev) t += 22 + (s.lift ? 30 : 0) + (prev.space ? 70 : 0) + (s.newRow ? 200 : 0);
            const t0 = t;
            t += Math.max(26, s.len / speed * 1000);
            return [t0, t];
        });
        let squeeze = 1;                                 // fit the time it is being said in, within reason
        if (duration) squeeze = Math.max(0.4, Math.min(2.6, duration / t));   // whole sentences: the pen keeps up with the voice
        const start = Math.max(this.clock, this.end) + (this.end > this.clock ? 120 : 0);
        strokes.forEach((s, n) => {
            const el = document.createElementNS(SVGNS, 'path');
            let d = `M${s.points[0].toFixed(1)} ${s.points[1].toFixed(1)}`;
            for (let k = 2; k < s.points.length; k += 2) d += `L${s.points[k].toFixed(1)} ${s.points[k + 1].toFixed(1)}`;
            if (s.points.length === 2) d += `l0.1 0`;
            el.setAttribute('d', d);
            el.setAttribute('class', 'bb-stroke');
            el.setAttribute('stroke', s.color);
            el.setAttribute('stroke-width', s.width.toFixed(2));
            el.style.strokeDasharray = `${(s.len + 2).toFixed(1)}`;
            el.style.strokeDashoffset = `${(s.len + 2).toFixed(1)}`;
            this.ink.insertBefore(el, this.pen);
            this.jobs.push({ el, s, t0: start + times[n][0] * squeeze, t1: start + times[n][1] * squeeze, top, bottom });
        });
        this.end = this.jobs[this.jobs.length - 1].t1;
        return new Promise((done) => this.waiters.push({ at: this.end, done }));
    }

    pause() { this.paused = true; }
    resume() { this.paused = false; this.looking = false; }
    get writing() { return this.head < this.jobs.length; }

    /** Finish what is being written at once (the student skipped ahead). */
    finish() { this.clock = Math.max(this.clock, this.end); }

    /** Wipe the board clean. */
    erase() {
        this.finish();
        return new Promise((done) => {
            const old = [...this.ink.querySelectorAll('.bb-stroke')];
            old.forEach((el) => { el.style.transition = 'opacity .45s'; el.style.opacity = '0'; });
            setTimeout(() => {
                old.forEach((el) => el.remove());
                this.jobs = []; this.head = 0; this.end = this.clock; this.lines = [];
                this.y = this.pad.top; this.scroll = this.scrollTo = 0; this.looking = false;
                this.ink.setAttribute('transform', 'translate(0 0)');
                done();
            }, 470);
        });
    }

    frame(dt) {
        if (!this.paused) this.clock += dt * this.rate;
        let penAt = null;
        while (this.head < this.jobs.length) {
            const j = this.jobs[this.head];
            if (this.clock < j.t0) break;
            if (!this.looking) {                         // keep the line being written in view
                const low = j.bottom - this.scrollTo - (this.H - this.pad.bottom);
                if (low > 0) this.scrollTo = Math.max(this.scrollTo, j.top - this.H * 0.34);
            }
            if (this.clock >= j.t1) {
                j.el.style.strokeDasharray = 'none';
                j.el.style.strokeDashoffset = '0';
                this.head++;
                const p = j.s.points;
                penAt = [p[p.length - 2], p[p.length - 1]];
                continue;
            }
            const f = (this.clock - j.t0) / (j.t1 - j.t0), gone = j.s.len * f;
            j.el.style.strokeDashoffset = `${(j.s.len + 2 - gone).toFixed(1)}`;
            const p = j.s.points;                        // where the pen is along this stroke
            let acc = 0;
            penAt = [p[0], p[1]];
            for (let k = 2; k < p.length; k += 2) {
                const seg = Math.hypot(p[k] - p[k - 2], p[k + 1] - p[k - 1]);
                if (acc + seg >= gone) { const u = seg ? (gone - acc) / seg : 0; penAt = [p[k - 2] + (p[k] - p[k - 2]) * u, p[k - 1] + (p[k + 1] - p[k - 1]) * u]; break; }
                acc += seg; penAt = [p[k], p[k + 1]];
            }
            break;
        }
        if (penAt && this.head < this.jobs.length && !this.paused) {
            this.pen.setAttribute('cx', penAt[0].toFixed(1));
            this.pen.setAttribute('cy', penAt[1].toFixed(1));
            this.pen.style.opacity = '1';
        } else if (this.head >= this.jobs.length || this.paused) this.pen.style.opacity = '0';
        if (this.waiters.length) {
            const due = this.waiters.filter((w) => this.clock >= w.at);
            if (due.length) { this.waiters = this.waiters.filter((w) => this.clock < w.at); due.forEach((w) => w.done()); }
        }
        if (Math.abs(this.scrollTo - this.scroll) > 0.3) {
            this.scroll += (this.scrollTo - this.scroll) * (1 - Math.exp(-dt / 150));
            this.ink.setAttribute('transform', `translate(0 ${(-this.scroll).toFixed(1)})`);
        }
    }
}

if (typeof module !== 'undefined') module.exports = { boardTidy, boardParse, boardStack, plain };
