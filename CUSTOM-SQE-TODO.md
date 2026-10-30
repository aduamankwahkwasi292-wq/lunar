# CUSTOM-SQE: maths practice in MrSOLIS 3 (to-do)

The user (2026-10-28): put an **SQE** button in **Quizzes** that opens the **MrSOLIS 2-AL** window, matching MrSOLIS 3,
for maths question practice.
- The engine behind it is called **CUSTOM-SQE**.
- Tell students in How to use how to bring their own questions.
- Improve the engine so it handles far more kinds of questions, asked in more ways.
- Also: "Practise more like this".

Source: the user's MrSOLIS 2-AL (`Downloads\mrsolis-2-al\pp`, package `qgen`). The original is not changed.

## Phase 1: bring the engine in (done 2026-10-28)
- [x] Copy the engine into `backend/sqe/` as CUSTOM-SQE. It needs only sympy, which MrSOLIS 3 already ships.
      Left out: the PowerPoint/PDF readers, the scikit-learn near-duplicate filter (`dedup.py` keeps exact-repeat
      and per-fact checks) and the SQLite deck store (`store.py` is in memory, per practice session).
- [x] A question bank to measure it: `scripts/sqe_bank.json`, 201 student-style questions in 20 topics.
      `python scripts/sqe_check.py` scores it.
      **Baseline: 34/201 (17%).** Proofs 3/3, limits 5/8, electrical 5/15, differentiation 5/15, integration 5/12,
      mechanics 4/15, linear 3/10, quadratic 2/8, indices 1/10, mensuration 1/8. These score 0: money, number,
      algebra, inequalities, sequences, trigonometry, coordinates, matrices, statistics, complex numbers.
- [x] Backend: `POST /api/sqe/generate` and `POST /api/sqe/check` (backend/sqe/api.py).
      - They run on one worker thread with a 25 s limit.
      - Marking: 27/27 cases right (units, fractions/decimals/percent, "x =", "+ C", roots in any order).
- Quality issues seen, for Phase 3:
  - fractional coefficients ("21x²/2 + 8x/5" from "3x² + 2x");
  - a 0/0 limit's versions stop being 0/0;
  - "2x + 3 = 11" comes back as "6x − 16/3 = 0".
  Versions should keep the student's form, with whole numbers unless asked.

## Phase 2: the SQE window (MrSOLIS 2-AL, in MrSOLIS 3's look) (done 2026-10-28)
- [x] **SQE** button on the Quizzes page. It opens its own window: the black & white steel frame, MrSOLIS 3's
      fonts and window buttons.
- [x] Flow: type or paste a question → how many (5 / 10 / 15 / 20) → optional timer → one question at a time
      (multiple choice or type the answer) → live score → review with worked steps for every question →
      "Again with new numbers".
- [x] On-screen maths keyboard (√ π ^ fractions ∫ d/dx lim sin cos log …), like 2-AL's.
- [x] Fair marking of typed answers: 0.5 = 1/2, 2(x+1) = 2x+2, units optional. Always shows the right answer and
      the steps.
- [x] Practice sessions saved in History (score per session).
- [x] **"Practise more like this"** on a solved problem (class, chat, Solver) opens SQE with that question filled in.
- Built: `frontend/sqe.html` + `static/mrsolis-sqe.js/.css`; the window in `desktop/main.js` (`openSqe`, one
  window, question passed in by IPC, closes with MrSOLIS); buttons in Quizzes, Tools → Solver and under the board's
  Solve answers; History line "Practised maths". Multiple-choice options are written alike (`api.even_options`), so
  "f'(x) =" or a unit never gives the answer away.
- Checked: browser flow (answer, type, review, again, timer, keyboard, leave) and the real Electron shell
  (9 checks: opens, one window, prefill, mid-practice safety, main-window-only IPC, its buttons, closes with MrSOLIS).

## Phase 3: a much bigger and better engine (done 2026-10-29)

**Design (decided 2026-10-28, built 2026-10-29).** "Better, not just bigger": every version should read like the
student's own question, with clean numbers and a checked answer.
- **Number slots.** Every number in the student's text becomes a slot: its span, its value, and whether it is signed
  (it owns a "+"/"-"), an exponent (after "^" or a superscript), a coefficient or an ordinal. A version is the
  student's exact text with new slot values. Signs re-render as "+ 7" or "- 7"; a coefficient of 1 is dropped
  ("x", not "1x"). The display keeps the student's own notation (², ×, √).
- **Symbolic template.** The same text with each slot as a sympy symbol `(S0)`, `(S1)`… is parsed by the family. A
  version is the template with new values substituted.
- **Answer first, then back-solve.** For equations, pick the root(s) first (integers when the original's were),
  then solve the template for the dependent slots (usually each equation's constant). The same trick keeps a 0/0
  limit 0/0, gives quadratics integer roots and keeps a word problem's answer as clean as the original's.
- **Families**, one module each: calculus, equations, algebra (simplify/expand/factorise, indices/surds/logs),
  number, sequences, trig, coordinates/vectors/circles, mensuration, matrices, statistics/probability, complex
  numbers, word problems (formula table, answer-first), proofs (old module), and a safe generic "evaluate with new
  numbers" fallback.
- **Checks.** Every version is re-parsed from its displayed text and must give the same answer. Each family also
  has its own independent check: substitute back, compare numerically, or differentiate an integral.
- **Answers.** Exact where the question is exact (fractions, surds, π); 3 significant figures for measured
  quantities, with a space before the unit.
- **Wrong options** come from real mistakes (each family), formatted alike (`api.even_options`).
- **Safety.** Parse with a whitelist of characters and names before `parse_expr`, because it runs `eval`. Apply the
  same whitelist to `api.check` on typed answers.
- **Time.** At most ~40 tries per version and a time budget per request. Variations keep the original's shape, so
  sympy stays as fast as it was on the original.
- **Measuring.** `scripts/sqe_check.py` reports coverage plus quality flags: fractions the original didn't have,
  repeats, failed checks and timings. Write a held-out bank B (`scripts/sqe_bank_b.json`, new phrasings) before
  tuning, and report both banks. Target ≥ 85–90% on each.
- **Packaging.** The packaged app finds modules by following imports from `backend/run.py`. Import the family
  modules statically, never by name at run time, or the packaged app won't include them.
- [x] More phrasings and notation: "find dy/dx", "d/dx", "derivative of", "∫ … dx", x², √, 2x, 3(x+1), sin²x,
      LaTeX-style input, "work out", "evaluate", "what is".
- [x] Algebra: simplify, expand, factorise; simultaneous equations (2 and 3 unknowns); quadratics (formula,
      discriminant, completing the square); inequalities; indices and surds; logarithms and exponential equations;
      remainder and factor theorem; partial fractions.
- [x] Number: fractions, decimals, percentages; ratio and proportion; HCF, LCM and prime factors; standard form;
      significant figures; number bases; modular arithmetic.
- [x] Calculus: product, quotient and chain rule; higher derivatives; definite integrals; integration by parts and
      by substitution; limits at infinity; stationary points; rates of change; area under a curve; simple
      differential equations.
- [x] Sequences and series: arithmetic and geometric (nth term, sum, sum to infinity); binomial expansion.
- [x] Trigonometry: right triangles, sine and cosine rules, area of a triangle, exact values, solving trig equations
      in a range, radians ↔ degrees.
- [x] Coordinate geometry and vectors: gradient, distance, midpoint, equation of a line, circles; magnitude, dot
      product, angle between vectors.
- [x] Matrices: determinant, inverse, product, solving systems.
- [x] Statistics and probability: mean, median, mode, range and standard deviation of a list; probability;
      permutations and combinations; expected value.
- [x] Complex numbers: arithmetic, modulus and argument, polar form.
- [x] Word problems: many more formulas and unit conversions.
      - Money: simple and compound interest, profit and loss %, discount.
      - Motion: speed-distance-time, suvat.
      - Physics: density, pressure, heat, gas laws, waves, lenses, momentum, energy.
      - Electrical: series and parallel resistors, capacitors, AC.
- [x] A safe "anything else" path: any question with numbers in it that sympy can compute gets new versions with
      new numbers, recomputed.
- [x] Wrong options built from real common mistakes, and worked steps, for every new type.
- [x] Difficulty: easy / medium / hard.
- [x] Every generated answer re-checked an independent way (substitute back, numeric check) before it's shown.

**Results (2026-10-29).**
- Coverage:
  - bank A: 198/201 (99%), up from 34/201 (17%);
  - bank B (held out, written before the engine): 188/201 (94%) on its first run;
  - after general fixes the first run exposed, bank B is at 198/201. The fixes were standard-form quantities,
    unwritten coefficients, the words around equations, and repeated angles; no single question was tuned.
- Correctness: `scripts/sqe_verify.py` re-reads every version's displayed text without the slot machinery and
  checks the answer a second way. Result: 0 wrong of 394 (A) and 389 (B) answers checked (the algebra and calculus
  kinds; word problems and number questions were hand-checked in an audit).
- Speed: most questions make 10 versions in well under a second (sympy's nsimplify was the slow part: replaced by
  `text.exact`).
- Typed marking (`api.check`) also accepts GHS amounts, "25" for 25%, mixed numbers, "6x + 2" for
  "dy/dx = 6x + 2", degrees and radians: 24/24 cases.
- Code:
  - `backend/sqe/text.py`: slots, normalising, safe parsing, printing.
  - `backend/sqe/core.py`: the version loop, number choice, keep_roots, checks.
  - Families: `fam_calculus.py`, `fam_equations.py`, `fam_words.py`, `fam_algebra.py`, `fam_number.py`,
    `fam_sequences.py`, `fam_stats.py`, `fam_trig.py`, `fam_geometry.py`, `fam_misc.py`.
  - `engine.py`: the order of families and per-session memory.
  - MrSOLIS 2-AL's own pipeline is kept only as a fallback.
- Known gaps:
  - trig identities ("simplify sin²x + cos²x + tan²x");
  - 2cos²x - cos x - 1 = 0 (no written number to change in the middle term);
  - ∫ sin x from 0 to π (other numbers give messy answers);
  - a question asking two things answers the first only.
- Lessons:
  - Shell heredocs halve backslashes (\b becomes a backspace). Write scripts with the file tool, and
    `scratchpad/fix_ctrl.py` finds control characters.
  - "a" was on the English-word list, so "a - 1" was read as a·(-1): single letters next to +/- are variables.

## Phase 4: tell students, and ship (done 2026-10-29, except pushing)
- [x] How to use: a "Practise maths (SQE)" card: what to type, an example for each kind of question, tips (give the
      numbers and say what to find; one question at a time), what it can't do yet.
- [x] Settings → About → Engines: CUSTOM-SQE. Licences & credits: built from MrSOLIS 2-AL; sympy (BSD).
- [x] Tests: the question bank as an automatic test (every type, every answer re-verified), plus a UI test of the
      window.
- [x] Build check: the packaged app includes `backend/sqe` (no size change expected: sympy is already in it).
- [x] Notes: CLAUDE.md and memory.
- What was built:
  - How to use has a "Practise maths (SQE)" card on bringing your own question: examples, what it knows, tips, the
    "Read as" line and what it can't do yet.
  - Licences & credits lists CUSTOM-SQE among the engines, and mpmath next to SymPy.
  - The window shows how a word problem was read ("Read as: P = VI, finding the current"). The review answers the
    student's own question with its working.
  - Tests:
    - `python -m backend.sqe.selftest`: safety, marking, own-question answers checked by hand, and versions for
      every family. All pass in about 9 s.
    - The Electron window test (`scratchpad/sqe-ui-test.mjs`): 10 checks pass.
  - Build: every module is reachable from `api.py` through static imports, so PyInstaller includes them; sympy is
    already collected whole. No spec change.
- Left for the user: pushing the release (nothing has been pushed).

