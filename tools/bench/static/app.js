"use strict";

// Physical header order (pin -> BCM or label); mirrors tools/bench/pins.py HEADER.
const HEADER = {1:"3V3",2:"5V",3:2,4:"5V",5:3,6:"GND",7:4,8:14,9:"GND",10:15,11:17,12:18,13:27,14:"GND",15:22,16:23,
  17:"3V3",18:24,19:10,20:"GND",21:9,22:25,23:11,24:8,25:"GND",26:7,27:0,28:1,29:5,30:"GND",31:6,32:12,33:13,34:"GND",
  35:19,36:16,37:26,38:20,39:"GND",40:21};
const LEDS = ["左目", "右目", "プロジェクター"];
const $ = (id) => document.getElementById(id);
const fmt = (v, d = 2) => (v === null || v === undefined ? "-" : Number(v).toFixed(d));
const vec = (v) => (v ? v.map((x) => fmt(x).padStart(6)).join(" ") : "-");

async function api(action, body, errId) {
  const err = errId ? $(errId) : null;
  if (err) err.textContent = "";
  try {
    const r = await fetch(`/api/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    const j = await r.json();
    if (!j.ok && err) err.textContent = j.error;
    return j;
  } catch (e) {
    if (err) err.textContent = `送れませんでした: ${e.message}`;
    return { ok: false };
  }
}

// ---- GPIO table (built once, updated in place) ----
const gpioCells = {};
function buildGpio() {
  const body = $("gpio-body");
  for (let pin = 1; pin <= 40; pin++) {
    const b = HEADER[pin];
    const tr = document.createElement("tr");
    if (typeof b !== "number") {
      tr.className = "power";
      tr.innerHTML = `<td>${pin}</td><td></td><td class="role">${b}</td><td></td><td></td><td></td><td></td>`;
    } else {
      tr.innerHTML = `<td>${pin}</td><td>${b}</td><td class="role"></td><td class="func"></td><td class="pull"></td><td class="lvl"></td><td class="ops"></td>`;
      gpioCells[b] = { tr, role: tr.querySelector(".role"), func: tr.querySelector(".func"), pull: tr.querySelector(".pull"),
        lvl: tr.querySelector(".lvl"), ops: tr.querySelector(".ops"), last: null };
    }
    body.appendChild(tr);
  }
}
function flash(td) { td.classList.add("flash"); setTimeout(() => td.classList.remove("flash"), 60); }
function updateGpio(pins) {
  for (const [bcm, p] of Object.entries(pins)) {
    const c = gpioCells[bcm];
    if (!c) continue;
    const key = `${p.func}|${p.pull}|${p.level}`;
    if (c.last === key) continue;
    if (c.last !== null) flash(c.lvl);
    c.last = key;
    c.role.textContent = p.role;
    c.tr.classList.toggle("reserved", p.role.startsWith("予約"));
    c.func.textContent = p.func;
    c.pull.textContent = p.pull;
    c.lvl.innerHTML = `<span class="level ${p.level ? "hi" : "lo"}">${p.level ? "hi" : "lo"}</span>`;
    if (p.can_pull && !c.ops.childElementCount) {
      for (const pull of ["pu", "pd", "pn"]) {
        const btn = document.createElement("button");
        btn.type = "button"; btn.textContent = pull;
        btn.setAttribute("aria-label", `GPIO${bcm} を ${pull} にする`);
        btn.onclick = () => api("set_pull", { bcm: Number(bcm), pull }, "err-gpio");
        c.ops.appendChild(btn);
      }
    }
  }
}
let lastEdgeCount = -1;
function updateEdges(edges) {
  const key = edges.length ? edges[edges.length - 1].join() : "";
  if (key === lastEdgeCount) return;
  lastEdgeCount = key;
  $("edge-log").innerHTML = edges.slice().reverse()
    .map(([t, name, a, b]) => `<li>${clock(t)} ${name} ${a ? "hi" : "lo"}→${b ? "hi" : "lo"}</li>`).join("");
}
function clock(t) {
  const d = new Date(t * 1000);
  return `${d.toLocaleTimeString("ja-JP", { hour12: false })}.${String(d.getMilliseconds()).padStart(3, "0")}`;
}

// ---- feet / imu / status ----
function updateFeet(feet, chatter) {
  for (const [name, level] of Object.entries(feet)) {
    const el = $(`foot-${name}`);
    if (!el) continue;
    el.classList.toggle("pressed", level === 0);
    el.querySelector(".state").textContent = level === 0 ? "押 (lo)" : "離 (hi)";
    el.querySelector(".chatter").textContent = `チャタリング ${chatter[name] || 0}`;
  }
}
function updateImu(imu) {
  const s = imu.sample;
  $("imu-sensor").textContent = s ? vec(s.sensor) : "読み取り失敗";
  $("imu-rf").textContent = s ? vec(s.runtime_false) : "-";
  $("imu-rt").textContent = s ? vec(s.runtime_true) : "-";
  $("imu-gyro").textContent = s ? vec(s.gyro) : "-";
  $("imu-norm").textContent = s ? fmt(s.norm) : "-";
  $("imu-err").textContent = imu.errors;
}
function updateStatus(st) {
  $("st-throttled").textContent = st.throttled;
  $("st-temp").textContent = `${fmt(st.cpu_temp, 1)}℃`;
  const m = Math.floor(st.uptime_s / 60);
  $("st-uptime").textContent = `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}m`;
}

// ---- LEDs ----
const ledState = {};
function buildLeds() {
  const rows = $("led-rows");
  for (const name of LEDS) {
    const row = document.createElement("div");
    row.className = "led-row";
    const id = `led-${LEDS.indexOf(name)}`;
    row.innerHTML = `<span>${name}</span><button type="button" id="${id}-btn">点灯</button>
      <input id="${id}-duty" type="range" min="0" max="100" value="100" aria-label="${name} の明るさ">
      <output id="${id}-rem" class="mono"></output>`;
    rows.appendChild(row);
    const btn = row.querySelector("button"), duty = row.querySelector("input");
    btn.onclick = () => api("led", { name, duty: ledState[name] ? 0 : Number(duty.value) }, "err-led");
    duty.onchange = () => { if (ledState[name]) api("led", { name, duty: Number(duty.value) }, "err-led"); };
  }
}
function updateLeds(remaining) {
  LEDS.forEach((name, i) => {
    const on = name in remaining;
    ledState[name] = on;
    const btn = $(`led-${i}-btn`);
    btn.classList.toggle("on", on);
    btn.textContent = on ? "消灯" : "点灯";
    $(`led-${i}-rem`).textContent = on ? `${Math.ceil(remaining[name])}s` : "";
  });
}

// ---- ears / speaker / camera ----
function setupEars() {
  for (const side of ["左", "右"]) {
    const input = $(`ear-${side}`), out = $(`ear-${side}-v`);
    input.oninput = () => { out.textContent = Number(input.value).toFixed(2); api("ear", { side, value: Number(input.value) }, "err-ear"); };
  }
  $("ear-center").onclick = () => {
    for (const side of ["左", "右"]) { $(`ear-${side}`).value = 0; $(`ear-${side}-v`).textContent = "0.00"; api("ear", { side, value: 0 }, "err-ear"); }
  };
}
let earLimitSet = false;
function applyEarLimit(limit) {
  if (earLimitSet) return;
  earLimitSet = true;
  for (const side of ["左", "右"]) { $(`ear-${side}`).min = -limit; $(`ear-${side}`).max = limit; }
}
function setupSpeaker() {
  $("tone-vol").oninput = () => { $("tone-vol-v").textContent = `${$("tone-vol").value}%`; };
  $("tone-play").onclick = async () => {
    $("tone-play").disabled = true;
    await api("tone", { freq: Number($("tone-freq").value), volume: Number($("tone-vol").value) / 100 }, "err-spk");
    $("tone-play").disabled = false;
  };
}
function setupCamera() {
  const img = $("cam-img");
  $("cam-capture").onclick = async () => {
    $("cam-capture").disabled = true;
    const j = await api("capture", {}, "err-cam");
    $("cam-capture").disabled = false;
    if (j.ok) { img.src = `/camera.jpg?t=${Date.now()}`; img.hidden = false; }
  };
  $("cam-rot").onchange = () => { img.style.transform = `rotate(${$("cam-rot").value}deg)`; };
}

// ---- servos ----
const servoRows = {};
function buildServoRow(r) {
  const tr = document.createElement("tr");
  tr.innerHTML = `<td class="num">${r.id}</td><td>${r.name}</td><td class="num pos"></td><td class="num volt"></td>
    <td class="num temp"></td><td class="stat"></td><td class="num maxv"></td>
    <td><div class="ops">
      <select aria-label="${r.name} の kp"><option>2</option><option selected>8</option><option>16</option></select>
      <button type="button" data-a="on">トルク ON</button>
      <button type="button" data-a="m" aria-label="${r.name} を -0.05 rad">−0.05</button>
      <button type="button" data-a="p" aria-label="${r.name} を +0.05 rad">+0.05</button>
      <button type="button" data-a="off">OFF</button></div></td>`;
  const kp = tr.querySelector("select");
  tr.querySelector('[data-a="on"]').onclick = () => api("servo_torque_on", { id: r.id, kp: Number(kp.value) }, "err-servo");
  tr.querySelector('[data-a="m"]').onclick = () => api("servo_jog", { id: r.id, direction: -1 }, "err-servo");
  tr.querySelector('[data-a="p"]').onclick = () => api("servo_jog", { id: r.id, direction: 1 }, "err-servo");
  tr.querySelector('[data-a="off"]').onclick = () => api("servo_torque_off", { id: r.id }, "err-servo");
  $("servo-body").appendChild(tr);
  servoRows[r.id] = tr;
  return tr;
}
function updateServos(rows, busErr, active) {
  $("servo-bus-err").textContent = busErr || "";
  for (const r of rows) {
    const tr = servoRows[r.id] || buildServoRow(r);
    tr.classList.toggle("active", r.id === active);
    tr.querySelector(".pos").textContent = fmt(r.position_rad, 3);
    tr.querySelector(".volt").textContent = r.voltage === null ? "-" : `${fmt(r.voltage, 1)}V`;
    tr.querySelector(".temp").textContent = r.temperature === null ? "-" : `${r.temperature}℃`;
    const stat = tr.querySelector(".stat");
    stat.textContent = r.error ? r.error : (r.status_text.length ? r.status_text.join("・") : "正常");
    stat.classList.toggle("status-bad", Boolean(r.error || r.status_text.length));
    tr.querySelector(".maxv").textContent = r.max_voltage === null ? "-" : `${fmt(r.max_voltage, 1)}V`;
  }
}

// ---- stream ----
function connect() {
  const es = new EventSource("/events");
  es.onopen = () => { $("conn").textContent = "接続中"; $("conn").className = "conn on"; };
  es.onerror = () => { $("conn").textContent = "切断"; $("conn").className = "conn off"; };
  es.onmessage = (ev) => {
    const s = JSON.parse(ev.data);
    $("read-err").textContent = s.fatal || [s.status && s.status.error && `状態 ${s.status.error}`, s.pins_error && `GPIO ${s.pins_error}`].filter(Boolean).join(" / ");
    if (s.fatal) return;
    updateStatus(s.status);
    updateGpio(s.pins);
    updateEdges(s.edges);
    updateFeet(s.feet, s.chatter);
    updateImu(s.imu);
    updateLeds(s.led_remaining);
    applyEarLimit(s.ear_limit);
    updateServos(s.servos, s.servo_error, s.active_servo);
  };
}

buildGpio();
buildLeds();
setupEars();
setupSpeaker();
setupCamera();
$("stop-all").onclick = () => api("stop_all", {}, "err-servo");
connect();
