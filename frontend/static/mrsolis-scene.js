/* ═══════════════════════════════════════════════════════════════════
   MrSOLIS 3 Scene — the black & white backdrop and the board's frame.

   #scene (canvas, behind everything): stars, a greyscale moon peeking
   over the board's top-left corner, a faint perspective floor and a
   halo under the board. #board-frame (SVG): the steel frame around the
   silver writing surface. Both are redrawn whenever the board resizes.
   Everything is procedural and seeded, so it looks the same each time.
   ═══════════════════════════════════════════════════════════════════ */
'use strict';

(() => {
    const canvas = document.getElementById('scene');
    const ctx = canvas.getContext('2d');
    const board = document.getElementById('board');
    const frame = document.getElementById('board-frame');
    const SVGNS = 'http://www.w3.org/2000/svg';

    // keep in step with #board's --frame-* and --cut in mrsolis.css
    const FT = 26, FR = 16, FB = 24, FL = 16, CUT = 18;

    function rng(seed) {                         // mulberry32
        return () => {
            seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
            let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
            t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
    }

    // ── backdrop ──────────────────────────────────────────────────────
    function drawStars(W, H) {
        const r = rng(7);
        const n = Math.round((W * H) / 3800);
        for (let i = 0; i < n; i++) {
            const x = r() * W, y = r() * H;
            const big = r() < 0.06;
            const a = big ? 0.55 + r() * 0.45 : 0.12 + r() * 0.45;
            const s = big ? 1.1 + r() * 0.9 : 0.5 + r() * 0.7;
            ctx.fillStyle = `rgba(255,255,255,${a})`;
            ctx.beginPath(); ctx.arc(x, y, s, 0, Math.PI * 2); ctx.fill();
            if (big && r() < 0.5) {                     // a few with a soft glint
                const g = ctx.createRadialGradient(x, y, 0, x, y, s * 6);
                g.addColorStop(0, `rgba(255,255,255,${a * 0.25})`); g.addColorStop(1, 'rgba(255,255,255,0)');
                ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, s * 6, 0, Math.PI * 2); ctx.fill();
            }
        }
    }

    function drawMoon(cx, cy, R) {
        const r = rng(42);
        ctx.save();
        const halo = ctx.createRadialGradient(cx, cy, R * 0.92, cx, cy, R * 1.45);
        halo.addColorStop(0, 'rgba(255,255,255,0.13)'); halo.addColorStop(1, 'rgba(255,255,255,0)');
        ctx.fillStyle = halo; ctx.beginPath(); ctx.arc(cx, cy, R * 1.45, 0, Math.PI * 2); ctx.fill();

        ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.clip();
        const body = ctx.createRadialGradient(cx - R * 0.42, cy - R * 0.5, R * 0.05, cx, cy, R * 1.02);
        body.addColorStop(0, '#d9d9da'); body.addColorStop(0.42, '#9b9c9e'); body.addColorStop(0.78, '#4a4b4d'); body.addColorStop(1, '#1b1b1c');
        ctx.fillStyle = body; ctx.fillRect(cx - R, cy - R, R * 2, R * 2);
        // maria: broad soft dark seas
        for (let i = 0; i < 10; i++) {
            const mx = cx + (r() - 0.5) * R * 1.4, my = cy + (r() - 0.5) * R * 1.4, mr = R * (0.12 + r() * 0.28);
            const g = ctx.createRadialGradient(mx, my, 0, mx, my, mr);
            g.addColorStop(0, `rgba(0,0,0,${0.16 + r() * 0.14})`); g.addColorStop(1, 'rgba(0,0,0,0)');
            ctx.fillStyle = g; ctx.beginPath(); ctx.arc(mx, my, mr, 0, Math.PI * 2); ctx.fill();
        }
        // craters: soft dark bowls, a faint lit rim towards the light (upper left)
        for (let i = 0; i < 90; i++) {
            const a = r() * Math.PI * 2, d = Math.sqrt(r()) * R;
            const x = cx + Math.cos(a) * d, y = cy + Math.sin(a) * d;
            const cr = R * (r() < 0.1 ? 0.05 + r() * 0.06 : 0.01 + r() * 0.03);
            const bowl = ctx.createRadialGradient(x + cr * 0.25, y + cr * 0.25, 0, x, y, cr);
            bowl.addColorStop(0, `rgba(0,0,0,${0.22 + r() * 0.18})`); bowl.addColorStop(1, 'rgba(0,0,0,0)');
            ctx.fillStyle = bowl; ctx.beginPath(); ctx.arc(x, y, cr, 0, Math.PI * 2); ctx.fill();
            ctx.strokeStyle = `rgba(255,255,255,${0.05 + r() * 0.09})`;
            ctx.lineWidth = Math.max(0.5, cr * 0.16);
            ctx.beginPath(); ctx.arc(x + cr * 0.15, y + cr * 0.15, cr * 0.92, Math.PI * 0.95, Math.PI * 1.7); ctx.stroke();
        }
        // grain
        for (let i = 0; i < R * R * 0.06; i++) {
            const x = cx + (r() - 0.5) * 2 * R, y = cy + (r() - 0.5) * 2 * R;
            ctx.fillStyle = r() < 0.5 ? 'rgba(0,0,0,0.12)' : 'rgba(255,255,255,0.07)';
            ctx.fillRect(x, y, 1, 1);
        }
        // night side
        const night = ctx.createRadialGradient(cx - R * 0.55, cy - R * 0.6, R * 0.6, cx - R * 0.2, cy - R * 0.2, R * 1.6);
        night.addColorStop(0, 'rgba(0,0,0,0)'); night.addColorStop(1, 'rgba(0,0,0,0.85)');
        ctx.fillStyle = night; ctx.fillRect(cx - R, cy - R, R * 2, R * 2);
        ctx.restore();
        // thin bright limb on the lit side
        ctx.strokeStyle = 'rgba(255,255,255,0.35)'; ctx.lineWidth = 1.2;
        ctx.beginPath(); ctx.arc(cx, cy, R - 0.6, Math.PI * 0.95, Math.PI * 1.65); ctx.stroke();
    }

    function drawFloor(W, H, b) {
        const horizon = b.bottom - 6;
        if (horizon >= H) return;
        const vx = b.left + b.width / 2, vy = horizon - H * 0.35;     // vanishing point above the horizon
        ctx.save();
        ctx.beginPath(); ctx.rect(0, horizon, W, H - horizon); ctx.clip();
        const fade = ctx.createLinearGradient(0, horizon, 0, H);
        fade.addColorStop(0, 'rgba(255,255,255,0.0)'); fade.addColorStop(0.35, 'rgba(255,255,255,0.075)'); fade.addColorStop(1, 'rgba(255,255,255,0.13)');
        ctx.strokeStyle = fade; ctx.lineWidth = 1;
        // radiating lines
        const spread = W * 1.6;
        for (let i = -24; i <= 24; i++) {
            const xb = vx + (i / 24) * spread;
            ctx.beginPath(); ctx.moveTo(vx, vy); ctx.lineTo(xb, H); ctx.stroke();
        }
        // receding cross lines
        for (let i = 1; i <= 14; i++) {
            const t = i / 14;
            const y = horizon + (H - horizon) * t * t;
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
        }
        ctx.restore();
        // light spilling from under the board
        const glow = ctx.createRadialGradient(vx, horizon, 0, vx, horizon, b.width * 0.55);
        glow.addColorStop(0, 'rgba(255,255,255,0.13)'); glow.addColorStop(1, 'rgba(255,255,255,0)');
        ctx.save(); ctx.translate(vx, horizon); ctx.scale(1, 0.22); ctx.translate(-vx, -horizon);
        ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(vx, horizon, b.width * 0.55, 0, Math.PI * 2); ctx.fill();
        ctx.restore();
    }

    function drawScene() {
        const dpr = window.devicePixelRatio || 1;
        const W = window.innerWidth, H = window.innerHeight;
        canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H);
        const top = ctx.createRadialGradient(W * 0.55, -H * 0.1, 0, W * 0.55, -H * 0.1, H * 1.1);
        top.addColorStop(0, 'rgba(255,255,255,0.05)'); top.addColorStop(1, 'rgba(255,255,255,0)');
        ctx.fillStyle = top; ctx.fillRect(0, 0, W, H);
        drawStars(W, H);
        const b = board.getBoundingClientRect();
        if (b.width > 0) {
            // the moon peeks over the slide viewer's top-left corner, its dome filling the gap under the top bar
            // (kept near the corner, clear of "Slide 3 of 6" centred above the slide)
            const gap = b.top - document.getElementById('topbar').getBoundingClientRect().bottom;
            const R = Math.max(60, Math.min(150, (gap - 10) / 0.62));
            drawMoon(b.left + R + 14, b.top + R * 0.38, R);
            drawFloor(W, H, b);
        }
    }

    // ── the board frame (SVG) ─────────────────────────────────────────
    /** Offset a closed clockwise (y-down) polygon inward by d (mitred corners). */
    function inset(pts, d) {
        const n = pts.length;
        return pts.map((p, i) => {
            const a = pts[(i - 1 + n) % n], c = pts[(i + 1) % n];
            const n1 = norm(a, p), n2 = norm(p, c);
            const k = d / (1 + n1[0] * n2[0] + n1[1] * n2[1]);
            return [p[0] + (n1[0] + n2[0]) * k, p[1] + (n1[1] + n2[1]) * k];
        });
    }
    function norm(a, b) {
        const dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1;
        return [-dy / l, dx / l];
    }
    const pathOf = (pts) => 'M' + pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join('L') + 'Z';
    const lineOf = (pts) => 'M' + pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join('L');

    function el(name, attrs, parent) {
        const e = document.createElementNS(SVGNS, name);
        for (const k in attrs) e.setAttribute(k, attrs[k]);
        if (parent) parent.appendChild(e);
        return e;
    }

    function drawFrame() {
        const W = Math.round(board.clientWidth), H = Math.round(board.clientHeight);
        if (!W || !H) return;
        frame.setAttribute('viewBox', `0 0 ${W} ${H}`);
        frame.textContent = '';
        const C = 30, s = 9;                                   // outer corner cut, tab step
        const tl = Math.min(W * 0.22, 330), tr = Math.min(W * 0.17, 250);
        const bl = Math.min(W * 0.15, 220), br = Math.min(W * 0.15, 220);
        // outer outline (clockwise): raised tabs top-left/top-right and bottom corners
        const O = [[0, C], [C, 0], [tl, 0], [tl + s, s], [W - tr - s, s], [W - tr, 0], [W - C, 0], [W, C],
            [W, H - C], [W - C, H], [W - br, H], [W - br - s, H - s], [bl + s, H - s], [bl, H], [C, H], [0, H - C]];
        // inner outline = the silver surface's edge
        const x0 = FL, y0 = FT, x1 = W - FR, y1 = H - FB;
        const I = [[x0 + CUT, y0], [x1 - CUT, y0], [x1, y0 + CUT], [x1, y1 - CUT], [x1 - CUT, y1], [x0 + CUT, y1], [x0, y1 - CUT], [x0, y0 + CUT]];

        const defs = el('defs', {}, frame);
        const steel = el('linearGradient', { id: 'f-steel', x1: '0', y1: '0', x2: '0', y2: '1' }, defs);
        [['0', '#5a5d61'], ['0.04', '#2a2c2f'], ['0.5', '#151618'], ['0.96', '#2a2c2f'], ['1', '#55585c']]
            .forEach(([o, c]) => el('stop', { offset: o, 'stop-color': c }, steel));
        const sheen = el('linearGradient', { id: 'f-sheen', x1: '0', y1: '0', x2: '1', y2: '1' }, defs);
        [['0', 'rgba(255,255,255,0.22)'], ['0.3', 'rgba(255,255,255,0)'], ['0.75', 'rgba(255,255,255,0)'], ['1', 'rgba(255,255,255,0.12)']]
            .forEach(([o, c]) => el('stop', { offset: o, 'stop-color': c }, sheen));
        const blur = el('filter', { id: 'f-glow', x: '-5%', y: '-5%', width: '110%', height: '110%' }, defs);
        el('feGaussianBlur', { stdDeviation: '5' }, blur);
        const blurHot = el('filter', { id: 'f-hot', x: '-20%', y: '-400%', width: '140%', height: '900%' }, defs);
        el('feGaussianBlur', { stdDeviation: '4' }, blurHot);

        const band = pathOf(O) + pathOf(I.slice().reverse());
        // halo, metal band, sheen
        el('path', { d: pathOf(O), fill: 'none', stroke: '#fff', 'stroke-width': 3, opacity: 0.4, filter: 'url(#f-glow)' }, frame);
        el('path', { d: band, fill: 'url(#f-steel)', 'fill-rule': 'evenodd' }, frame);
        el('path', { d: band, fill: 'url(#f-sheen)', 'fill-rule': 'evenodd' }, frame);
        // machined edges: bright outer rim, a fine groove, the lit inner lip
        el('path', { d: pathOf(O), fill: 'none', stroke: '#fff', 'stroke-width': 1.5, opacity: 0.95 }, frame);
        el('path', { d: pathOf(inset(O, 5)), fill: 'none', stroke: '#fff', 'stroke-width': 0.8, opacity: 0.32 }, frame);
        el('path', { d: pathOf(inset(I, -3)), fill: 'none', stroke: '#000', 'stroke-width': 2, opacity: 0.7 }, frame);
        el('path', { d: pathOf(I), fill: 'none', stroke: '#fff', 'stroke-width': 1.3, opacity: 0.9 }, frame);

        // light bars, top and bottom centre
        const g = el('g', { stroke: '#fff', 'stroke-linecap': 'round' }, frame);
        const lx0 = W * 0.38, lx1 = W * 0.62;
        for (const y of [s + 0.5, H - s - 0.5]) {
            el('line', { x1: lx0, y1: y, x2: lx1, y2: y, 'stroke-width': 4, opacity: 0.9, filter: 'url(#f-hot)' }, g);
            el('line', { x1: lx0 + 20, y1: y, x2: lx1 - 20, y2: y, 'stroke-width': 1.6 }, g);
        }
        // corner slashes along each outer cut
        const slash = (a, b) => {
            const m = 0.28;
            const ax = a[0] + (b[0] - a[0]) * m, ay = a[1] + (b[1] - a[1]) * m;
            const bx = b[0] - (b[0] - a[0]) * m, by = b[1] - (b[1] - a[1]) * m;
            const n = norm(a, b);
            el('line', { x1: ax + n[0] * 7, y1: ay + n[1] * 7, x2: bx + n[0] * 7, y2: by + n[1] * 7, 'stroke-width': 3, opacity: 0.85 }, g);
        };
        slash([0, C], [C, 0]); slash([W - C, 0], [W, C]); slash([W, H - C], [W - C, H]); slash([C, H], [0, H - C]);
        // dot columns on the sides
        const dots = el('g', { fill: '#fff' }, frame);
        for (const fy of [0.3, 0.7]) {
            for (let i = -2; i <= 1; i++) {
                el('circle', { cx: FL / 2, cy: H * fy + i * 7, r: 1.3, opacity: 0.85 }, dots);
                el('circle', { cx: W - FR / 2, cy: H * fy + i * 7, r: 1.3, opacity: 0.85 }, dots);
            }
        }
        // data dashes on the raised tabs
        const dash = (xa, xb, y) => {
            for (let x = xa, i = 0; x < xb; x += 9, i++) {
                el('rect', { x, y, width: i % 4 === 3 ? 2 : 5, height: 2, fill: '#fff', opacity: i % 4 === 3 ? 0.9 : 0.5 }, frame);
            }
        };
        dash(Math.max(C + 20, tl - 120), tl - 22, 13);
        dash(W - tr + 22, Math.min(W - C - 20, W - tr + 120), 13);
        dash(Math.max(C + 16, bl - 100), bl - 18, H - 13);
        dash(W - br + 18, Math.min(W - C - 16, W - br + 100), H - 13);
    }

    // ── redraw when anything changes size ─────────────────────────────
    let pending = false;
    function redraw() {
        if (pending) return;
        pending = true;
        requestAnimationFrame(() => { pending = false; drawFrame(); drawScene(); });
    }
    new ResizeObserver(redraw).observe(board);
    window.addEventListener('resize', redraw);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(redraw);
    redraw();
})();
