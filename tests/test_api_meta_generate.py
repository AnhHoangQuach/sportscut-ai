import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from sportscut import api, media, pipeline
from sportscut.commentary import publish

NEED = "home, away, competition, kickoff and meta_backend need meta"
TEAMS = {"meta": "true", "home": "Hà Nội", "away": "Viettel"}
ENTRIES = [{"start": start, "end": start + 10.0, "score": 1.0, "reason": "peak", "event": event,
            "event_confidence": 0.5, "file": f"clip_0{i}.mp4"}
           for i, (start, event) in enumerate([(0.0, "goal"), (20.0, "other")], 1)]
HL_KEYS = ["start", "end", "score", "reason", "event", "event_confidence", "clip_url"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(media, "probe_duration", lambda path: 60.0)
    return TestClient(api.app)


def fake_run(entries, calls=None):
    def run(video, out_dir, **kw):
        if calls is not None:
            calls.append(kw)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "highlights.json").write_text(json.dumps(entries, indent=2) + "\n")
        return [dict(e) for e in entries]
    return run


def post(client, **data):
    return client.post("/highlights", files={"file": ("match.mp4", b"video")}, data=data)


def ok(meta):
    return api.format_problems(api.ClipMeta(meta["title"], meta["caption"], tuple(meta["hashtags"]))) == []


@pytest.mark.parametrize("data, detail", [
    ({"home": "Hà Nội"}, NEED),
    ({"meta_backend": "template"}, NEED),
    ({"meta": "true", "home": "x" * 41}, "home must be a stripped string of 1 to 40 characters"),
    ({"meta": "true", "kickoff": "-5"}, "kickoff must be non-negative"),
    ({"meta": "true", "kickoff": "nan"}, list),
    ({"meta": "true", "meta_backend": "gpt"}, list),
    ({"meta": "maybe"}, list),
])
def test_meta_fields_need_meta_and_valid_match(env, tmp_path, monkeypatch, data, detail):
    calls = []
    monkeypatch.setattr(pipeline, "run", fake_run(ENTRIES, calls))
    before = set(tmp_path.glob("jobs/*"))
    response = post(env, **data)
    got = response.json()["detail"]
    assert response.status_code == 422 and (isinstance(got, list) if detail is list else got == detail)
    assert calls == [] and set(tmp_path.glob("jobs/*")) == before
    assert post(env, home="  ").status_code == 200


@pytest.fixture
def meta_job(env, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "run", fake_run(ENTRIES))
    body = post(env, **TEAMS).json()
    return env, body["job_id"], body, tmp_path / "jobs" / body["job_id"]


def test_post_meta_generates_and_returns_metadata(meta_job, tmp_path):
    _, _, body, job_dir = meta_job
    assert list(body) == ["job_id", "source_name", "source_url", "duration", "highlights", "reel"]
    stored = json.loads((job_dir / "clips/highlights.json").read_text(encoding="utf-8"))
    for item, entry in zip(body["highlights"], stored, strict=True):
        assert list(item) == HL_KEYS + ["title", "caption", "hashtags"]
        assert "Hà Nội vs Viettel" in item["title"] and ok(item) and {"#HaNoi", "#Viettel"} <= set(item["hashtags"])
        assert {k: item[k] for k in publish.META_KEYS} == {k: entry[k] for k in publish.META_KEYS}
    assert body["reel"] == json.loads((job_dir / "clips/reel.json").read_text(encoding="utf-8"))
    assert body["reel"]["title"] == "Tổng hợp highlight: Hà Nội vs Viettel" and ok(body["reel"])
    assert json.loads((job_dir / "job.json").read_text()) == {
        "source_name": "match.mp4", "source_url": None, "duration": 60.0, "version": 0, "segments": ENTRIES}
    (copy := tmp_path / "copy").mkdir()
    (copy / "highlights.json").write_text(json.dumps(ENTRIES, indent=2) + "\n")
    publish.write_meta(copy, {"home": "Hà Nội", "away": "Viettel"}, "template")
    for name in ("highlights.json", "captions.txt", "reel.json"):
        assert (job_dir / "clips" / name).read_bytes() == (copy / name).read_bytes()


def test_get_job_and_meta_use_stored_metadata(meta_job):
    client, job_id, body, job_dir = meta_job
    assert client.get(f"/highlights/{job_id}").json() == body
    goal = client.get(f"/highlights/{job_id}?event=goal").json()
    assert goal["highlights"] == body["highlights"][:1] and goal["reel"] == body["reel"]
    meta = client.get(f"/highlights/{job_id}/meta").json()
    assert list(meta) == ["job_id", "reel", "clips"] and meta["reel"] == body["reel"] != api.REEL_DEFAULT.to_dict()
    stored = json.loads((job_dir / "clips/highlights.json").read_text(encoding="utf-8"))
    assert meta["clips"] == [{"file": e["file"], **{k: e[k] for k in publish.META_KEYS}} for e in stored]
    assert all(c != {"file": e["file"], **api._default_clip_meta(e)} for c, e in zip(meta["clips"], stored))


def test_put_meta_overrides_stored(meta_job):
    client, job_id, _, _ = meta_job
    text = {"title": "Bàn thắng đẹp mắt", "caption": "Một pha bóng tuyệt vời. Cùng xem lại nhé!",
            "hashtags": ["#BongDa", "#Highlight", "#TongHop"]}
    edits = {"reel": text, "clips": [{"file": e["file"], **text} for e in ENTRIES]}
    assert client.put(f"/highlights/{job_id}/meta", json=edits).status_code == 200
    assert client.get(f"/highlights/{job_id}/meta").json() == {"job_id": job_id, **edits}
    job = client.get(f"/highlights/{job_id}").json()
    assert job["reel"] == text and all({k: h[k] for k in publish.META_KEYS} == text for h in job["highlights"])
    bad = client.put(f"/highlights/{job_id}/meta", json={**edits, "clips": edits["clips"][:1]})
    assert bad.status_code == 422 and bad.json()["detail"] == "clips must match the job's clips"


def test_no_meta_unchanged_and_zero_clips(env, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "run", fake_run(ENTRIES, calls))
    body = post(env).json()
    assert list(body) == ["job_id", "source_name", "source_url", "duration", "highlights"]
    assert all(list(h) == HL_KEYS for h in body["highlights"])
    assert not any((tmp_path / "jobs" / body["job_id"] / "clips" / n).exists() for n in ("reel.json", "captions.txt"))
    assert [set(kw) for kw in calls] == [{"top", "min_len", "max_len", "events"}]
    meta = env.get(f"/highlights/{body['job_id']}/meta").json()
    assert meta["reel"] == api.REEL_DEFAULT.to_dict() and meta["clips"] == [{"file": e["file"], **api._default_clip_meta(e)} for e in ENTRIES]
    monkeypatch.setattr(pipeline, "run", fake_run([]))
    empty = post(env, **TEAMS)
    assert empty.status_code == 200 and "reel" not in empty.json()
    assert not (tmp_path / "jobs" / empty.json()["job_id"] / "clips/reel.json").exists()


def test_llm_backend_passed_through(env, monkeypatch):
    seen, real = [], publish.write_meta
    monkeypatch.setattr(pipeline, "run", fake_run(ENTRIES))
    monkeypatch.setattr(api.publish, "write_meta", lambda d, m, b: seen.append((m, b)) or real(d, m, b))
    assert [post(env, **TEAMS, **extra).status_code for extra in ({"meta_backend": "llm"}, {})] == [200, 200]
    assert seen == [({"home": "Hà Nội", "away": "Viettel"}, "llm"),
                    ({"home": "Hà Nội", "away": "Viettel"}, "template")]


def test_upload_form_sends_match_fields(env):
    html = env.get("/").text
    form = html[html.index('id="highlights-form"'):html.index('id="submit"')]
    assert '<fieldset id="match-info">' in form and "<legend>Thông tin trận đấu" in form
    for name in ("home", "away", "competition"):
        assert f'<label for="{name}">' in form and f'<input id="{name}" name="{name}" type="text" maxlength="40">' in form
    assert (js := env.get("/static/app.js")).status_code == 200
    marks = ['if (events) formData.append("events", events)', '["home", "away", "competition"]',
             'formData.append("meta", "true")', 'fetch("/highlights"']
    assert [js.text.index(m) for m in marks] == sorted(js.text.index(m) for m in marks)
