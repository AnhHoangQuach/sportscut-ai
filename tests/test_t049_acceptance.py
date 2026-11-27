"""Tester acceptance tests for T-049: match info in POST /highlights and stored metadata in GET/PUT /meta."""
import json, shutil, subprocess  # noqa: E401
from html.parser import HTMLParser
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sportscut import api, media, pipeline
from sportscut.commentary import publish
from sportscut.commentary.eval_meta import format_problems
from sportscut.commentary.meta import ClipMeta
HOME, AWAY, COMP = "Công An Hà Nội", "Nam Định", "V.League 1"
MATCH = {"home": HOME, "away": AWAY, "competition": COMP, "kickoff": 0.0}
FORM = {"meta": "true", "home": f"  {HOME} ", "away": AWAY, "competition": COMP, "kickoff": "0"}
ENTRIES = [{"start": 125.0, "end": 140.0, "score": 0.9, "reason": "audio_peak", "file": "clip_01.mp4", "event": "goal", "event_confidence": 0.8},
           {"start": 300.0, "end": 312.0, "score": 0.5, "reason": "audio_peak", "file": "clip_02.mp4", "event": "other", "event_confidence": 0.3}]
OLD_KEYS, NEED = ["start", "end", "score", "reason", "event", "event_confidence", "clip_url"], "home, away, competition, kickoff and meta_backend need meta"
@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path)); monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # noqa: E702
    monkeypatch.setattr(media, "probe_duration", lambda _p: 600.0)
    calls, state = [], {"entries": ENTRIES}
    def run(video, out_dir, **kw):  # fake pipeline: writes highlights.json like export does and returns a copy
        calls.append(kw); Path(out_dir).mkdir(parents=True, exist_ok=True)  # noqa: E702
        (Path(out_dir) / "highlights.json").write_text(json.dumps(state["entries"], indent=2) + "\n", encoding="utf-8")
        return json.loads(json.dumps(state["entries"]))
    monkeypatch.setattr(pipeline, "run", run)
    return tmp_path, TestClient(api.app), calls, state
post = lambda client, **form: client.post("/highlights", files={"file": ("match.mp4", b"fake", "video/mp4")}, data=form)  # noqa: E731
jobs = lambda root: set((root / "jobs").iterdir()) if (root / "jobs").exists() else set()  # noqa: E731
ok_meta = lambda m: format_problems(ClipMeta(m["title"], m["caption"], tuple(m["hashtags"]))) == []  # noqa: E731
texts = lambda items: [{k: m[k] for k in publish.META_KEYS} for m in items]  # noqa: E731
@pytest.mark.parametrize("form, detail", [
    *[(f, NEED) for f in ({"home": HOME}, {"away": AWAY, "meta": "false"}, {"competition": COMP}, {"kickoff": "0"}, {"meta_backend": "template"}, {"meta_backend": "llm"})],
    *[({"meta": "true", k: c * 41}, f"{k} must be a stripped string of 1 to 40 characters") for k, c in (("home", "A"), ("away", "B"))],
    ({"meta": "true", "kickoff": "-5"}, "kickoff must be non-negative"), ({"meta": "maybe"}, list), ({"meta": "true", "meta_backend": "gpt"}, list),
    *[({"meta": "true", "kickoff": k}, list) for k in ("nan", "inf", "abc")]])
def test_ac1_rejected_without_pipeline_or_job_dir(env, form, detail):
    root, client, calls, _ = env
    before, r = jobs(root), post(client, **form)
    assert r.status_code == 422 and calls == [] and jobs(root) == before
    assert isinstance(r.json()["detail"], list) if detail is list else r.json() == {"detail": detail}
def test_ac1_ac6_blank_fields_and_no_meta_unchanged(env):
    root, client, calls, _ = env
    for form in ({}, {"home": "   ", "away": "", "competition": "\t"}):
        r = post(client, **form)
        assert r.status_code == 200 and list(r.json()) == ["job_id", "source_name", "source_url", "duration", "highlights"]
        assert all(list(h) == OLD_KEYS for h in r.json()["highlights"])
        assert not any((root / "jobs" / r.json()["job_id"] / "clips" / n).exists() for n in ("reel.json", "captions.txt"))
        meta = client.get(f"/highlights/{r.json()['job_id']}/meta").json()
        assert meta["reel"] == api.REEL_DEFAULT.to_dict() and meta["clips"][1] == {"file": "clip_02.mp4", **api._default_clip_meta(ENTRIES[1])}
    assert calls == [{"top": 10, "min_len": 10, "max_len": 30, "events": None}] * 2
def test_ac2_ac3_ac4_generate_store_and_serve(env, tmp_path_factory):
    root, client, _, state = env
    assert (r := post(client, **FORM)).status_code == 200, r.text
    body, d = r.json(), root / "jobs" / r.json()["job_id"]
    assert list(body) == ["job_id", "source_name", "source_url", "duration", "highlights", "reel"]
    assert [list(h) for h in body["highlights"]] == [OLD_KEYS + ["title", "caption", "hashtags"]] * 2
    for h in body["highlights"]:
        assert f"{HOME} vs {AWAY}" in h["title"] and f"trong trận {HOME} gặp {AWAY}" in h["caption"] and "phút" in h["caption"]
        assert {"#CongAnHaNoi", "#NamDinh", "#VLeague1"} <= set(h["hashtags"]) and ok_meta(h)
    assert "phút 3" in body["highlights"][0]["title"] + body["highlights"][0]["caption"]
    assert body["reel"]["title"] == f"Tổng hợp highlight: {HOME} vs {AWAY}" and COMP in body["reel"]["caption"] and ok_meta(body["reel"])
    ref = tmp_path_factory.mktemp("ref")  # AC3: byte identity against write_meta on a copy
    (ref / "highlights.json").write_text(json.dumps(ENTRIES, indent=2) + "\n", encoding="utf-8")
    publish.write_meta(ref, MATCH, "template")
    for name in ("highlights.json", "captions.txt", "reel.json"):
        assert (d / "clips" / name).read_bytes() == (ref / name).read_bytes(), name
    stored = json.loads((d / "clips" / "highlights.json").read_text(encoding="utf-8"))
    assert texts(body["highlights"]) == texts(stored)
    assert body["reel"] == json.loads((d / "clips" / "reel.json").read_text(encoding="utf-8"))
    assert json.loads((d / "job.json").read_text(encoding="utf-8")) == {"source_name": "match.mp4", "source_url": None, "duration": 600.0, "version": 0, "segments": ENTRIES}
    jid = body["job_id"]  # AC4
    assert client.get(f"/highlights/{jid}").json() == body
    assert (goal := client.get(f"/highlights/{jid}", params={"event": "goal"}).json())["highlights"] == body["highlights"][:1] and goal["reel"] == body["reel"]
    assert (meta := client.get(f"/highlights/{jid}/meta").json()) == {"job_id": jid, "reel": body["reel"], "clips": [{"file": s["file"], **{k: s[k] for k in publish.META_KEYS}} for s in stored]}
    assert meta["reel"] != api.REEL_DEFAULT.to_dict() and meta["clips"][0] != {"file": "clip_01.mp4", **api._default_clip_meta(ENTRIES[0])}
def test_ac5_put_overrides_stored_and_validation_unchanged(env):
    root, client, _, state = env
    jid = post(client, **FORM).json()["job_id"]
    d, stored = root / "jobs" / jid, client.get(f"/highlights/{jid}/meta").json()
    edit = {"reel": {"title": "Đại chiến Công An Hà Nội", "caption": "Xem ngay!", "hashtags": ["#BongDa", "#CAHN", "#NamDinh"]},
            "clips": [{"file": f"clip_0{i}.mp4", "title": f"Pha bóng số {i} hay nhất", "caption": "Tuyệt vời.", "hashtags": ["#BongDa", "#A", f"#B{i}"]} for i in (1, 2)]}
    for bad in ({**edit, "clips": edit["clips"][::-1]}, {**edit, "clips": edit["clips"][:1]}, {**edit, "reel": {**edit["reel"], "title": "Ngắn"}}, {"reel": 1}):
        assert client.put(f"/highlights/{jid}/meta", json=bad).status_code == 422 and not (d / "meta.json").exists()
    assert client.get(f"/highlights/{jid}/meta").json() == stored
    assert ((r := client.put(f"/highlights/{jid}/meta", json=edit)).status_code, r.json()) == (200, {"job_id": jid, **edit})
    assert client.get(f"/highlights/{jid}/meta").json() == {"job_id": jid, **edit}
    assert (job := client.get(f"/highlights/{jid}").json())["reel"] == edit["reel"] and texts(job["highlights"]) == texts(edit["clips"])
def test_ac6_ac7_zero_clips_llm_backend_and_write_failure(env, monkeypatch):
    root, client, _, state = env
    seen, real = [], publish.write_meta  # spy: records (match, backend), then runs the template backend (no network)
    monkeypatch.setattr(api.publish, "write_meta", lambda out, match=None, backend="template", client=None: seen.append((match, backend)) or real(out, match, "template"))
    r = post(client, meta="true", home=HOME, away=AWAY, meta_backend="llm")
    assert r.status_code == 200 and "reel" in r.json() and seen == [({"home": HOME, "away": AWAY}, "llm")]
    assert post(client, meta="true").status_code == 200 and seen[-1] == (None, "template")
    state["entries"] = []; r = post(client, meta="true", home=HOME)  # noqa: E702
    assert r.status_code == 200 and "reel" not in r.json() and r.json()["highlights"] == [] and len(seen) == 2
    assert not (root / "jobs" / r.json()["job_id"] / "clips" / "reel.json").exists()
    state["entries"], before = ENTRIES, jobs(root)
    monkeypatch.setattr(api.publish, "write_meta", lambda *a, **k: 1 / 0)
    r = TestClient(api.app, raise_server_exceptions=False).post("/highlights", files={"file": ("m.mp4", b"x")}, data={"meta": "true"})
    assert r.status_code == 500 and jobs(root) == before
def test_ac8_real_burst_video(burst_video, tmp_path, monkeypatch):
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path)); client = TestClient(api.app)  # noqa: E702
    with burst_video.open("rb") as fh:
        r = client.post("/highlights", files={"file": ("burst.mp4", fh, "video/mp4")}, data={"meta": "true", "home": "Hà Nội", "away": "Viettel"})
    assert r.status_code == 200, r.text
    assert len(hl := r.json()["highlights"]) == 3 and all("Hà Nội vs Viettel" in h["title"] and ok_meta(h) for h in hl) and ok_meta(r.json()["reel"])
    assert texts((meta := client.get(f"/highlights/{r.json()['job_id']}/meta").json())["clips"]) == texts(hl) and meta["reel"] == r.json()["reel"]
class Events(HTMLParser):
    def __init__(self, html): super().__init__(); self.ev, self.text = [], {}; self.feed(html)  # noqa: E702
    def handle_starttag(self, tag, attrs): self.ev.append((tag, dict(attrs)))
    def handle_data(self, data): self.ev and self.text.setdefault(len(self.ev) - 1, []).append(data)
def test_ac9_upload_form_markup_and_app_js(tmp_path):
    client = TestClient(api.app)
    ev = Events(client.get("/").text)
    pos = {a["id"]: i for i, (_, a) in enumerate(ev.ev) if "id" in a}
    form, submit, fs = pos["highlights-form"], pos["submit"], pos["match-info"]
    assert ev.ev[fs][0] == "fieldset" and ev.ev[fs + 1][0] == "legend" and "trận đấu" in "".join(ev.text[fs + 1])
    assert ev.ev[submit] == ("button", {"id": "submit", "type": "submit"}) and form < fs < submit
    labels = {a.get("for"): "".join(ev.text.get(i, [])).strip() for i, (t, a) in enumerate(ev.ev) if t == "label"}
    for key in ("home", "away", "competition"):
        assert ev.ev[pos[key]] == ("input", {"id": key, "name": key, "type": "text", "maxlength": "40"}) and fs < pos[key] < submit
        assert labels[key] and any(ord(ch) > 127 for ch in labels[key]), key
    assert (js := client.get("/static/app.js")).status_code == 200; a, b, c = (js.text.index(m) for m in ('if (events) formData.append("events", events)', 'formData.append("meta", "true")', 'fetch("/highlights"'))
    assert a < b < c and all(f'"{n}"' in js.text[a:c] for n in ("home", "away", "competition"))
    if shutil.which("node") is None:
        return
    (harness := tmp_path / "h.js").write_text(HARNESS, encoding="utf-8")
    assert (out := subprocess.run(["node", str(harness), str(Path(api.__file__).parent / "web" / "app.js")], capture_output=True, text=True, timeout=60)).returncode == 0, out.stderr
    assert json.loads(out.stdout) == [[["url", "https://youtu.be/x"], ["meta", "true"], ["home", "A"]], [["url", "https://youtu.be/x"]]]
HARNESS = r"""
const vm = require("vm"), fs = require("fs"), els = {}, sent = []
const make = () => ({ value: "", files: [], hidden: false, listeners: {}, addEventListener(t, f) { this.listeners[t] = f },
  setAttribute() {}, removeAttribute() {}, append() {}, replaceChildren() {} })
globalThis.document = { querySelector: (s) => els[s] ??= make(), querySelectorAll: () => [], createElement: make }
globalThis.window = { location: { assign() {} } }
globalThis.fetch = async (url, opts) => { sent.push([...opts.body.entries()]); return { ok: true, status: 200, json: async () => ({ job_id: "j" }) } }
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"))
;(async () => { const q = (s) => document.querySelector(s); q("#url").value = "https://youtu.be/x"
  for (const [home, away] of [[" A ", "  "], ["", ""]]) {
    q("#home").value = home; q("#away").value = away; q("#competition").value = ""; await q("#highlights-form").listeners.submit({ preventDefault() {} }) }
  console.log(JSON.stringify(sent)) })()
"""
