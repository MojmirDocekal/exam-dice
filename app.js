'use strict';

/* Exam Dice — web version of exam_dice.py
 *
 * One "series" draws every number 1..sides at most once; a duplicate is
 * re-rolled automatically (with a visible note).  "New series" resets.
 */

/* ---------------------------------------------------------------- constants */

const MIN_SIDES = 2;
const MAX_SIDES = 30;

// classic silhouettes; other sizes get a generic polygon/oval
const CLASSIC_SHAPES = {
  2: 'coin', 3: 'triangle', 4: 'triangle', 5: 'pentagon', 6: 'square',
  8: 'diamond', 10: 'kite', 12: 'pentagon', 20: 'hexagon',
};

// pip positions on a 3x3 grid [row, col], rows/cols 0..2
const PIP_LAYOUT = {
  1: [[1, 1]],
  2: [[0, 0], [2, 2]],
  3: [[0, 0], [1, 1], [2, 2]],
  4: [[0, 0], [0, 2], [2, 0], [2, 2]],
  5: [[0, 0], [0, 2], [1, 1], [2, 0], [2, 2]],
  6: [[0, 0], [0, 2], [1, 0], [1, 2], [2, 0], [2, 2]],
};

// text placement per shape: [yOffsetFactor, fontSizeFactor]
const TEXT_METRICS = {
  triangle: [0.20, 0.40], square: [0, 0.60], diamond: [0, 0.55],
  kite: [0.05, 0.50], pentagon: [0, 0.55], hexagon: [0, 0.55],
  polygon: [0, 0.50], oval: [0, 0.60],
};

const R = 120; // die radius in SVG user units

/* ---------------------------------------------------------------- helpers */

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const clampSides = (n) => Math.min(MAX_SIDES, Math.max(MIN_SIDES, Math.round(n)));

/** Uniform random integer 1..n using the Web Crypto API. */
function randInt(n) {
  const c = window.crypto || window.msCrypto;
  if (!c || !c.getRandomValues) return 1 + Math.floor(Math.random() * n);
  const limit = Math.floor(0x100000000 / n) * n; // rejection sampling
  const buf = new Uint32Array(1);
  let x;
  do {
    c.getRandomValues(buf);
    x = buf[0];
  } while (x >= limit);
  return (x % n) + 1;
}

/* ---------------------------------------------------------------- sound */

const Sound = {
  on: true,
  ctx: null,
  ensure() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (AC) this.ctx = new AC();
    }
    if (this.ctx && this.ctx.state === 'suspended') this.ctx.resume();
    return this.ctx;
  },
  blip(freq, dur, type, gain, when = 0) {
    if (!this.on) return;
    const ctx = this.ensure();
    if (!ctx) return;
    const t = ctx.currentTime + when;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    g.gain.setValueAtTime(gain, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    osc.connect(g).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + dur + 0.02);
  },
  tick() { this.blip(950 + Math.random() * 300, 0.03, 'square', 0.025); },
  win() { this.blip(660, 0.09, 'sine', 0.06); this.blip(990, 0.14, 'sine', 0.06, 0.09); },
  dup() { this.blip(240, 0.16, 'sawtooth', 0.05); },
};

/* ---------------------------------------------------------------- state */

const state = {
  sides: 6,
  used: new Set(),
  last: null,
  rolling: false,
};

const STORE_KEY = 'exam-dice-v1';

function save() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({
      sides: state.sides,
      used: [...state.used],
      last: state.last,
      sound: Sound.on,
    }));
  } catch { /* private mode etc. */ }
}

function load() {
  try {
    const d = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
    if (!d) return;
    state.sides = clampSides(d.sides || 6);
    if (Array.isArray(d.used)) {
      state.used = new Set(d.used.filter((v) => Number.isInteger(v) && v >= 1 && v <= state.sides));
    }
    if (Number.isInteger(d.last) && state.used.has(d.last)) state.last = d.last;
    Sound.on = d.sound !== false;
  } catch { /* corrupted storage — start fresh */ }
}

/* ---------------------------------------------------------------- SVG die */

const SVG_NS = 'http://www.w3.org/2000/svg';
const dieG = $('die-g');

function svgEl(name, attrs) {
  const e = document.createElementNS(SVG_NS, name);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}

function ngonPoints(r, n, rotDeg = 0) {
  const a0 = ((rotDeg - 90) * Math.PI) / 180;
  const pts = [];
  for (let k = 0; k < n; k++) {
    const a = a0 + (2 * Math.PI * k) / n;
    pts.push((r * Math.cos(a)).toFixed(2) + ',' + (r * Math.sin(a)).toFixed(2));
  }
  return pts.join(' ');
}

/**
 * Draw the die face.  opts:
 *   angle  – rotation in degrees (tumble jitter)
 *   scale  – size multiplier (settle bounce)
 *   coinW  – horizontal squash of the coin (d2 spin)
 *   result – null while tumbling, 'ok' (accepted) or 'dup' (re-rolled)
 */
function renderFace(value, opts = {}) {
  const { angle = 0, scale = 1, coinW = 1, result = null } = opts;
  dieG.setAttribute('transform', `rotate(${angle.toFixed(2)}) scale(${scale.toFixed(3)})`);
  while (dieG.firstChild) dieG.removeChild(dieG.firstChild);

  const sides = state.sides;
  const shape = CLASSIC_SHAPES[sides] || (sides <= 12 ? 'polygon' : 'oval');
  const stroke = result == null ? 'var(--edge)' : (result === 'ok' ? 'var(--ok)' : 'var(--warn)');
  const common = {
    fill: 'var(--face)',
    stroke,
    'stroke-width': result == null ? 5 : 9,
    'stroke-linejoin': 'round',
  };

  if (shape === 'coin') {
    const rw = R * Math.max(coinW, 0.1);
    dieG.appendChild(svgEl('ellipse', { cx: 0, cy: 0, rx: rw, ry: R, ...common }));
    dieG.appendChild(svgEl('ellipse', {
      cx: 0, cy: 0, rx: rw * 0.84, ry: R * 0.84,
      fill: 'none', stroke, 'stroke-width': 2,
    }));
    if (coinW > 0.45) addText(value, 0, 0, R * 0.55);
    return;
  }

  let node;
  if (shape === 'triangle') {
    node = svgEl('polygon', { points: ngonPoints(R, 3), ...common });
  } else if (shape === 'square') {
    node = svgEl('polygon', { points: ngonPoints(R * 0.92, 4, 45), ...common });
  } else if (shape === 'diamond') {
    node = svgEl('polygon', { points: ngonPoints(R, 4), ...common });
  } else if (shape === 'kite') {
    node = svgEl('polygon', {
      points: `0,${-R} ${(0.66 * R).toFixed(2)},${(-0.12 * R).toFixed(2)} 0,${R} ${(-0.66 * R).toFixed(2)},${(-0.12 * R).toFixed(2)}`,
      ...common,
    });
  } else if (shape === 'pentagon') {
    node = svgEl('polygon', { points: ngonPoints(R, 5), ...common });
  } else if (shape === 'hexagon') {
    node = svgEl('polygon', { points: ngonPoints(R, 6), ...common });
  } else if (shape === 'oval') {
    node = svgEl('circle', { cx: 0, cy: 0, r: R, ...common });
  } else {
    node = svgEl('polygon', { points: ngonPoints(R, sides), ...common });
  }
  dieG.appendChild(node);

  if (sides === 6 && Number.isInteger(value)) { // classic pips
    const pr = R * 0.13;
    const span = R * 0.48;
    for (const [row, col] of PIP_LAYOUT[value] || []) {
      dieG.appendChild(svgEl('circle', {
        cx: ((col - 1) * span).toFixed(2),
        cy: ((row - 1) * span).toFixed(2),
        r: pr, fill: 'var(--pip)',
      }));
    }
  } else {
    const [dy, f] = TEXT_METRICS[shape] || [0, 0.55];
    const text = String(value);
    const size = R * f * (text.length >= 2 ? 0.82 : 1);
    addText(value, 0, dy * R, size, value === '?');
  }
}

function addText(value, x, y, size, muted) {
  const t = svgEl('text', {
    x, y,
    'text-anchor': 'middle',
    'dominant-baseline': 'central',
    'font-size': size.toFixed(1),
    fill: muted ? 'var(--muted)' : 'var(--pip)',
  });
  t.textContent = value;
  dieG.appendChild(t);
}

/* ---------------------------------------------------------------- animation */

/** Tumble through random faces and settle on `target`. */
async function tumble(target, final) {
  if (reduceMotion) {
    renderFace(target, { result: final ? 'ok' : 'dup' });
    if (final) Sound.win(); else Sound.dup();
    await sleep(350);
    return;
  }

  const coin = state.sides === 2;
  const DUR = 1450;
  const t0 = performance.now();
  let face = randInt(state.sides);
  let nextFaceAt = 0;
  let spin = (Math.random() < 0.5 ? -1 : 1) * (coin ? 80 : 260); // deg/s
  let angle = 0;
  let phase = Math.random() * Math.PI;
  let last = t0;

  await new Promise((resolve) => {
    const step = (now) => {
      const t = Math.min(1, (now - t0) / DUR);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;

      if (t >= 1) {
        renderFace(target, { scale: 1.12, result: final ? 'ok' : 'dup' });
        resolve();
        return;
      }

      if (now >= nextFaceAt) { // faces change at a slowing rate
        face = randInt(state.sides);
        nextFaceAt = now + 55 + 190 * t * t;
        if (Math.random() < 0.25) spin = -spin;
        Sound.tick();
      }

      angle += spin * dt * (1 - t);      // spin decays
      phase += (1 - t) * dt * 9;         // coin spin slows down
      const scale = 1 + 0.035 * Math.sin(now / 60) * (1 - t);
      renderFace(face, {
        angle,
        scale,
        coinW: coin ? Math.abs(Math.sin(phase)) : 1,
      });
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });

  if (final) Sound.win(); else Sound.dup();
  try { navigator.vibrate && navigator.vibrate(final ? 35 : [20, 40, 20]); } catch { /* iOS */ }
  await sleep(120);
  renderFace(target, { result: final ? 'ok' : 'dup' });
  await sleep(160);
}

/* ---------------------------------------------------------------- UI bits */

function setStatus(msg, cls = '') {
  const s = $('status');
  s.textContent = msg;
  s.className = cls;
}

function buildChips() {
  const box = $('chips');
  box.innerHTML = '';
  for (let i = 1; i <= state.sides; i++) {
    const chip = document.createElement('div');
    chip.className = 'chip';
    chip.textContent = i;
    box.appendChild(chip);
  }
}

function updateChips() {
  const chips = $('chips').children;
  for (let i = 0; i < chips.length; i++) {
    const v = i + 1;
    chips[i].classList.toggle('used', state.used.has(v));
    chips[i].classList.toggle('last', v === state.last);
  }
}

function syncSidesLabel() {
  $('sides-value').textContent = 'd' + state.sides;
}

function syncSoundBtn() {
  const b = $('sound-btn');
  b.textContent = Sound.on ? '🔊' : '🔇';
  b.setAttribute('aria-pressed', String(Sound.on));
}

function updateControls() {
  for (const id of ['roll-btn', 'minus', 'plus', 'new-btn']) {
    $(id).disabled = state.rolling;
  }
}

/* ---------------------------------------------------------------- actions */

async function doRoll() {
  if (state.rolling) return;
  Sound.ensure(); // audio must start from a user gesture
  if (state.used.size >= state.sides) {
    openCompleteDialog();
    return;
  }
  state.rolling = true;
  updateControls();
  setStatus('rolling…');

  for (;;) {
    const v = randInt(state.sides);
    const final = !state.used.has(v);
    await tumble(v, final);
    if (final) {
      state.used.add(v);
      state.last = v;
      updateChips();
      const done = state.used.size >= state.sides;
      setStatus(
        done
          ? `question #${v} — series complete!`
          : `question #${v} · ${state.used.size}/${state.sides} drawn`,
        done ? 'warn' : 'ok',
      );
      save();
      state.rolling = false;
      updateControls();
      if (done) setTimeout(openCompleteDialog, 500);
      return;
    }
    setStatus(`${v} was already drawn — rolling again…`, 'warn');
    await sleep(850);
  }
}

function newSeries() {
  if (state.rolling) return;
  state.used.clear();
  state.last = null;
  updateChips();
  renderFace('?');
  setStatus(`d${state.sides} — new series, every number available`);
  save();
}

function setSides(n) {
  if (state.rolling) return;
  n = clampSides(n);
  if (n === state.sides) {
    syncSidesLabel();
    return;
  }
  if (state.used.size > 0 &&
      !window.confirm(`Switch to d${n}? The current series will be cleared.`)) {
    syncSidesLabel();
    return;
  }
  state.sides = n;
  state.used.clear();
  state.last = null;
  buildChips();
  updateChips();
  renderFace('?');
  syncSidesLabel();
  setStatus(`d${n} — new series started`);
  save();
}

function openCompleteDialog() {
  const dlg = $('complete');
  const text = `All ${state.sides} numbers have been drawn.`;
  if (typeof dlg.showModal === 'function') {
    $('complete-text').textContent = text;
    if (!dlg.open) dlg.showModal();
  } else if (window.confirm(text + '\n\nStart a new series?')) {
    newSeries();
  }
}

/* ---------------------------------------------------------------- events */

$('roll-btn').addEventListener('click', doRoll);
$('new-btn').addEventListener('click', newSeries);
$('dialog-new').addEventListener('click', () => { $('complete').close(); newSeries(); });
$('dialog-close').addEventListener('click', () => $('complete').close());

$('sound-btn').addEventListener('click', () => {
  Sound.on = !Sound.on;
  syncSoundBtn();
  save();
  if (Sound.on) Sound.tick();
});

/** Stepper buttons: one step on tap, auto-repeat while held down. */
function holdButton(btn, stepFn) {
  let timer = null;
  let interval = null;
  const stop = () => {
    clearTimeout(timer);
    clearInterval(interval);
    timer = interval = null;
  };
  btn.addEventListener('pointerdown', (e) => {
    if (btn.disabled) return;
    e.preventDefault();
    stepFn();
    timer = setTimeout(() => { interval = setInterval(stepFn, 110); }, 420);
  });
  for (const ev of ['pointerup', 'pointerleave', 'pointercancel']) {
    btn.addEventListener(ev, stop);
  }
  btn.addEventListener('click', (e) => { if (e.detail === 0) stepFn(); }); // keyboard
}

holdButton($('minus'), () => setSides(state.sides - 1));
holdButton($('plus'), () => setSides(state.sides + 1));

document.addEventListener('keydown', (e) => {
  const tag = e.target && e.target.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
  if (e.repeat) return;
  if (e.code === 'Space' || e.key === 'Enter') {
    e.preventDefault();
    doRoll();
  } else if (e.key === 'n' || e.key === 'N') {
    newSeries();
  }
});

/* ---------------------------------------------------------------- init */

load();
syncSidesLabel();
syncSoundBtn();
buildChips();
updateChips();
renderFace('?');

if (state.used.size >= state.sides && state.used.size > 0) {
  setStatus('series complete — press New series', 'warn');
} else if (state.used.size > 0) {
  setStatus(`d${state.sides} — ${state.used.size}/${state.sides} drawn, press ROLL`);
} else {
  setStatus(`d${state.sides} — press ROLL to draw a question`);
}

if ('serviceWorker' in navigator &&
    (location.protocol === 'https:' ||
     location.hostname === 'localhost' || location.hostname === '127.0.0.1')) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('./service-worker.js').catch(() => {});
  });
}
