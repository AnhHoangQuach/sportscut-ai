// Agent Office: a 3D office where you can watch the PM, Tech Lead, Developer and Tester (four separate
// agents on two subscription CLIs) hand work to each other.
// Same data as the Kanban dashboard: /ws streams state + events, PO actions POST to the inbox.
import * as THREE from "three";
import { OrbitControls } from "/static/vendor/OrbitControls.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hhmm = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); };
const NAMES = { pm: "PM", lead: "Tech Lead", dev: "Developer", tester: "Tester", po: "Bạn (PO)", all: "mọi người", main: "main" };
const COLORS = { pm: 0xc8693d, lead: 0x9a4626, dev: 0x1f8a70, tester: 0x4f9a3a, po: 0x3b6fd6 };
const AV = { pm: "P", lead: "L", dev: "D", tester: "T", po: "PO" };
const DEFAULT_PROVIDER = { pm: "claude", lead: "claude", dev: "codex", tester: "codex" };
// Events written before the split name a CLI ("claude"/"codex"): show them at its first role.
const norm = (a) => (state && state.legacy_agents && state.legacy_agents[a]) || ({ claude: "pm", codex: "dev" })[a] || a;
const providerOf = (a) => { const r = (state?.roles || []).find((x) => x.name === norm(a)); return r ? r.provider : (DEFAULT_PROVIDER[norm(a)] || "po"); };
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const dark = matchMedia("(prefers-color-scheme: dark)").matches;

let state = null;
const working = {};          // agent -> {task, label}
const sessions = {};         // agent -> {task_id: label}; Codex may run several tasks at once
function syncWorking(a) {
  const ent = Object.entries(sessions[a] || {});
  if (!ent.length) { delete working[a]; return; }
  working[a] = { task: ent.map((e) => e[0]).join(", "), label: ent.length > 1 ? `${ent.length} việc` : ent[0][1], n: ent.length };
}
function startWork(a, task, label) { (sessions[a] ||= {})[task] = label; syncWorking(a); }
function endWork(a, task) { if (sessions[a]) delete sessions[a][task]; syncWorking(a); }
function clearWork(a) { sessions[a] = {}; syncWorking(a); }
function syncFromState(a) {
  if (a.status !== "working") { clearWork(a.name); return; }
  if (!Array.isArray(a.active)) return;
  const cur = sessions[a.name] || {};
  sessions[a.name] = Object.fromEntries(a.active.map((t) => [t, cur[t] || "đang làm"]));
  syncWorking(a.name);
}
function activeTasks() { return new Set(Object.values(sessions).flatMap((m) => Object.keys(m))); }
const messages = [];
const seenMessages = new Set();

// ------------------------------------------------------------------ scene
const canvas = $("scene");
const stage = $("stage");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
const scene = new THREE.Scene();
scene.background = new THREE.Color(dark ? 0x15181d : 0xe9ecf0);
const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
camera.position.set(0, 10.5, 15.5);
const controls = new OrbitControls(camera, canvas);
controls.target.set(0, 1.2, -0.8);
controls.enableDamping = true;
controls.maxPolarAngle = Math.PI * 0.47;
controls.minDistance = 7;
controls.maxDistance = 28;

scene.add(new THREE.HemisphereLight(0xffffff, dark ? 0x222833 : 0xb9c2cf, dark ? 0.9 : 1.1));
const sun = new THREE.DirectionalLight(0xffffff, dark ? 0.9 : 1.4);
sun.position.set(6, 12, 8);
sun.castShadow = true;
sun.shadow.mapSize.set(1024, 1024);
Object.assign(sun.shadow.camera, { left: -12, right: 12, top: 12, bottom: -12 });
scene.add(sun);

const mat = (color, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.8, ...extra });
function box(w, h, d, color, x, y, z, parent = scene) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat(color));
  m.position.set(x, y, z);
  m.castShadow = m.receiveShadow = true;
  parent.add(m);
  return m;
}

// room
const floor = new THREE.Mesh(new THREE.PlaneGeometry(22, 16), mat(dark ? 0x2a2f37 : 0xd9d4cb));
floor.rotation.x = -Math.PI / 2;
floor.receiveShadow = true;
scene.add(floor);
box(22, 6, 0.2, dark ? 0x232830 : 0xf4f1ec, 0, 3, -6.1);
box(0.2, 6, 16, dark ? 0x20252c : 0xefebe5, -11, 3, 0);
const rug = new THREE.Mesh(new THREE.CircleGeometry(2.2, 48), mat(dark ? 0x313847 : 0xc9d3e3));
rug.rotation.x = -Math.PI / 2; rug.position.set(0, 0.01, 0.6); scene.add(rug);

// a plant for warmth
const pot = box(0.6, 0.6, 0.6, 0x8a6a4f, -9.6, 0.3, -5.2);
const leaves = new THREE.Mesh(new THREE.SphereGeometry(0.75, 16, 12), mat(0x4f8a4a));
leaves.position.set(-9.6, 1.25, -5.2); leaves.castShadow = true; scene.add(leaves);
void pot;

// ------------------------------------------------------------------ desks + people
function screenTexture() {
  const c = document.createElement("canvas");
  c.width = 256; c.height = 160;
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return { c, tex };
}

function makeStation(key, x, z, label) {
  const g = new THREE.Group();
  g.position.set(x, 0, z);
  scene.add(g);
  const deskColor = dark ? 0x5a4a3c : 0xb08d6a;
  box(2.6, 0.12, 1.3, deskColor, 0, 1.0, 0.4, g);           // top
  for (const [dx, dz] of [[-1.2, -0.15], [1.2, -0.15], [-1.2, 0.95], [1.2, 0.95]]) box(0.08, 1.0, 0.08, 0x6b5a4a, dx, 0.5, dz, g);
  // monitor angled toward the person and the camera
  const scr = screenTexture();
  const mon = new THREE.Group();
  mon.position.set(0.75, 1.06, 0.55);
  mon.rotation.y = -0.6;
  g.add(mon);
  box(0.1, 0.35, 0.1, 0x30343a, 0, 0.17, 0, mon);
  box(1.0, 0.65, 0.06, 0x1d2025, 0, 0.62, 0, mon);
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.92, 0.57),
    new THREE.MeshStandardMaterial({ map: scr.tex, emissive: 0xffffff, emissiveMap: scr.tex, emissiveIntensity: 0.6 }));
  screen.position.set(0, 0.62, 0.035);
  mon.add(screen);
  box(0.6, 0.03, 0.22, 0x2f3338, -0.2, 1.08, 0.75, g);       // keyboard
  // chair
  box(0.8, 0.1, 0.8, 0x3d4350, 0, 0.55, -0.55, g);
  box(0.8, 0.8, 0.1, 0x3d4350, 0, 0.95, -0.95, g);
  // person (sits behind the desk, faces the camera)
  const person = new THREE.Group();
  person.position.set(0, 0, -0.45);
  g.add(person);
  const color = COLORS[key];
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.33, 0.55, 6, 16), mat(color));
  body.position.y = 1.15; body.castShadow = true; person.add(body);
  const head = new THREE.Group();
  head.position.y = 1.85; person.add(head);
  const skull = new THREE.Mesh(new THREE.SphereGeometry(0.27, 24, 16), mat(0xf1d3b8));
  skull.castShadow = true; head.add(skull);
  const eyeMat = mat(0x22252a);
  for (const ex of [-0.09, 0.09]) {
    const eye = new THREE.Mesh(new THREE.SphereGeometry(0.035, 8, 8), eyeMat);
    eye.position.set(ex, 0.03, 0.245); head.add(eye);
  }
  const hair = new THREE.Mesh(new THREE.SphereGeometry(0.285, 24, 16, 0, Math.PI * 2, 0, Math.PI / 2.2), mat(key === "po" ? 0x3a2c22 : 0x2b2b2b));
  hair.position.y = 0.02; head.add(hair);
  const arms = [];
  for (const side of [-1, 1]) {
    const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.08, 0.45, 4, 8), mat(color));
    arm.position.set(side * 0.38, 1.25, 0.25); arm.rotation.x = -1.1; arm.castShadow = true;
    person.add(arm); arms.push(arm);
  }
  // status lamp on the desk
  const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.09, 12, 12), new THREE.MeshStandardMaterial({ color: 0x888888, emissive: 0x000000 }));
  lamp.position.set(-1.1, 1.15, 0.9); g.add(lamp);
  return { key, label, group: g, person, head, body, arms, screen, scr, lamp, status: "idle", screenKey: "" };
}

// One desk per role: Claude's PM + Tech Lead on the left, Codex's Developer + Tester on the right.
const stations = {
  pm: makeStation("pm", -6.9, -1.4, "PM"),
  lead: makeStation("lead", -2.3, -1.4, "Tech Lead"),
  dev: makeStation("dev", 2.3, -1.4, "Developer"),
  tester: makeStation("tester", 6.9, -1.4, "Tester"),
  po: makeStation("po", 0, 3.6, "Bạn (PO)"),
};
stations.po.group.rotation.y = 0; // PO faces the team too

// "main" branch: a small server tower where merged work lands
const server = new THREE.Group();
server.position.set(10, 0, -5.2);
scene.add(server);
box(1.1, 2.4, 0.9, 0x2a2e35, 0, 1.2, 0, server);
const leds = [];
for (let i = 0; i < 5; i++) {
  const led = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.06, 0.02), new THREE.MeshStandardMaterial({ color: 0x1b5e3a, emissive: 0x0a2a18 }));
  led.position.set(0, 0.5 + i * 0.4, 0.46); server.add(led); leds.push(led);
}
let mergeFlash = 0;

// kanban on the back wall
const kanCanvas = document.createElement("canvas");
kanCanvas.width = 1600; kanCanvas.height = 680;
const kanTex = new THREE.CanvasTexture(kanCanvas);
kanTex.colorSpace = THREE.SRGBColorSpace;
kanTex.anisotropy = 4;
const kanban = new THREE.Mesh(new THREE.PlaneGeometry(10.4, 4.42), new THREE.MeshStandardMaterial({ map: kanTex, roughness: 0.9 }));
kanban.position.set(-0.8, 3.45, -5.98);
scene.add(kanban);
box(10.6, 0.12, 0.12, 0x8c8c8c, -0.8, 1.2, -5.94);

// ------------------------------------------------------------------ 2D drawing helpers
function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}
function clip(ctx, text, max) {
  if (ctx.measureText(text).width <= max) return text;
  while (text.length > 1 && ctx.measureText(text + "…").width > max) text = text.slice(0, -1);
  return text + "…";
}
const STAGES = ["todo", "spec", "dev", "test", "review", "pr", "done", "blocked"];
const STAGE_COLOR = { spec: "#c8693d", review: "#c8693d", dev: "#1f8a70", test: "#1f8a70", done: "#2c8a4b", blocked: "#b7791f", todo: "#7a8391", pr: "#3b6fd6" };

function drawKanban() {
  const ctx = kanCanvas.getContext("2d");
  const W = kanCanvas.width, H = kanCanvas.height;
  ctx.fillStyle = "#fbfaf7"; ctx.fillRect(0, 0, W, H);
  ctx.strokeStyle = "#c9c4ba"; ctx.lineWidth = 6; ctx.strokeRect(3, 3, W - 6, H - 6);
  ctx.fillStyle = "#2a2e35"; ctx.font = "600 34px system-ui, sans-serif";
  const req = (state?.requests || []).slice(-1)[0];
  ctx.fillText(req ? clip(ctx, `${req.id} · ${req.text.trim().split("\n")[0].replace(/^#+\s*/, "")}`, W - 60) : "Chưa có yêu cầu", 28, 52);
  const colW = (W - 40) / STAGES.length;
  const tasks = (state?.tasks || []).slice().sort((a, b) => a.id.localeCompare(b.id));
  const active = activeTasks();
  STAGES.forEach((s, i) => {
    const x = 20 + i * colW;
    ctx.fillStyle = s === "blocked" ? "#f8ecd5" : "#eef0f3";
    roundRect(ctx, x + 4, 72, colW - 8, H - 92, 14); ctx.fill();
    ctx.fillStyle = "#5d6673"; ctx.font = "600 24px system-ui, sans-serif";
    ctx.fillText(s.toUpperCase(), x + 16, 106);
    let y = 122;
    for (const t of tasks.filter((t) => t.stage === s)) {
      if (y > H - 80) { ctx.fillStyle = "#5d6673"; ctx.fillText("…", x + 16, y + 20); break; }
      ctx.fillStyle = "#ffffff"; roundRect(ctx, x + 12, y, colW - 24, 92, 10); ctx.fill();
      ctx.fillStyle = STAGE_COLOR[s]; ctx.fillRect(x + 12, y, 8, 92);
      if (active.has(t.id)) { ctx.strokeStyle = STAGE_COLOR[s]; ctx.lineWidth = 4; roundRect(ctx, x + 12, y, colW - 24, 92, 10); ctx.stroke(); }
      ctx.fillStyle = "#5d6673"; ctx.font = "600 20px ui-monospace, Menlo, monospace"; ctx.fillText(t.id, x + 30, y + 28);
      ctx.fillStyle = "#1b1f24"; ctx.font = "22px system-ui, sans-serif";
      const words = t.title.split(" "); let line = "", ly = y + 56, lines = 0;
      for (const w of words) {
        const test = line ? line + " " + w : w;
        if (ctx.measureText(test).width > colW - 50 && line) {
          ctx.fillText(line, x + 30, ly); ly += 26; line = w; lines++;
          if (lines === 1) { line = clip(ctx, words.slice(words.indexOf(w)).join(" "), colW - 50); break; }
        } else line = test;
      }
      ctx.fillText(line, x + 30, ly);
      y += 104;
    }
  });
  kanTex.needsUpdate = true;
}

function drawScreen(st) {
  const a = (state?.agents || []).find((x) => x.name === st.key);
  const w = working[st.key];
  let key, lines, bg;
  if (st.key === "po") {
    const asks = pendingQuestions().length;
    key = `po:${asks}`; bg = asks ? "#4a3510" : "#18202e";
    lines = asks ? ["Team hỏi", `${asks} câu`] : ["Product", "Owner"];
  } else if (a && a.status === "resting") {
    key = `rest:${a.rest_until}`; bg = "#2b2410";
    lines = [a.rest_cause === "failure" ? `${a.provider} lỗi` : `Hết quota ${a.provider}`, `nghỉ đến ${hhmm(a.rest_until)}`];
  } else if (w) {
    key = `work:${w.label}:${w.task}`; bg = providerOf(st.key) === "claude" ? "#3b2216" : "#10302a"; lines = [w.label, w.task];
  } else {
    key = "idle"; bg = "#1b1f25"; lines = ["rảnh", ""];
  }
  if (key === st.screenKey) return;
  st.screenKey = key;
  const ctx = st.scr.c.getContext("2d");
  ctx.fillStyle = bg; ctx.fillRect(0, 0, 256, 160);
  ctx.fillStyle = "#e8eaee"; ctx.font = "600 30px system-ui, sans-serif"; ctx.textAlign = "center";
  ctx.fillText(lines[0], 128, 70);
  ctx.font = "24px ui-monospace, Menlo, monospace"; ctx.fillStyle = "#b9c0ca";
  ctx.fillText(lines[1] || "", 128, 112);
  if (key.startsWith("work")) { ctx.fillStyle = "#e8eaee"; for (let i = 0; i < 5; i++) ctx.fillRect(40 + i * 38, 132, 26, 4); }
  st.scr.tex.needsUpdate = true;
}

// ------------------------------------------------------------------ overlays (labels, bubbles, flyers)
const overlay = $("overlay");
const tmp = new THREE.Vector3();
function toScreen(v) {
  tmp.copy(v).project(camera);
  const r = canvas.getBoundingClientRect();
  return { x: (tmp.x * 0.5 + 0.5) * r.width, y: (-tmp.y * 0.5 + 0.5) * r.height, visible: tmp.z < 1 };
}
function el(cls, html) { const d = document.createElement("div"); d.className = cls; d.innerHTML = html; overlay.appendChild(d); return d; }

for (const st of Object.values(stations)) {
  st.tag = el(`tag ${st.key === "po" ? "po" : DEFAULT_PROVIDER[st.key]}`, "");
  st.anchor = new THREE.Vector3();
  st.zzz = el("zzz", "Z z z"); st.zzz.style.display = "none";
}
const serverTag = el("tag mainbr", "main");

const bubbles = []; // {el, who, until}
function say(who, html, ms = 7000) {
  who = norm(who);
  const st = stations[who];
  if (!st) return;
  for (const b of bubbles.filter((b) => b.who === who)) b.el.remove();
  bubbles.splice(0, bubbles.length, ...bubbles.filter((b) => b.who !== who));
  const b = el(`bubble ${who === "po" ? "po" : providerOf(who)}`, html);
  bubbles.push({ el: b, who, until: performance.now() + ms });
}

const flyers = []; // paper flying between desks
const paperGeo = new THREE.PlaneGeometry(0.5, 0.66);
function anchorOf(who) {
  if (who === "main") return new THREE.Vector3(10, 2.6, -5.2);
  const st = stations[who];
  return st.group.localToWorld(new THREE.Vector3(0, 1.5, 0.4));
}
function fly(from, to, label, color) {
  from = norm(from); to = norm(to);
  if (!stations[from] && from !== "main") return;
  if (!stations[to] && to !== "main") return;
  const paper = new THREE.Mesh(paperGeo, new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: color, emissiveIntensity: 0.25, side: THREE.DoubleSide }));
  paper.castShadow = true;
  scene.add(paper);
  const tag = el("flyer", esc(label));
  tag.style.borderColor = "#" + color.toString(16).padStart(6, "0");
  flyers.push({ paper, tag, a: anchorOf(from), b: anchorOf(to), t0: performance.now(), dur: reduceMotion ? 300 : 1700, to });
}

// ------------------------------------------------------------------ data → scene
function pendingQuestions() {
  const out = [];
  for (const r of state?.requests || []) if (r.status === "blocked") out.push({ id: r.id, title: r.text.split("\n")[0].replace(/^#+\s*/, ""), qs: r.questions || [], why: r.note });
  for (const t of state?.tasks || []) if (t.stage === "blocked") out.push({ id: t.id, title: t.title, qs: t.questions || [], why: t.blocked_reason });
  return out;
}

function applyState(s) {
  state = s;
  for (const a of s.agents || []) {
    syncFromState(a);
    const st = stations[a.name];
    if (!st) continue;
    st.status = a.status === "resting" ? "resting" : working[a.name] ? "working" : "idle";
    st.label = `${NAMES[a.name] || a.name} · ${a.provider}`;
    st.tag.className = `tag ${a.provider}`;
  }
  stations.po.status = pendingQuestions().length ? "asking" : "idle";
  $("repo").textContent = s.repo ? s.repo.path : "";
  const on = s.runner && s.runner.running;
  $("runner-state").textContent = on ? "Runner đang chạy" : "Runner đang dừng";
  $("runner-state").className = "runner" + (on ? " on" : "");
  $("runner-btn").textContent = on ? "Dừng" : "Bắt đầu";
  $("runner-btn").className = "btn " + (on ? "danger" : "primary");
  $("runner-btn").disabled = false;
  drawKanban();
  Object.values(stations).forEach(drawScreen);
  renderAsk();
}

function onEvent(e, live) {
  const ag = norm(e.agent);
  if (e.event === "agent_working") { startWork(ag, e.task_id, e.label); if (stations[ag]) stations[ag].status = "working"; }
  if (["agent_done", "agent_failed"].includes(e.event)) { endWork(ag, e.task_id); if (stations[ag]) stations[ag].status = working[ag] ? "working" : "idle"; }
  if (e.event === "agent_resting") {
    for (const r of (e.roles || [e.agent]).map(norm)) { clearWork(r); if (stations[r]) stations[r].status = "resting"; }
  }
  if (e.event === "message") {
    const id = `${e.at}|${e.frm}|${e.text}`;
    if (seenMessages.has(id)) return;
    seenMessages.add(id);
    messages.push(e);
    appendMsg(e);
    if (!live) return;
    say(e.frm, `<b>${esc(NAMES[norm(e.frm)] || e.frm)} → ${esc(NAMES[norm(e.to)] || e.to)}</b>${esc(e.text.length > 160 ? e.text.slice(0, 160) + "…" : e.text)}`);
    const label = e.task_id || (e.text.match(/R-\d+/) || [""])[0] || "✉";
    const color = COLORS[norm(e.frm)] || 0x888888;
    if (e.topic === "merged") { fly("lead", "main", label, 0x2c8a4b); mergeFlash = 1; }
    else if (e.frm !== e.to && e.to !== "all") fly(e.frm, e.to, label, color);
  }
  if (live && e.event === "pr_merged") mergeFlash = 1;
}

// ------------------------------------------------------------------ chat + ask panels
function appendMsg(e) {
  const list = $("msgs");
  list.querySelector(".empty")?.remove();
  const who = norm(e.frm) in NAMES ? norm(e.frm) : "pm";
  const li = document.createElement("li");
  li.className = `msg k-${e.topic || ""}`;
  li.innerHTML = `<div class="av ${who === "po" ? "po" : providerOf(who)}">${AV[who] || "?"}</div>
    <div><div class="msg-head"><b>${esc(NAMES[who] || e.frm)}</b> → ${esc(NAMES[norm(e.to)] || e.to)} · ${hhmm(e.at)}${e.task_id ? ` · ${esc(e.task_id)}` : ""}</div>
    <div class="msg-body">${esc(e.text)}</div></div>`;
  const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 60;
  list.appendChild(li);
  while (list.children.length > 400) list.firstChild.remove();
  if (atBottom) list.scrollTop = list.scrollHeight;
  $("chat-count").textContent = `${messages.length} tin`;
}

function renderAsk() {
  const items = pendingQuestions();
  $("ask").hidden = !items.length;
  const drafts = {};
  document.querySelectorAll("#ask-list textarea").forEach((t) => { drafts[t.dataset.id] = t.value; });
  $("ask-list").innerHTML = items.map((i) => `<div class="q"><b>${esc(i.id)}</b> ${esc(i.title)}
    ${i.qs.length ? `<ul>${i.qs.map((q) => `<li>${esc(q)}</li>`).join("")}</ul>` : `<div class="muted">${esc(i.why)}</div>`}
    <textarea rows="2" data-id="${esc(i.id)}" placeholder="Trả lời cho team">${esc(drafts[i.id] || "")}</textarea>
    <div class="row"><button class="btn primary small" data-answer="${esc(i.id)}">Trả lời</button></div></div>`).join("");
}

async function api(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("button");
  if (!b) return;
  try {
    if (b.dataset.answer) {
      const ta = document.querySelector(`#ask-list textarea[data-id="${b.dataset.answer}"]`);
      if (!ta.value.trim()) { ta.focus(); return; }
      b.disabled = true;
      await api(`/api/tasks/${encodeURIComponent(b.dataset.answer)}/answer`, { text: ta.value.trim() });
      ta.value = "";
    } else if (b.id === "runner-btn") {
      b.disabled = true;
      await api(state?.runner?.running ? "/api/runner/stop" : "/api/runner/start");
    }
  } catch (e) { say("po", esc("Lỗi: " + e.message)); b.disabled = false; }
});
$("compose").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const ta = $("compose-text");
  if (!ta.value.trim()) return;
  try { await api("/api/requests", { text: ta.value.trim() }); ta.value = ""; }
  catch (e) { say("po", esc("Lỗi: " + e.message)); }
});

// ------------------------------------------------------------------ realtime
let ws, retry = 1000;
function connect() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  const conn = $("conn");
  ws.onopen = () => { retry = 1000; conn.className = "conn ok"; conn.lastChild.textContent = "realtime"; };
  ws.onclose = () => { conn.className = "conn bad"; conn.lastChild.textContent = "mất kết nối"; setTimeout(connect, retry); retry = Math.min(retry * 2, 15000); };
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.type === "snapshot") {
      for (const e of msg.events || []) onEvent(e, false);
      applyState(msg.state);
      if (!messages.length) $("msgs").innerHTML = `<li class="empty">Chưa có hội thoại. Gửi yêu cầu bên dưới rồi bấm Bắt đầu.</li>`;
      const last = messages.slice(-1)[0];
      if (last) say(last.frm, `<b>${esc(NAMES[norm(last.frm)] || last.frm)} → ${esc(NAMES[norm(last.to)] || last.to)}</b>${esc(last.text.slice(0, 160))}`, 5000);
      $("msgs").scrollTop = $("msgs").scrollHeight;
    } else if (msg.type === "event") {
      onEvent(msg.event, true);
    } else if (msg.type === "state") {
      applyState(msg.state);
    }
  };
}

// ------------------------------------------------------------------ loop
function resize() {
  const r = stage.getBoundingClientRect();
  renderer.setSize(r.width, r.height, false);
  camera.aspect = r.width / Math.max(1, r.height);
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(stage);
resize();

const clock = new THREE.Clock();
function place(node, v) {
  const p = toScreen(v);
  node.style.left = p.x + "px"; node.style.top = p.y + "px";
  node.style.visibility = p.visible ? "visible" : "hidden";
}
function frame() {
  const t = clock.getElapsedTime();
  const amp = reduceMotion ? 0.2 : 1;
  for (const st of Object.values(stations)) {
    const s = st.status;
    st.body.position.y = 1.15 + (s === "working" ? Math.abs(Math.sin(t * 9)) * 0.03 * amp : Math.sin(t * 1.5) * 0.008);
    st.head.rotation.x = s === "resting" ? 0.55 : s === "working" ? Math.sin(t * 4) * 0.05 * amp + 0.15 : 0;
    st.head.rotation.z = s === "asking" ? Math.sin(t * 2) * 0.12 * amp : 0;
    st.arms.forEach((arm, i) => { arm.rotation.x = s === "working" ? -1.1 + Math.sin(t * 16 + i * 2) * 0.12 * amp : s === "resting" ? -0.3 : -1.0; });
    st.screen.material.emissiveIntensity = s === "resting" ? 0.15 : s === "working" ? 0.7 + Math.sin(t * 6) * 0.1 * amp : 0.45;
    const lampColor = s === "working" ? 0x2bd47a : s === "resting" ? 0xf0b030 : s === "asking" ? 0x6c9cff : 0x444444;
    st.lamp.material.emissive.setHex(lampColor);
    st.group.localToWorld(st.anchor.set(0, 2.45, -0.45));
    const w = working[st.key];
    const a = (state?.agents || []).find((x) => x.name === st.key);
    st.tag.innerHTML = `${esc(st.label)}<small>${s === "working" && w ? `${esc(w.label)} ${esc(w.task)}` : s === "resting" && a ? `nghỉ đến ${hhmm(a.rest_until)}` : s === "asking" ? "cần trả lời" : "rảnh"}</small>`;
    place(st.tag, st.anchor);
    st.zzz.style.display = s === "resting" ? "block" : "none";
    if (s === "resting") { place(st.zzz, tmp.copy(st.anchor).add(new THREE.Vector3(0.5, 0.35 + Math.sin(t * 2) * 0.1, 0))); }
  }
  place(serverTag, new THREE.Vector3(10, 2.75, -5.2));
  mergeFlash = Math.max(0, mergeFlash - 0.012);
  leds.forEach((led, i) => led.material.emissive.setHex(mergeFlash > 0 ? (Math.floor(t * 12 + i) % 2 ? 0x37e27f : 0x0a2a18) : (Math.floor(t * 1.5 + i) % 3 ? 0x0f4527 : 0x1f8a4c)));

  const now = performance.now();
  for (let i = bubbles.length - 1; i >= 0; i--) {
    const b = bubbles[i];
    if (now > b.until) { b.el.remove(); bubbles.splice(i, 1); continue; }
    b.el.style.opacity = now > b.until - 600 ? "0" : "1";
    place(b.el, tmp.copy(stations[b.who].anchor).add(new THREE.Vector3(0, 0.55, 0)));
  }
  for (let i = flyers.length - 1; i >= 0; i--) {
    const f = flyers[i];
    const k = Math.min(1, (now - f.t0) / f.dur);
    const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    const p = new THREE.Vector3().lerpVectors(f.a, f.b, e);
    p.y += Math.sin(Math.PI * e) * 2.6;
    f.paper.position.copy(p);
    f.paper.rotation.set(-0.4 + e * 0.8, e * Math.PI * 2, Math.sin(e * Math.PI) * 0.4);
    place(f.tag, p.clone().add(new THREE.Vector3(0, 0.55, 0)));
    if (k >= 1) { scene.remove(f.paper); f.paper.material.dispose(); f.tag.remove(); flyers.splice(i, 1); }
  }
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}
drawKanban();
Object.values(stations).forEach(drawScreen);
connect();
frame();
