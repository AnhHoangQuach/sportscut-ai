"use strict";
// Agent Office dashboard. Reads state + events over a WebSocket; every PO action is a POST
// that lands in the office inbox, so it is safe while the runner works.

const STAGES = [
  ["todo", "PM"], ["spec", "PM"], ["dev", "Developer"], ["test", "Tester"],
  ["review", "Tech Lead"], ["pr", "merge"], ["done", ""], ["blocked", "chờ PO (nghiệp vụ)"],
];
// Four separate agents (roles). Each runs on one subscription CLI (provider); roles on the same
// CLI share its quota. Colours follow the provider, names follow the role.
const STAGE_AGENT = { spec: "pm", review: "lead", dev: "dev", test: "tester" };
const ROLE_LABEL = { pm: "PM", lead: "Tech Lead", dev: "Developer", tester: "Tester", po: "PO" };
const ROLE_AV = { pm: "P", lead: "L", dev: "D", tester: "T" };
const DEFAULT_PROVIDER = { pm: "claude", lead: "claude", dev: "codex", tester: "codex" };
// Events written before the split name a CLI; show them at that CLI's first role.
const norm = (a) => (state && state.legacy_agents && state.legacy_agents[a]) || ({ claude: "pm", codex: "dev" })[a] || a;
const roleOf = (a) => (state && (state.roles || []).find((r) => r.name === norm(a))) || null;
const providerOf = (a) => { const r = roleOf(a); return r ? r.provider : (DEFAULT_PROVIDER[norm(a)] || ""); };
const roleName = (a) => ROLE_LABEL[norm(a)] || a;
const REQ_STATUS = { new: "mới", planned: "đang làm", done: "xong", blocked: "chờ PO" };

let state = null;
let events = [];
const working = {}; // agent -> {task, label}
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
let openTask = null;
let openTab = "overview";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hhmm = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); };

async function api(path, body, method = "POST") {
  const r = await fetch(path, {
    method, headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}

// ---------------------------------------------------------------- realtime
let ws = null, retry = 1000;
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  setConn("connecting");
  ws.onopen = () => { retry = 1000; setConn("ok"); };
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.type === "snapshot") {
      events = msg.events || [];
      events.forEach(trackWorking);
      setState(msg.state);
      renderFeed();
    } else if (msg.type === "event") {
      events.push(msg.event);
      if (events.length > 1000) events = events.slice(-800);
      trackWorking(msg.event);
      prependFeed(msg.event);
    } else if (msg.type === "state") {
      setState(msg.state);
    }
  };
  ws.onclose = () => {
    setConn("bad");
    setTimeout(connect, retry);
    retry = Math.min(retry * 2, 15000);
  };
}
function setConn(s) {
  const el = $("conn");
  el.className = "conn " + (s === "ok" ? "ok" : s === "bad" ? "bad" : "");
  el.querySelector("span").textContent = s === "ok" ? "realtime" : s === "bad" ? "mất kết nối" : "đang kết nối";
}
function trackWorking(e) {
  if (e.event === "agent_working") startWork(norm(e.agent), e.task_id, e.label);
  else if (["agent_done", "agent_failed"].includes(e.event)) endWork(norm(e.agent), e.task_id);
  else if (e.event === "agent_resting") (e.roles || [e.agent]).forEach((r) => clearWork(norm(r)));
}

function setState(s) {
  state = s;
  for (const a of s.agents || []) syncFromState(a);
  render();
  if (openTask) renderDrawer();
}

// ---------------------------------------------------------------- render
function render() {
  $("repo-name").textContent = state.repo ? `${state.repo.name} · ${state.repo.path}` : "";
  const cfg = state.config || {};
  $("merge-mode").textContent = cfg.merge_mode === "auto" ? `tự merge → ${cfg.base_branch}` : `PO merge → ${cfg.base_branch}`;
  const on = state.runner && state.runner.running;
  $("runner-state").textContent = on ? `Runner đang chạy (pid ${state.runner.pid})` : "Runner đang dừng";
  $("runner-state").className = "runner-state" + (on ? " on" : "");
  const btn = $("runner-btn");
  btn.textContent = on ? "Dừng" : "Bắt đầu";
  btn.className = "btn " + (on ? "danger" : "primary");
  btn.disabled = false;
  renderAgents();
  renderAttention();
  renderRequests();
  renderBoard();
  renderWaiting();
}

function renderAgents() {
  $("agents").innerHTML = (state.agents || []).map((a) => {
    const w = working[a.name];
    let status;
    if (a.status === "resting") {
      const why = a.rest_cause === "failure" ? "CLI lỗi" : a.rest_cause === "budget" ? "hết ngân sách" : "hết quota";
      status = `Nghỉ (${why} ${esc(a.provider)}) đến ${hhmm(a.rest_until)} · <span data-until="${esc(a.rest_until)}"></span>`;
    } else if (a.status === "working" || w) {
      status = `Đang làm ${esc(w ? `${w.label} · ${w.task}` : "")}`;
    } else {
      status = "Rảnh";
    }
    const cls = a.status === "resting" ? "resting" : (a.status === "working" || w) ? "working" : "idle";
    const wake = a.status === "resting" ? `<button class="btn small" data-wake="${esc(a.name)}">Làm lại ngay</button>` : "";
    const role = roleOf(a.name) || {};
    return `<div class="agent ${esc(a.provider)} ${cls}">
      <div class="avatar">${ROLE_AV[a.name] || "?"}</div>
      <div class="agent-info">
        <div class="agent-name">${esc(roleName(a.name))} <span class="hint">@${esc(a.provider)}</span></div>
        <div class="agent-role">${esc(role.title || "")}</div>
        <div class="agent-status"><span class="status-dot"></span>${status}</div>
        ${usage(a)}
        ${(a.rest_detail || a.last_error) && a.status === "resting" ? `<div class="hint">${esc(a.rest_detail || a.last_error).slice(0, 120)}</div>` : ""}
      </div>${wake}</div>`;
  }).join("");
  tickCountdowns();
}
function usage(a) {
  const cfg = state.config || {};
  const today = new Date().toLocaleDateString("sv-SE");
  const calls = a.calls_day === today ? a.calls_today || 0 : 0;
  // the daily budget is per CLI, shared by its roles
  const mates = (state.agents || []).filter((m) => m.provider === a.provider);
  const shared = mates.reduce((n, m) => n + (m.calls_day === today ? m.calls_today || 0 : 0), 0);
  const cap = (cfg.max_calls_per_day || {})[a.provider] || 0;
  const par = (cfg.parallel || {})[a.name] || 1;
  return `<div class="hint">Hôm nay ${calls} lượt (${esc(a.provider)}: ${shared}${cap ? `/${cap}` : ""}) · ${(a.active || []).length}/${par} phiên · đã nghỉ ${a.rests_total || 0} lần</div>`;
}
function tickCountdowns() {
  document.querySelectorAll("[data-until]").forEach((el) => {
    const ms = new Date(el.dataset.until) - Date.now();
    if (isNaN(ms)) { el.textContent = ""; return; }
    if (ms <= 0) { el.textContent = "sắp làm lại"; return; }
    const m = Math.floor(ms / 60000), h = Math.floor(m / 60);
    el.textContent = h ? `còn ${h} giờ ${m % 60} phút` : `còn ${m} phút ${Math.floor(ms / 1000) % 60}s`;
  });
}

function renderAttention() {
  const items = [];
  for (const r of state.requests || []) {
    if (r.status === "blocked") items.push({ id: r.id, title: r.text.split("\n")[0], why: r.note, questions: r.questions || [] });
  }
  for (const t of state.tasks || []) {
    if (t.stage === "blocked") items.push({ id: t.id, title: t.title, why: t.blocked_reason, questions: t.questions || [] });
  }
  $("attention").hidden = items.length === 0;
  // keep what the PO is typing when the state refreshes
  const drafts = {};
  document.querySelectorAll("#attention-list textarea").forEach((ta) => { drafts[ta.dataset.id] = ta.value; });
  $("attention-list").innerHTML = items.map((i) => `
    <div class="q-item">
      <div class="q-head">${esc(i.id)} · ${esc(i.title)}</div>
      ${i.questions.length ? `<ul>${i.questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ul>` : `<div class="hint">${esc(i.why)}</div>`}
      <textarea rows="2" data-id="${esc(i.id)}" placeholder="Câu trả lời / hướng dẫn cho team">${esc(drafts[i.id] || "")}</textarea>
      <div class="row"><span class="hint">Gửi xong task tự chạy tiếp.</span>
      <button class="btn primary small" data-answer="${esc(i.id)}">Trả lời</button></div>
    </div>`).join("");
}

function renderRequests() {
  $("requests").innerHTML = (state.requests || []).slice().reverse().map((r) => {
    const tasks = (state.tasks || []).filter((t) => t.request_id === r.id);
    const done = tasks.filter((t) => t.stage === "done").length;
    return `<div class="req">
      <span class="badge ${esc(r.status)}">${esc(REQ_STATUS[r.status] || r.status)}</span>
      <strong>${esc(r.id)}</strong>
      <span class="req-text">${esc(r.text.trim().split("\n")[0].replace(/^#+\s*/, ""))}</span>
      <span class="hint">${tasks.length ? `${done}/${tasks.length} task xong` : ""}${r.goal_rounds ? ` · kiểm tra mục tiêu ${r.goal_rounds} lần` : ""}</span>
      ${r.summary ? `<span class="req-summary">${esc(r.summary)}</span>` : ""}
    </div>`;
  }).join("");
}

function renderBoard() {
  const tasks = (state.tasks || []).slice().sort((a, b) => a.id.localeCompare(b.id));
  const active = activeTasks();
  $("board").innerHTML = STAGES.map(([stage, who]) => {
    const list = tasks.filter((t) => t.stage === stage);
    const cards = list.map((t) => {
      const agent = STAGE_AGENT[t.stage] ? providerOf(STAGE_AGENT[t.stage]) : "";
      const meta = [];
      if (active.has(t.id)) meta.push(`<span class="badge planned">đang chạy</span>`);
      if (t.review_round) meta.push(`<span class="badge">review ${t.review_round}/3</span>`);
      if (t.test_attempts) meta.push(`<span class="badge">test fail ${t.test_attempts}</span>`);
      if (t.checkpoint) meta.push(`<span class="badge blocked">checkpoint</span>`);
      if (t.tl_issue) meta.push(`<span class="badge planned">Tech Lead xử lý</span>`);
      if (t.dropped) meta.push(`<span class="badge">gác lại</span>`);
      if (t.retry_at) meta.push(`<span class="badge">chờ đến ${hhmm(t.retry_at)}</span>`);
      if (t.depends_on && t.depends_on.length && t.stage === "todo") meta.push(`<span class="badge">sau ${esc(t.depends_on.join(", "))}</span>`);
      return `<button class="tcard ${agent} ${active.has(t.id) ? "active" : ""}" data-task="${esc(t.id)}">
        <div class="tid">${esc(t.id)} · ${esc(t.request_id)}</div>
        <div class="ttitle">${esc(t.title)}</div>
        <div class="tmeta">${meta.join("")}</div></button>`;
    }).join("");
    return `<div class="col ${stage}">
      <div class="col-head"><div><div class="col-name">${stage}</div><div class="col-who">${who}</div></div>
      <span class="col-count">${list.length}</span></div>
      ${cards || `<div class="col-empty">–</div>`}</div>`;
  }).join("");
}

function renderWaiting() {
  const w = state.waiting_on || [];
  const empty = !(state.requests || []).length;
  $("waiting").hidden = !w.length && !empty;
  $("waiting-list").innerHTML = empty
    ? `<li>Chưa có yêu cầu nào. Gửi yêu cầu ở trên rồi bấm <b>Bắt đầu</b>.</li>`
    : w.map((x) => `<li>${esc(x)}</li>`).join("");
}

// ---------------------------------------------------------------- feed
function describe(e) {
  const who = (a) => `<span class="who ${esc(providerOf(a) || a)}">${esc(roleName(a))}</span>`;
  switch (e.event) {
    case "request_added": return `PO gửi <b>${esc(e.request_id)}</b>`;
    case "task_created": return `${who("pm")} tạo <b>${esc(e.task_id)}</b> ${esc(e.title)}`;
    case "stage_changed": {
      const cls = e.to === "blocked" ? "ev-warn" : e.to === "done" ? "ev-good" : "";
      return `<b>${esc(e.task_id)}</b> <span class="${cls}">${esc(e.frm)} → ${esc(e.to)}</span>${e.note ? ` · ${esc(e.note)}` : ""}`;
    }
    case "agent_working": return `${who(e.agent)} bắt đầu ${esc(e.label)} (${esc(e.task_id)})`;
    case "agent_done": return `${who(e.agent)} xong ${esc(e.label)} (${esc(e.task_id)})`;
    case "agent_failed": return `${who(e.agent)} <span class="ev-bad">lỗi</span> (${esc(e.task_id)}, exit ${esc(e.exit_code)})`;
    case "agent_resting": return `${(e.roles || [e.agent]).map(who).join(", ")} <span class="ev-warn">${e.cause === "failure" ? "CLI lỗi" : e.cause === "budget" ? "hết ngân sách" : "hết quota"}${e.provider ? ` ${esc(e.provider)}` : ""}</span>, nghỉ đến ${hhmm(e.until)}`;
    case "agent_failover": return `${who(e.agent)} <span class="ev-good">tiếp quản</span> ${esc(e.step_kind)} (${esc(e.task_id)}) thay ${who(e.preferred)} đang hết quota`;
    case "agent_awake": return `${(e.roles || [e.agent]).map(who).join(", ")} làm việc lại`;
    case "task_checkpoint": return `<b>${esc(e.task_id)}</b> lưu checkpoint (${esc(e.reason)})`;
    case "review_done": return `${who("lead")} review <b>${esc(e.task_id)}</b> vòng ${esc(e.round)}: <span class="${e.verdict === "approve" ? "ev-good" : "ev-warn"}">${esc(e.verdict)}</span>`;
    case "pr_opened": return `PR mở cho <b>${esc(e.task_id)}</b>`;
    case "pr_merged": return `<span class="ev-good">Đã merge</span> <b>${esc(e.task_id)}</b>`;
    case "request_blocked": return `<b>${esc(e.request_id)}</b> <span class="ev-warn">cần PO</span>: ${esc(e.note)}`;
    case "request_answered": return `PO trả lời <b>${esc(e.request_id)}</b>`;
    case "request_followup": return `${who("pm")} thêm ${esc((e.tasks || []).length)} task cho <b>${esc(e.request_id)}</b>`;
    case "request_done": return `<span class="ev-good">Hoàn thành</span> <b>${esc(e.request_id)}</b>`;
    case "runner_started": return `Runner bắt đầu`;
    case "runner_stopped": return `Runner dừng sau ${esc(e.steps)} bước`;
    case "worktree_ready": return `Worktree cho <b>${esc(e.task_id)}</b>: ${esc(e.branch)}`;
    case "message": return `${who(e.frm)} → ${e.to === "all" ? "mọi người" : who(e.to)}: ${esc(String(e.text || "").slice(0, 160))}`;
    case "merge_conflict": return `<b>${esc(e.task_id)}</b> <span class="ev-warn">xung đột merge</span>, ${who("dev")} sẽ gỡ (lần ${esc(e.round)})`;
    case "conflict_resolved": return `<span class="ev-good">Đã gỡ xung đột</span> <b>${esc(e.task_id)}</b>`;
    case "guardrail": return `<span class="ev-bad">Rào chắn</span> dừng <b>${esc(e.task_id || e.request_id)}</b> (${esc(e.rule)})`;
    case "budget_reached": return `${who(e.agent)} <span class="ev-warn">hết ngân sách hôm nay</span> (${esc(e.calls)}/${esc(e.cap)})`;
    case "techlead_needed": return `<b>${esc(e.task_id || e.request_id)}</b> vướng kỹ thuật (${esc(e.issue)}), ${who("lead")} xử lý`;
    case "tests_changed_by_dev": return `${who("dev")} sửa test của ${who("tester")} ở <b>${esc(e.task_id)}</b>: ${esc((e.files || []).join(", "))} (Tester sẽ kiểm tra lại)`;
    case "techlead_decision": return `Tech Lead quyết <b>${esc(e.task_id || e.request_id)}</b>: ${esc(e.action)}${e.decision ? ` · ${esc(e.decision)}` : ""}`;
    case "techlead_paused": return `<b>${esc(e.request_id)}</b> tạm dừng, thử lại lúc ${hhmm(e.until)}`;
    case "task_dropped": return `<b>${esc(e.task_id)}</b> <span class="ev-warn">gác lại</span>: ${esc(e.why)}`;
    case "step_crashed": return `<span class="ev-bad">Lỗi bước</span> ${esc(e.kind)} ${esc(e.target)}: ${esc(e.error)}`;
    default: return esc(e.event);
  }
}
const QUIET = new Set(["dispatch"]);
const feedItem = (e) => QUIET.has(e.event) ? "" : `<li><time>${hhmm(e.at)}</time>${describe(e)}</li>`;
function renderFeed() {
  $("feed").innerHTML = events.slice(-200).reverse().map(feedItem).join("") || `<li class="empty-note">Chưa có hoạt động.</li>`;
}
function prependFeed(e) {
  const f = $("feed");
  if (f.querySelector(".empty-note")) f.innerHTML = "";
  f.insertAdjacentHTML("afterbegin", feedItem(e));
  while (f.children.length > 300) f.lastChild.remove();
}

// ---------------------------------------------------------------- drawer
function findTask(id) { return (state.tasks || []).find((t) => t.id === id); }

async function renderDrawer() {
  const t = findTask(openTask);
  if (!t) return;
  $("d-id").textContent = `${t.id} · ${t.stage} · ${t.request_id}`;
  $("d-title").textContent = t.title;
  document.querySelectorAll("#d-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === openTab));
  const body = $("d-body");
  if (openTab === "overview") {
    const list = (xs) => xs && xs.length ? `<ul>${xs.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="empty-note">–</p>`;
    body.innerHTML = `
      <p>${esc(t.brief)}</p>
      ${t.stage === "blocked" ? `<div class="answer"><b>Đang chờ PO:</b> ${esc(t.blocked_reason)}
        <textarea rows="3" id="d-answer" placeholder="Trả lời / hướng dẫn"></textarea>
        <div class="row"><span></span><button class="btn primary small" data-answer="${esc(t.id)}" data-src="d-answer">Trả lời</button></div></div>` : ""}
      <dl class="kv">
        ${t.branch ? `<dt>Branch</dt><dd>${esc(t.branch)}</dd>` : ""}
        ${t.worktree ? `<dt>Worktree</dt><dd>${esc(t.worktree)}</dd>` : ""}
        ${t.pr_url ? `<dt>PR</dt><dd>${t.pr_url.startsWith("http") ? `<a href="${esc(t.pr_url)}" target="_blank" rel="noopener">${esc(t.pr_url)}</a>` : esc(t.pr_url)}</dd>` : ""}
        ${t.depends_on.length ? `<dt>Phụ thuộc</dt><dd>${esc(t.depends_on.join(", "))}</dd>` : ""}
        <dt>Review</dt><dd>${t.review_round}/3 vòng</dd>
      </dl>
      <h3>Acceptance criteria</h3>${list(t.acceptance_criteria)}
      <h3>Test plan</h3>${list(t.test_plan)}
      <h3>Spec</h3>${t.spec ? `<pre>${esc(t.spec)}</pre>` : `<p class="empty-note">Chưa có spec.</p>`}
      ${t.po_answer ? `<h3>PO đã trả lời</h3><pre>${esc(t.po_answer)}</pre>` : ""}
      ${t.review_comments.length ? `<h3>Comment review gần nhất</h3><ul>${t.review_comments.map((c) => `<li><b>[${esc(c.severity)}]</b> ${esc(c.file)}:${esc(c.line)} ${esc(c.text)}</li>`).join("")}</ul>` : ""}
      ${t.test_output ? `<h3>Lỗi test gần nhất</h3><pre>${esc(t.test_output)}</pre>` : ""}`;
  } else if (openTab === "history") {
    body.innerHTML = `<ul class="hist">${t.history.filter((h) => h.from).map((h) =>
      `<li><time>${esc(new Date(h.at).toLocaleString())}</time> · ${esc(h.from)} → <b>${esc(h.to)}</b> ${esc(h.note || "")}</li>`).join("")}</ul>`;
  } else if (openTab === "notes") {
    body.innerHTML = `<p class="empty-note">Đang tải…</p>`;
    const notes = await api(`/api/tasks/${encodeURIComponent(t.id)}/notes`, undefined, "GET").catch(() => ({}));
    const names = Object.keys(notes);
    body.innerHTML = names.length ? names.map((n) => `<h3>${esc(n)}</h3><pre class="md">${esc(notes[n])}</pre>`).join("")
      : `<p class="empty-note">Chưa có ghi chú (worktree chưa tạo hoặc đã dọn sau khi merge).</p>`;
  } else if (openTab === "logs") {
    const logs = await api(`/api/tasks/${encodeURIComponent(t.id)}/logs`, undefined, "GET").catch(() => []);
    body.innerHTML = logs.length ? `<div class="loglist">${logs.map((l) => `<button class="btn small" data-log="${esc(t.id)}/${esc(l)}">${esc(l)}</button>`).join("")}</div>`
      : `<p class="empty-note">Chưa có log.</p>`;
  }
}

async function showLog(title, url) {
  $("log-title").textContent = title;
  $("log-body").textContent = "Đang tải…";
  $("logdlg").showModal();
  $("log-body").textContent = await api(url, undefined, "GET").catch((e) => String(e));
  $("log-body").scrollTop = $("log-body").scrollHeight;
}

// ---------------------------------------------------------------- actions
document.addEventListener("click", async (ev) => {
  const el = ev.target.closest("button");
  if (!el) return;
  try {
    if (el.dataset.task) {
      openTask = el.dataset.task; openTab = "overview";
      $("drawer").showModal(); renderDrawer();
    } else if (el.dataset.tab) {
      openTab = el.dataset.tab; renderDrawer();
    } else if (el.dataset.answer) {
      const src = el.dataset.src ? $(el.dataset.src) : document.querySelector(`#attention-list textarea[data-id="${el.dataset.answer}"]`);
      const text = (src && src.value || "").trim();
      if (!text) { src && src.focus(); return; }
      el.disabled = true;
      await api(`/api/tasks/${encodeURIComponent(el.dataset.answer)}/answer`, { text });
      src.value = "";
      if (el.dataset.src) $("drawer").close();
    } else if (el.dataset.wake) {
      await api(`/api/agents/${el.dataset.wake}/wake`);
    } else if (el.dataset.log) {
      const [tid, name] = el.dataset.log.split("/");
      showLog(name, `/api/tasks/${encodeURIComponent(tid)}/logs/${encodeURIComponent(name)}`);
    } else if (el.id === "runner-btn") {
      el.disabled = true;
      await api(state.runner && state.runner.running ? "/api/runner/stop" : "/api/runner/start");
    } else if (el.id === "runner-log-btn") {
      showLog("Log runner", "/api/runner/log");
    } else if (el.id === "d-close") {
      $("drawer").close(); openTask = null;
    } else if (el.id === "log-close") {
      $("logdlg").close();
    }
  } catch (e) {
    alertBox(e.message);
    el.disabled = false;
  }
});
$("drawer").addEventListener("close", () => { openTask = null; });

$("request-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const ta = $("request-text");
  const text = ta.value.trim();
  if (!text) { ta.focus(); return; }
  try {
    const r = await api("/api/requests", { text });
    ta.value = "";
    $("request-hint").textContent = (r.results || []).join(" · ") +
      (state && state.runner && state.runner.running ? "" : " · bấm Bắt đầu để team làm việc");
  } catch (e) { alertBox(e.message); }
});

function alertBox(msg) {
  $("request-hint").textContent = "Lỗi: " + msg;
}

setInterval(tickCountdowns, 1000);
// Fallback when the socket is down: poll the state.
setInterval(async () => {
  if (ws && ws.readyState === WebSocket.OPEN) return;
  try { setState(await api("/api/state", undefined, "GET")); } catch (_) { /* offline */ }
}, 5000);
connect();
