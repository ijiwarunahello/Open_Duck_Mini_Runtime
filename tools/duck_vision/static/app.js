// Duck-vision booth page.
// Operator keys: Space = photo, R = rotate camera 90°, P = palette, M = sound on/off, F = fullscreen.
// URL params (optional): rot=0|90|180|270, enter=12, exit=6 (motion thresholds, 0-255).
"use strict";

const params = new URLSearchParams(location.search);

// ---------------------------------------------------------------- palettes
// 4 tones each, dark to light. "uv" is a playful false-colour: ducks do see ultraviolet.
const PALETTES = {
  duck: [[29, 36, 51], [63, 111, 115], [217, 196, 138], [246, 240, 216]],
  uv: [[26, 15, 46], [91, 42, 134], [200, 107, 250], [242, 230, 255]],
};
const PALETTE_NAMES = Object.keys(PALETTES);
const BAYER4 = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];

const state = {
  rot: Number(params.get("rot") ?? 90),
  palette: 0,
  enter: Number(params.get("enter") ?? 12),
  exit: Number(params.get("exit") ?? 6),
  motion: 0,
  walking: false,
  walkChangedAt: 0,
  lastFrameAt: 0,
  cameraOk: false,
  prevLuma: null,
  photoUntil: 0,
};

// ---------------------------------------------------------------- duck view
const view = document.getElementById("view");
const viewCtx = view.getContext("2d", { willReadFrequently: true });
const src = document.createElement("canvas");
const srcCtx = src.getContext("2d", { willReadFrequently: true });

function drawRotated(bitmap) {
  const quarter = ((state.rot % 360) + 360) % 360 / 90;
  const w = quarter % 2 ? bitmap.height : bitmap.width;
  const h = quarter % 2 ? bitmap.width : bitmap.height;
  if (src.width !== w || src.height !== h) { src.width = w; src.height = h; }
  srcCtx.save();
  srcCtx.translate(w / 2, h / 2);
  srcCtx.rotate(quarter * Math.PI / 2);
  srcCtx.drawImage(bitmap, -bitmap.width / 2, -bitmap.height / 2);
  srcCtx.restore();
  return srcCtx.getImageData(0, 0, w, h);
}

function ditherInto(img) {
  const pal = PALETTES[PALETTE_NAMES[state.palette]];
  const { width: w, height: h, data } = img;
  const luma = new Float32Array(w * h);
  let lo = 255, hi = 0;
  for (let i = 0; i < w * h; i++) {
    const y = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
    luma[i] = y;
    if (y < lo) lo = y;
    if (y > hi) hi = y;
  }
  const span = Math.max(hi - lo, 40); // auto-contrast, but do not amplify flat noise
  const out = new ImageData(w, h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      const t = (luma[i] - lo) / span; // 0..1
      const v = t * (pal.length - 1) + (BAYER4[(y & 3) * 4 + (x & 3)] / 16 - 0.5);
      const c = pal[Math.max(0, Math.min(pal.length - 1, Math.round(v)))];
      out.data[i * 4] = c[0]; out.data[i * 4 + 1] = c[1]; out.data[i * 4 + 2] = c[2]; out.data[i * 4 + 3] = 255;
    }
  }
  return { out, luma };
}

function updateMotion(luma, now) {
  const prev = state.prevLuma;
  state.prevLuma = luma;
  if (!prev || prev.length !== luma.length) return;
  let sum = 0;
  for (let i = 0; i < luma.length; i++) sum += Math.abs(luma[i] - prev[i]);
  state.motion = 0.7 * state.motion + 0.3 * (sum / luma.length);
  const held = now - state.walkChangedAt > 1500;
  if (!state.walking && state.motion > state.enter && held) setWalking(true, now);
  else if (state.walking && state.motion < state.exit && held) setWalking(false, now);
}

function setWalking(on, now) {
  state.walking = on;
  state.walkChangedAt = now;
  if (on) { pet.play("jumping", "running"); say("walkStart"); }
  else { pet.play("idle"); say("walkStop"); }
}

async function frameLoop() {
  for (;;) {
    const started = performance.now();
    try {
      const r = await fetch("/frame.jpg", { cache: "no-store" });
      if (r.status === 200) {
        const bitmap = await createImageBitmap(await r.blob());
        const img = drawRotated(bitmap);
        bitmap.close();
        const { out, luma } = ditherInto(img);
        if (view.width !== out.width || view.height !== out.height) {
          view.width = out.width; view.height = out.height;
        }
        viewCtx.putImageData(out, 0, 0);
        const now = performance.now();
        updateMotion(luma, now);
        state.lastFrameAt = now;
        if (!state.cameraOk) { state.cameraOk = true; if (now > 3000) say("cameraBack"); pet.play("idle"); }
      }
    } catch (e) { /* server restarting; try again */ }
    const now = performance.now();
    if (state.cameraOk && now - state.lastFrameAt > 3000) {
      state.cameraOk = false; state.walking = false; state.prevLuma = null;
      pet.play("failed", "waiting"); say("cameraLost");
    }
    await sleep(Math.max(0, 100 - (performance.now() - started)));
  }
}

// ---------------------------------------------------------------- photo
const photo = document.getElementById("photo");
const photoCanvas = document.getElementById("photoCanvas");
const flash = document.getElementById("flash");

function takePhoto() {
  if (!state.cameraOk) return;
  photoCanvas.width = view.width; photoCanvas.height = view.height;
  photoCanvas.getContext("2d").drawImage(view, 0, 0);
  flash.classList.remove("on"); void flash.offsetWidth; flash.classList.add("on");
  shutter();
  photo.hidden = false;
  state.photoUntil = performance.now() + 7000;
  pet.play("waving", state.walking ? "running" : "idle");
  say("photo", true);
  setTimeout(() => { if (performance.now() >= state.photoUntil) photo.hidden = true; }, 7100);
}

// ---------------------------------------------------------------- pet
// Codex pet atlas: 8 columns x 9 rows of 192x208 cells; row order from the hatch-pet contract.
const PET_ROWS = ["idle", "running-right", "running-left", "waving", "jumping", "failed", "waiting", "running", "review"];
const CELL_W = 192, CELL_H = 208, COLS = 8;
const ONCE = new Set(["waving", "jumping", "failed"]);

const pet = {
  canvas: document.getElementById("pet"),
  sheet: null,
  frames: {},     // row name -> number of used cells
  current: "waiting",
  after: null,
  frame: 0,
  play(name, after) {
    if (this.current === name && !ONCE.has(name)) return;
    this.current = name; this.after = after ?? null; this.frame = 0;
  },
  async load() {
    try {
      const meta = await (await fetch("/pet.json")).json();
      const img = new Image();
      img.src = "/pet-sheet";
      await img.decode();
      this.sheet = img;
      this.countFrames(img);
      if (meta.displayName) document.title = `${meta.displayName} から みた せかい`;
    } catch (e) { this.sheet = null; } // no pet yet: draw the placeholder
  },
  countFrames(img) {
    const c = document.createElement("canvas");
    c.width = img.width; c.height = img.height;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    PET_ROWS.forEach((name, row) => {
      let n = 0;
      for (let col = 0; col < COLS; col++) {
        const d = ctx.getImageData(col * CELL_W, row * CELL_H, CELL_W, CELL_H).data;
        let used = false;
        for (let i = 3; i < d.length; i += 16) if (d[i] > 0) { used = true; break; }
        if (used) n = col + 1; else break;
      }
      this.frames[name] = n;
    });
  },
  tick() {
    const ctx = this.canvas.getContext("2d");
    ctx.clearRect(0, 0, CELL_W, CELL_H);
    if (!this.sheet) { drawPlaceholder(ctx, this.current, this.frame++); return; }
    const row = PET_ROWS.indexOf(this.current);
    const n = this.frames[this.current] || 1;
    if (this.frame >= n) {
      if (ONCE.has(this.current)) { this.current = this.after ?? "idle"; this.after = null; }
      this.frame = 0;
    }
    const r = PET_ROWS.indexOf(this.current);
    ctx.drawImage(this.sheet, this.frame * CELL_W, (r < 0 ? row : r) * CELL_H, CELL_W, CELL_H, 0, 0, CELL_W, CELL_H);
    this.frame++;
  },
};

function drawPlaceholder(ctx, mode, f) {
  // A blocky stand-in until the hatched pet is installed.
  if (ONCE.has(mode) && f > 8) { pet.current = pet.after ?? "idle"; pet.after = null; }
  const bob = mode.startsWith("running") ? (f % 2) * 6 : Math.round(Math.sin(f / 3) * 2);
  const px = (x, y, w, h, c) => { ctx.fillStyle = c; ctx.fillRect(x, y + bob, w, h); };
  px(56, 60, 80, 64, "#e9e4d4");      // head
  px(64, 76, 64, 28, "#1d2433");      // visor
  const blink = mode === "failed" ? 2 : (f % 24 === 0 ? 2 : 10);
  px(76, 86 - blink / 2 + 5, 10, blink, "#9fe3ff");
  px(106, 86 - blink / 2 + 5, 10, blink, "#9fe3ff");
  px(72, 40, 6, 20, "#e9e4d4"); px(114, 40, 6, 20, "#e9e4d4"); // antennas
  px(70, 128, 52, 36, "#cfc8b4");     // body
  const step = mode.startsWith("running") ? (f % 2 ? 8 : -8) : 0;
  px(76, 164, 12, 26 + step, "#8a93a6"); px(104, 164, 12, 26 - step, "#8a93a6");
}

// ---------------------------------------------------------------- speech
const LINES = {
  walkStart: ["あるくよ", "とことこ", "まえに すすむよ", "いってきまーす"],
  walkStop: ["ふう、とまった", "ここ どこかな", "ちょっと きゅうけい"],
  photo: ["はい、ちーず", "とれた!", "いい しゃしん!"],
  cameraLost: ["あれ? め が みえない…"],
  cameraBack: ["みえた!"],
  idle: [
    "みんな おおきく みえるよ",
    "ぼく の め には こう みえてるんだ",
    "アヒル は しがいせん も みえるんだって",
    "コントローラ で うごかしてみてね",
    "ぼく、 まいにち あるく れんしゅう してるんだ",
    "ぴかぴか して きれい",
  ],
};
const bubble = document.getElementById("bubble");
const speech = { busyUntil: 0, nextIdleAt: 8000, typing: null, last: {} };

function pick(kind) {
  const list = LINES[kind];
  let line;
  do { line = list[Math.floor(Math.random() * list.length)]; } while (list.length > 1 && line === speech.last[kind]);
  speech.last[kind] = line;
  return line;
}

function say(kind, force = false) {
  const now = performance.now();
  if (!force && now < speech.busyUntil) return;
  const text = pick(kind);
  clearInterval(speech.typing);
  bubble.textContent = "";
  let i = 0;
  speech.busyUntil = now + 1200 + text.length * 90 + 2500;
  speech.nextIdleAt = speech.busyUntil + 15000 + Math.random() * 15000;
  speech.typing = setInterval(() => {
    const ch = text[i++];
    bubble.textContent += ch;
    if (ch && ch.trim() && !"、。…!?".includes(ch)) blip(ch);
    if (i >= text.length) {
      clearInterval(speech.typing);
      setTimeout(() => { if (bubble.textContent === text) bubble.textContent = ""; }, 4500);
    }
  }, 90);
}

function idleChatter() {
  const now = performance.now();
  if (state.cameraOk && now > speech.nextIdleAt && now > speech.busyUntil) {
    if (!state.walking) pet.play("review");
    say("idle");
    setTimeout(() => { if (pet.current === "review") pet.play(state.walking ? "running" : "idle"); }, 4000);
  }
}

// ---------------------------------------------------------------- sound (machine voice, never a human voice)
let audio = null;
let muted = false;
const soundButton = document.getElementById("sound");

function unlockAudio() {
  if (!audio) audio = new (window.AudioContext || window.webkitAudioContext)();
  audio.resume();
  soundButton.hidden = true;
}

function tone(freq, start, dur, type = "square", gain = 0.05) {
  if (!audio || muted) return;
  const o = audio.createOscillator(), g = audio.createGain();
  o.type = type; o.frequency.setValueAtTime(freq, start);
  g.gain.setValueAtTime(gain, start);
  g.gain.exponentialRampToValueAtTime(0.0001, start + dur);
  o.connect(g).connect(audio.destination);
  o.start(start); o.stop(start + dur + 0.02);
}

function blip(ch) {
  if (!audio) return;
  const base = 520 + (ch.codePointAt(0) % 12) * 40; // same character, same pitch: reads like a voice
  const t = audio.currentTime;
  tone(base, t, 0.06);
  tone(base * 1.5, t + 0.03, 0.04, "triangle", 0.03);
}

function shutter() {
  if (!audio) return;
  const t = audio.currentTime;
  tone(1400, t, 0.04, "square", 0.06);
  tone(900, t + 0.06, 0.08, "square", 0.05);
}

// ---------------------------------------------------------------- input
soundButton.addEventListener("click", unlockAudio);
document.addEventListener("pointerdown", unlockAudio, { once: true });
document.addEventListener("keydown", (e) => {
  unlockAudio();
  if (e.code === "Space") { e.preventDefault(); takePhoto(); }
  else if (e.key === "r" || e.key === "R") { state.rot = (state.rot + 90) % 360; state.prevLuma = null; }
  else if (e.key === "p" || e.key === "P") state.palette = (state.palette + 1) % PALETTE_NAMES.length;
  else if (e.key === "m" || e.key === "M") muted = !muted;
  else if (e.key === "f" || e.key === "F") {
    if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen();
  }
});

// ---------------------------------------------------------------- start
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

pet.load().then(() => {
  setInterval(() => pet.tick(), 125);
  setInterval(idleChatter, 1000);
  frameLoop();
});
