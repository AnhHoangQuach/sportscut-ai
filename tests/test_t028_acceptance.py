import copy, json, re, shutil, subprocess, uuid
from html.parser import HTMLParser
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from sportscut import api
WEB = Path(api.__file__).parent / "web"
REEL = {"title": "Tổng hợp highlight trận đấu", "caption": "Tổng hợp những khoảnh khắc đáng chú ý trong trận đấu. Cùng xem lại nhé!", "hashtags": ["#BongDa", "#Highlight", "#TongHop"]}
GOAL = {"title": "Bàn thắng trong trận đấu", "caption": "Bàn thắng trong trận đấu. Cùng xem lại khoảnh khắc này!", "hashtags": ["#BongDa", "#BanThang", "#Highlight"]}
OTHER = {"title": "Khoảnh khắc đáng chú ý trong trận đấu", "caption": "Khoảnh khắc đáng chú ý trong trận đấu. Cùng xem lại khoảnh khắc này!", "hashtags": ["#BongDa", "#KhoanhKhac", "#Highlight"]}
EDIT = {"reel": {"title": "Tổng hợp U23 Việt Nam", "caption": "Những pha bóng hay nhất.", "hashtags": ["#BongDa", "#U23", "#VietNam"]}, "clips": [
    {"file": "clip_01.mp4", "title": "Siêu phẩm phút cuối", "caption": "Không thể tin nổi!", "hashtags": ["#BongDa", "#BanThang", "#Highlight"]},
    {"file": "clip_02.mp4", "title": "Khoảnh khắc đáng nhớ", "caption": "Xem lại nào.", "hashtags": ["#BongDa", "#KhoanhKhac", "#Highlight", "#VietNam"]}]}

def _job(root, files=("clip_01.mp4", "clip_02.mp4"), events=("goal", None), job_id=None):
    job_id = job_id or str(uuid.uuid4())
    segs = [{"start": i + 0.5, "end": i + 1.5, "score": 1.0, "reason": "detected", "file": f, **({"event": e} if e else {})} for i, (f, e) in enumerate(zip(files, events))]
    (d := root / "jobs" / job_id).mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(json.dumps({"source_name": "match.mp4", "source_url": None, "duration": 6.0, "version": 0, "segments": segs}), encoding="utf-8")
    return job_id, d
def _defaults(job_id, files=("clip_01.mp4", "clip_02.mp4")):
    return {"job_id": job_id, "reel": REEL, "clips": [{"file": files[0], **GOAL}, {"file": files[1], **OTHER}]}
@pytest.fixture
def env(tmp_path, monkeypatch):
    return monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path)) or (tmp_path, TestClient(api.app))

def test_ac3_defaults_ac4_404_matrix(env):
    root, client = env
    (job_id, _), (odd, _) = _job(root), _job(root, events=("goal", "penalty_shootout"))
    assert [client.get(f"/highlights/{i}/meta").json() for i in (job_id, odd)] == [_defaults(job_id), _defaults(odd)]
    (root / "jobs" / (empty := str(uuid.uuid4()))).mkdir()
    (bad := root / "jobs" / str(uuid.uuid4())).mkdir()
    (bad / "job.json").write_text("{not json", encoding="utf-8")
    for ident in (str(uuid.uuid4()), job_id.upper(), "not-a-uuid", empty, bad.name):
        for r in (client.get(f"/highlights/{ident}/meta"), client.put(f"/highlights/{ident}/meta", json=EDIT)):
            assert (r.status_code, r.json()) == (404, {"detail": "not found"}), ident
    assert not list(root.rglob("meta.json"))

def test_ac5_ac6_ac9_persist_reject_and_fallback(env):
    (root, client), (job_id, d), (fresh, fresh_dir) = env, _job(env[0]), _job(env[0])
    bad, dup = copy.deepcopy(EDIT), copy.deepcopy(EDIT)
    bad["reel"]["title"], bad["clips"][1]["hashtags"], dup["clips"][0]["hashtags"] = "Ngắn", ["#A", "#B"], ["#BongDa", "#bongda", "#X"]
    assert client.put(f"/highlights/{fresh}/meta", json=bad).status_code == 422 and not (fresh_dir / "meta.json").exists()
    job_bytes, r = (d / "job.json").read_bytes(), client.put(f"/highlights/{job_id}/meta", json=EDIT)
    assert r.status_code == 200 and r.json() == {"job_id": job_id, **EDIT} and list(r.json()["clips"][0]) == ["file", "title", "caption", "hashtags"]
    assert client.get(f"/highlights/{job_id}/meta").json() == {"job_id": job_id, **EDIT} and (d / "job.json").read_bytes() == job_bytes
    saved = (d / "meta.json").read_bytes()  # raises if the valid PUT did not create meta.json
    for payload, detail in ((bad, "reel: title length 4; clip 2: hashtag count 2"), (dup, "clip 1: duplicate hashtag #bongda")):
        r = client.put(f"/highlights/{job_id}/meta", json=payload)
        assert (r.status_code, r.json()) == (422, {"detail": detail}) and (d / "meta.json").read_bytes() == saved
    _job(root, files=("clip_01_v1.mp4", "clip_02_v1.mp4"), job_id=job_id)  # AC9: a re-cut renames the clips
    assert client.get(f"/highlights/{job_id}/meta").json() == {**_defaults(job_id, ("clip_01_v1.mp4", "clip_02_v1.mp4")), "reel": EDIT["reel"]}
    _job(root, job_id=job_id)
    for corrupt in ("{oops", json.dumps({"reel": EDIT["reel"]}), "[]"):
        (d / "meta.json").write_text(corrupt, encoding="utf-8")
        assert client.get(f"/highlights/{job_id}/meta").json() == _defaults(job_id)

MUTATE = {"missing": lambda b: b["clips"].pop(), "extra": lambda b: b["clips"].append({**b["clips"][0], "file": "clip_03.mp4"}),
          "swapped": lambda b: b["clips"].reverse(), "unknown": lambda b: b["clips"][1].update(file="nope.mp4"),
          "x-top": lambda b: b.update(extra=1), "no-reel": lambda b: b.pop("reel"), "x-clip": lambda b: b["clips"][0].update(extra=1),
          "tags-str": lambda b: b["clips"][0].update(hashtags="#BongDa #X #Y"), "title-num": lambda b: b["reel"].update(title=12345678901)}
@pytest.mark.parametrize("change", list(MUTATE))
def test_ac7_ac8_mismatch_and_schema_422(env, change):
    (root, client), (job_id, d) = env, _job(env[0])
    MUTATE[change](body := copy.deepcopy(EDIT))
    r = client.put(f"/highlights/{job_id}/meta", json=body)
    assert r.status_code == 422 and not (d / "meta.json").exists()
    assert r.json() == {"detail": "clips must match the job's clips"} if change in ("missing", "extra", "swapped", "unknown") else isinstance(r.json()["detail"], list)

class _Tags(HTMLParser):
    def __init__(self): super().__init__(); self.stack, self.tags = [], []
    def handle_starttag(self, tag, attrs):
        self.tags.append(el := {"tag": tag, "a": dict(attrs), "up": {t["a"].get("id") for t in self.stack}, "text": ""})
        if tag not in ("input", "link", "meta", "br"): self.stack.append(el)
    def handle_endtag(self, tag): del self.stack[max((i for i, t in enumerate(self.stack) if t["tag"] == tag), default=len(self.stack)):]
    def handle_data(self, data): self.stack and self.stack[-1].update(text=self.stack[-1]["text"] + data)
def test_ac10_preview_html_contract(env):
    root, client = env
    r = client.get(f"/jobs/{_job(root)[0]}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and r.text == (WEB / "preview.html").read_text(encoding="utf-8")
    (p := _Tags()).feed(r.text)
    def one(tag, inside, text, **a):  # exactly one tag with these attrs (None = boolean attr present) under #inside
        hits = [t for t in p.tags if t["tag"] == tag and inside in t["up"] | {None} and all(k in t["a"] and t["a"][k] == v for k, v in a.items())]
        assert len(hits) == 1 and (text is None or hits[0]["text"].strip() == text), (tag, a)
    one("section", None, None, id="meta", hidden=None); one("h2", "meta", "Tiêu đề, mô tả và hashtag"); one("ol", "meta", None, id="meta-list"); one("button", "meta", "Lưu tiêu đề và hashtag", id="save-meta", type="button", disabled=None)
    for tag, cls, kind in (("li", "meta-item", {}), ("h3", "meta-name", {}), ("input", "meta-title", {"type": "text"}), ("textarea", "meta-caption", {}), ("input", "meta-hashtags", {"type": "text"})):
        one(tag, "meta-row", None, **{"class": cls}, **kind)
    one("button", "meta-row", "Sao chép", type="button", **{"class": "copy"}); one("button", "segment-row", "Lồng tiếng", type="button", hidden=None, **{"class": "voiceover", "aria-pressed": "false"})
    assert [t["a"].get("href") or t["a"]["src"] for t in p.tags if t["tag"] in ("link", "script")] == ["/static/style.css", "/static/timefmt.js", "/static/filters.js", "/static/metafmt.js", "/static/preview.js"]
    assert all("defer" in t["a"] for t in p.tags if t["tag"] == "script") and next(t for t in p.tags if t["tag"] == "a")["a"]["href"] == "/"
    assert not re.search(r"https?://", r.text) and (js := client.get("/static/metafmt.js")).status_code == 200 and "javascript" in js.headers["content-type"]

def test_ac11_metafmt_node_contract(tmp_path):
    node = shutil.which("node") or pytest.skip("node is required on PATH")
    assert not re.search(r"document|window|fetch|localStorage|XMLHttpRequest|navigator", (WEB / "metafmt.js").read_text(encoding="utf-8"))
    (runner := tmp_path / "r.js").write_text("""const M = require(process.argv[2]); const S = M.clipSources; const o = {clip_url: '/c/1.mp4'}
process.stdout.write(JSON.stringify({p: ['#BongDa  #Highlight,#KhoanhKhac\\n', ' , ', '', null, 'BongDa #bongda'].map(M.parseHashtags),
 f: [M.formatHashtags(['#A', '#B']), M.formatHashtags([])], c: M.copyText({title: 'Bàn thắng đẹp', caption: 'Xem lại nhé!', hashtags: ['#BongDa', '#Highlight']}),
 s: [S(o), S({...o, voiceover_url: '/c/1_vo.mp4'}), S({...o, voiceover_url: ''}), S({...o, voiceover_url: null}), S({...o, voiceover_url: 5}), S({clip_url: null}), S(undefined)],
 k: Object.keys(M).sort(), g: globalThis.SportsCutMeta === M}))""", encoding="utf-8")
    out = subprocess.run([node, str(runner), str(WEB / "metafmt.js")], check=True, capture_output=True, text=True)
    orig, vo = {"label": "Bản gốc", "url": "/c/1.mp4"}, {"label": "Lồng tiếng", "url": "/c/1_vo.mp4"}
    assert json.loads(out.stdout) == {"p": [["#BongDa", "#Highlight", "#KhoanhKhac"], [], [], [], ["BongDa", "#bongda"]], "f": ["#A #B", ""],
        "c": "Bàn thắng đẹp\nXem lại nhé!\n#BongDa #Highlight", "s": [[orig], [orig, vo], [orig], [orig], [orig], [], []],
        "k": ["clipSources", "copyText", "formatHashtags", "parseHashtags"], "g": True} and out.stderr == ""

def test_ac12_preview_js_markers():
    js = (WEB / "preview.js").read_text(encoding="utf-8")
    for marker in ("const M = globalThis.SportsCutMeta", "fetch(`/highlights/${encodeURIComponent(jobId)}/meta`)", "fetch(`/highlights/${encodeURIComponent(jobId)}/meta`, {",
                   "M.clipSources(seg)", "M.formatHashtags(", "M.parseHashtags(", "M.copyText(", "navigator.clipboard.writeText(", "voiceover_url", "aria-pressed",
                   "Đã sao chép.", "Không sao chép được. Hãy chọn chữ và sao chép thủ công.", "Đã lưu tiêu đề và hashtag."):
        assert marker in js, marker
    assert "innerHTML" not in js and not re.search(r"https?://", js) and js.index("saveMeta.disabled = true") < js.index("async function loadJob()")
    at = js.index("async function loadJob()")  # loadMeta() runs after acceptResponse(data) in loadJob, and after the segments PUT
    assert js.index("acceptResponse(data)", at) < js.index("loadMeta()", at) < js.index("\n}\n", at)
    at = js.index('save.addEventListener("click"')
    assert js.index("fetch(", at) < js.index("loadMeta()", at) < js.index("\n})\n", at)
