import json, re, shutil, subprocess  # noqa: E401
from dataclasses import replace
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sportscut import api
from sportscut.commentary.eval_meta import format_problems
from sportscut.commentary.facts import ClipFacts
from sportscut.commentary.meta import ClipMeta, generate_meta
WEB, JOB_ID = Path(__file__).resolve().parents[1] / "sportscut" / "web", "1b4e28ba-2fa1-11d2-883f-0016d3cca427"
TAGS, URL = ["#BongDa", "#BanThang", "#Highlight"], f"/highlights/{JOB_ID}/meta"
def test_format_problems_rules():
    assert all(format_problems(generate_meta(ClipFacts(e))) == [] for e in api.EVENT_TYPES)
    ok = ClipMeta("Bàn thắng đẹp mắt", "Xem lại.", tuple(TAGS))
    for field, value, expected in [("title", "Ngắn", "title length 4"), ("caption", "a" * 301, "caption length 301"),
            ("hashtags", ("#A", "#B"), "hashtag count 2"), ("hashtags", ("#BongDa", "#Việt", "#X"), "bad hashtag #Việt"),
            ("hashtags", ("#BongDa", "#bongda", "#X"), "duplicate hashtag #bongda")]:
        assert format_problems(replace(ok, **{field: value})) == [expected]

@pytest.fixture
def client(tmp_path, monkeypatch):  # hand-written job dir, no ffmpeg (as test_web_filters._write_hand_job)
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    (job_dir := tmp_path / "jobs" / JOB_ID).mkdir(parents=True)
    job = {"source_name": "match.mp4", "source_url": None, "duration": 6.0, "version": 0, "segments": [
        {"start": 0.5, "end": 1.5, "score": 2.0, "reason": "d", "event": "goal", "file": "clip_01.mp4"},
        {"start": 2.0, "end": 3.0, "score": 1.0, "reason": "d", "file": "clip_02.mp4"}]}
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    return TestClient(api.app), job_dir
def _body(*files, reel_title="Tổng hợp U23 Việt Nam", tags=TAGS):
    clips = [{"file": f, "title": "Siêu phẩm phút cuối", "caption": "Xem lại.", "hashtags": tags} for f in files]
    return {"reel": {"title": reel_title, "caption": "Hay.", "hashtags": TAGS}, "clips": clips}
def test_get_meta_defaults(client):
    assert client[0].get(URL).json() == {"job_id": JOB_ID, "reel": api.REEL_DEFAULT.to_dict(), "clips": [{"file": f, **generate_meta(
        ClipFacts(e)).to_dict()} for f, e in (("clip_01.mp4", "goal"), ("clip_02.mp4", "other"))]}
    assert client[0].get("/highlights/not-a-uuid/meta").json() == {"detail": "not found"}

def test_put_meta_valid_persists_and_invalid_422(client):
    (http, job_dir), job_bytes = client, (client[1] / "job.json").read_bytes()
    swapped = http.put(URL, json=_body("clip_02.mp4", "clip_01.mp4"))  # AC7: clips must match the job, in order
    assert swapped.json() == {"detail": "clips must match the job's clips"} and not (job_dir / "meta.json").exists()
    saved = http.put(URL, json=_body("clip_01.mp4", "clip_02.mp4"))
    assert saved.status_code == 200 and http.get(URL).json() == saved.json()
    assert list(saved.json()["clips"][0]) == ["file", "title", "caption", "hashtags"]
    stored = (job_dir / "meta.json").read_bytes()
    bad = http.put(URL, json=_body("clip_01.mp4", "clip_02.mp4", reel_title="Ngắn", tags=["#A", "#B"]))
    assert bad.json() == {"detail": "reel: title length 4; clip 1: hashtag count 2; clip 2: hashtag count 2"}
    shape = http.put(URL, json={**_body("clip_01.mp4", "clip_02.mp4"), "extra": 1})
    assert swapped.status_code == bad.status_code == shape.status_code == 422 and isinstance(shape.json()["detail"], list)
    assert (job_dir / "meta.json").read_bytes() == stored and (job_dir / "job.json").read_bytes() == job_bytes

def test_metafmt_node_contract(tmp_path):
    if shutil.which("node") is None: pytest.skip("node is required on PATH")  # noqa: E701
    (runner := tmp_path / "runner.js").write_text(
        "const M = require(process.argv[2]); console.log(JSON.stringify([M.parseHashtags('#A  #B,#C\\n'), "
        "M.parseHashtags(null), M.copyText({title: 'T', caption: 'C', hashtags: ['#A', '#B']}), M.clipSources("
        "{clip_url: '/c.mp4', voiceover_url: '/v.mp4'}), M.clipSources({clip_url: '/c.mp4', voiceover_url: ''}), "
        "M.clipSources(undefined), globalThis.SportsCutMeta === M]))", encoding="utf-8")
    out = subprocess.run(["node", str(runner), str(WEB / "metafmt.js")], check=True, capture_output=True, text=True)
    orig = {"label": "Bản gốc", "url": "/c.mp4"}
    assert json.loads(out.stdout) == [["#A", "#B", "#C"], [], "T\nC\n#A #B", [orig, {"label": "Lồng tiếng", "url": "/v.mp4"}], [orig], [], True]

def test_preview_html_meta_contract(client):
    html = client[0].get(f"/jobs/{JOB_ID}").text
    assert all(f in html for f in ('<section id="meta" hidden>', '<h2>Tiêu đề, mô tả và hashtag</h2>', '<ol id="meta-list">',
        'type="button" id="save-meta" disabled>Lưu tiêu đề và hashtag<', '<template id="meta-row"><li class="meta-item">',
        '<h3 class="meta-name">', 'class="meta-title" type="text"', '<textarea class="meta-caption"', 'class="meta-hashtags" '
        'type="text"', 'type="button" class="copy">Sao chép<', 'type="button" class="voiceover" aria-pressed="false" hidden>Lồng tiếng<'))
    assert re.findall(r'src="(/static/[a-z]+\.js)" defer', html)[1:3] == ["/static/filters.js", "/static/metafmt.js"]
    order = ['class="clip-player"', 'class="voiceover"', 'id="save"', 'id="meta"', 'id="status"']
    assert [html.index(marker) for marker in order] == sorted(html.index(marker) for marker in order)

def test_preview_js_meta_markers():
    src, url = (WEB / "preview.js").read_text(encoding="utf-8"), "fetch(`/highlights/${encodeURIComponent(jobId)}/meta`"
    assert all(m in src for m in ("const M = globalThis.SportsCutMeta", url + ")", url + ", {", "M.clipSources(seg)",
        "M.formatHashtags(", "M.parseHashtags(", "M.copyText(", "navigator.clipboard.writeText(", "voiceover_url",
        "aria-pressed", "Đã sao chép.", "Không sao chép được. Hãy chọn chữ và sao chép thủ công.", "Đã lưu tiêu đề và hashtag."))
    load_at, save_at = src.index("async function loadJob()"), src.index('save.addEventListener("click"')
    assert src.index("saveMeta.disabled = true") < load_at < src.index("loadMeta()", src.index("acceptResponse(data)", load_at))
    assert src.index("loadMeta()", src.index("/segments`", save_at)) < load_at
    assert "innerHTML" not in src and "http://" not in src and "https://" not in src
