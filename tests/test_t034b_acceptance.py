"""Tester acceptance tests for T-041 (T-034B): the 'Theo dõi cầu thủ' section of the upload page."""
import json, re, shutil, subprocess  # noqa: E401
from html.parser import HTMLParser
from pathlib import Path

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient
from sportscut.api import app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "sportscut" / "web"
INPUTS = {"player-file": ("file", "file", {"accept": "video/*"}), "player-job-id": ("job_id", "text", {}),
          "player-team-color": ("team_color", "color", {"value": "#ff0000"}), "player-team-name": ("team_name", "text", {}),
          "player-number": ("number", "number", {"min": "1", "max": "99", "step": "1"})}
FLAGGED = [("player-busy", "p", {"role": "status"}), ("player-empty", "p", {}), ("player-result", "div", {}),
           ("player-error", "p", {"role": "alert", "aria-live": "assertive"})]


class Events(HTMLParser):  # flat ordered list: ("start", tag, attrs) / ("end", tag) / ("text", data)
    def __init__(self, html): super().__init__(); self.ev = []; self.feed(html)  # noqa: E702
    def handle_starttag(self, tag, attrs): self.ev.append(("start", tag, dict(attrs)))
    def handle_endtag(self, tag): self.ev.append(("end", tag))
    def handle_data(self, data): self.ev.append(("text", data))


def test_ac1_ac2_markup_and_assets():
    response = TestClient(app).get("/")
    assert response.status_code == 200 and "text/html" in response.headers["content-type"]
    ev = Events(response.text).ev
    starts = [(i, e[1], e[2]) for i, e in enumerate(ev) if e[0] == "start"]
    by_id = {a["id"]: (i, t, a) for i, t, a in starts if "id" in a}
    assert len(by_id) == sum("id" in a for _, _, a in starts), "duplicate ids"
    end = lambda i, tag: next(j for j in range(i, len(ev)) if ev[j][:2] == ("end", tag))  # noqa: E731
    text = lambda i, tag: "".join(e[1] for e in ev[i:end(i, tag)] if e[0] == "text").strip()  # noqa: E731
    sec, form = by_id["player-section"][0], by_id["player-form"][0]
    assert by_id["player-section"][1] == "section" and by_id["highlights-form"][0] < sec
    assert sec < form < end(form, "form") < end(sec, "section") and by_id["player-form"][1] == "form"
    assert [text(i, "h2") for i, t, _ in starts if t == "h2" and sec < i < end(sec, "section")] == ["Theo dõi cầu thủ"]
    labels = {a.get("for"): text(i, "label") for i, t, a in starts if t == "label"}
    for key, (name, typ, extra) in INPUTS.items():
        i, tag, attrs = by_id[key]
        assert tag == "input" and form < i < end(form, "form"), key
        assert {k: attrs.get(k) for k in ("name", "type", *extra)} == {"name": name, "type": typ, **extra}, key
        assert labels.get(key) and re.search(r"[^\x00-\x7f]", labels[key]), key
    assert by_id["player-submit"][1:] == ("button", {"id": "player-submit", "type": "submit"})
    for key, tag, need in FLAGGED:
        assert by_id[key][1] == tag and "hidden" in by_id[key][2] and all(by_id[key][2].get(k) == v for k, v in need.items()), key
    for key in ("player-reel", "player-source"):
        assert by_id[key][1] == "video" and "controls" in by_id[key][2] and "src" not in by_id[key][2], key
    assert text(by_id["player-empty"][0], "p") == "Không tìm thấy pha chạm bóng nào." and by_id["player-touches"][1] == "ol"
    assets = ["/static/style.css", "/static/app.js"]  # AC2
    assert [v for _, _, a in starts for k, v in a.items() if k in ("href", "src")] == assets
    assert re.findall(r'(?:href|src)="([^"]+)"', response.text) == assets
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert not any(re.search(r"https?://", t, re.I) for t in (response.text, js, (WEB / "style.css").read_text(encoding="utf-8")))
    assert "content-type" not in js.lower() and "innerHTML" not in js


HARNESS = r"""
const vm = require("vm"), fs = require("fs"), els = {}, hidden0 = ["#player-result", "#player-empty", "#player-busy", "#player-error"]
const make = (tag) => ({ tag, hidden: false, value: "", files: [], src: "", textContent: "", children: [], attrs: {}, listeners: {},
  disabled: false, currentTime: 0, type: "", addEventListener(t, f) { this.listeners[t] = f }, setAttribute(k, v) { this.attrs[k] = v },
  removeAttribute(k) { delete this.attrs[k]; if (k === "src") this.src = "" }, append(...c) { this.children.push(...c) },
  replaceChildren(...c) { this.children = c } })
globalThis.document = { querySelector: (s) => els[s] ??= Object.assign(make(s), { hidden: hidden0.includes(s) }),
  querySelectorAll: () => [], createElement: (tag) => make(tag) }
const $ = (s) => document.querySelector(s), h = (s) => $(s).hidden; let calls = [], reply = null
globalThis.fetch = async (url, opts) => {
  calls.push({ url, method: opts.method, fields: [...opts.body.entries()].map(([k, v]) => [k, typeof v === "string" ? v : "<blob>"]),
    disabledDuring: $("#player-submit").disabled, busyHiddenDuring: h("#player-busy") })
  if (reply === "reject") throw new TypeError("network"); return { ok: reply.status < 300, status: reply.status, json: async () => reply.body }
}
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"))
async function run({ files = [], job = "abc", teamName = "", response }) {
  calls = []; reply = response; $("#player-file").files = files; $("#player-job-id").value = job; $("#player-team-name").value = teamName
  $("#player-team-color").value = "#ff0000"; $("#player-number").value = "10"; await $("#player-form").listeners.submit({ preventDefault() {} })
  const items = $("#player-touches").children, buttons = items.map((li) => li.children[0]); buttons[1]?.listeners.click()
  return { calls, sourceSrc: $("#player-source").src, reelSrc: $("#player-reel").src, reelHidden: h("#player-reel"),
    resultHidden: h("#player-result"), emptyHidden: h("#player-empty"), errorText: $("#player-error").textContent, errorHidden: h("#player-error"),
    disabled: $("#player-submit").disabled, busyHidden: h("#player-busy"), ariaBusy: "aria-busy" in $("#player-form").attrs,
    items: items.map((li) => [li.tag, li.children.length]), buttons: buttons.map((b) => [b.tag, b.type, b.textContent]),
    currentTime: $("#player-source").currentTime }
}
const ok = { status: 200, body: { job_id: "j 1", touches: [{ t: 1.5 }, { t: 4 }], reel_url: "/players/j%201/reel/player_ff0000_10.mp4" } }
const err = (detail) => ({ status: 422, body: { detail } })
;(async () => console.log(JSON.stringify({ success: await run({ job: " abc ", response: ok }), name: await run({ teamName: " blue ", response: ok }),
  empty: await run({ response: { status: 200, body: { job_id: "abc", touches: [], reel_url: null } } }), "422": await run({ response: err("bad team") }),
  "422list": await run({ response: err([{ msg: "x" }, { msg: "y" }]) }), both: await run({ files: [new Blob(["v"])], response: ok }),
  neither: await run({ job: "", response: ok }), reject: await run({ response: "reject" }) })))()
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
def test_ac4_ac5_player_flow_in_node(tmp_path):
    (tmp_path / "harness.js").write_text(HARNESS, encoding="utf-8")
    done = subprocess.run(["node", str(tmp_path / "harness.js"), str(WEB / "app.js")], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    r = json.loads(done.stdout.strip().splitlines()[-1])
    call, choose, offline = r["success"]["calls"], "Hãy chọn một tệp video hoặc nhập mã công việc.", "Không thể kết nối hoặc phản hồi từ máy chủ không hợp lệ."
    assert [(c["url"], c["method"], dict(c["fields"]), c["disabledDuring"], c["busyHiddenDuring"]) for c in call] == [
        ("/players", "POST", {"job_id": "abc", "team": "#ff0000", "number": "10"}, True, False)]
    assert dict(r["name"]["calls"][0]["fields"])["team"] == "blue" and len(r["reject"]["calls"]) == 1
    expect = {"success": dict(sourceSrc="/highlights/j%201/source", reelSrc="/players/j%201/reel/player_ff0000_10.mp4", currentTime=4,
                              resultHidden=False, emptyHidden=True, reelHidden=False, items=[["li", 1], ["li", 1]], ariaBusy=False,
                              buttons=[["button", "button", "1.5 s"], ["button", "button", "4.0 s"]], disabled=False, busyHidden=True),
              "empty": dict(reelHidden=True, emptyHidden=False, resultHidden=False, items=[]),
              "422": dict(errorText="Lỗi 422: bad team", errorHidden=False, resultHidden=True),
              "422list": dict(errorText="Lỗi 422: x; y", errorHidden=False, resultHidden=True),
              "both": dict(calls=[], errorText=choose, errorHidden=False), "neither": dict(calls=[], errorText=choose, errorHidden=False),
              "reject": dict(errorText=offline, errorHidden=False, disabled=False, busyHidden=True)}
    for key, want in expect.items():
        assert {k: r[key][k] for k in want} == want, key


def test_ac9_ac10_scope_and_size():
    git = lambda *args: subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)  # noqa: E731
    if shutil.which("git") is None or git("rev-parse", "--verify", "main").returncode:
        pytest.skip("git or the main branch is not available")
    base = git("merge-base", "main", "HEAD").stdout.strip()  # main...HEAD base; diffing the worktree also covers uncommitted edits
    # T-041's file allowlist and 380-line size cap applied only to T-041's own diff and were enforced at its merge (373a843); later branches keep only the project-wide frozen paths (Tech Lead, T-015 round 1).
    assert git("diff", "--exit-code", base, "--", "tests/conftest.py", "agent-office").returncode == 0
