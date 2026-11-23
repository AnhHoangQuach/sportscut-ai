"""Independent acceptance coverage for T-007's public HTTP and export contracts."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from sportscut import api, export, media
from sportscut.models import Segment


RESPONSE_KEYS = {"job_id", "source_name", "source_url", "duration", "highlights"}
HIGHLIGHT_KEYS = {"start", "end", "score", "reason", "clip_url"}


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path / "data"))
    with TestClient(api.app) as client:
        yield client


def _post_upload(
    client: TestClient,
    video: Path,
    *,
    filename: str = "match.mp4",
) -> dict[str, object]:
    with video.open("rb") as source:
        response = client.post(
            "/highlights",
            files={"file": (filename, source, "video/mp4")},
            data={"top": "1", "min_len": "0.5", "max_len": "1.0"},
        )
    assert response.status_code == 200, response.text
    return response.json()


def _job_dir(data_root: Path, response: dict[str, object]) -> Path:
    return data_root / "jobs" / str(response["job_id"])


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _assert_canonical_response(payload: dict[str, object]) -> None:
    assert set(payload) == RESPONSE_KEYS
    assert str(uuid.UUID(str(payload["job_id"]))) == payload["job_id"]
    assert isinstance(payload["duration"], (int, float))
    assert payload["duration"] > 0
    assert isinstance(payload["highlights"], list)
    for highlight in payload["highlights"]:
        assert set(highlight) == HIGHLIGHT_KEYS
        assert highlight["clip_url"].startswith(
            f"http://testserver/highlights/{payload['job_id']}/clips/"
        )


def test_ac2_ac3_upload_post_persists_exact_job_and_canonical_response(
    api_client: TestClient,
    synthetic_video: Path,
    tmp_path: Path,
) -> None:
    payload = _post_upload(api_client, synthetic_video, filename="../inert-name.mp4")
    _assert_canonical_response(payload)
    assert payload["source_name"] == "../inert-name.mp4"
    assert payload["source_url"] is None

    job_dir = _job_dir(tmp_path / "data", payload)
    raw_job = (job_dir / "job.json").read_text(encoding="utf-8")
    job = json.loads(raw_job)
    manifest = json.loads((job_dir / "clips" / "highlights.json").read_text())

    assert set(job) == {"source_name", "source_url", "duration", "version", "segments"}
    assert job == {
        "source_name": "../inert-name.mp4",
        "source_url": None,
        "duration": media.probe_duration(job_dir / "input"),
        "version": 0,
        "segments": manifest,
    }
    assert raw_job == json.dumps(job, indent=2) + "\n"
    assert not (tmp_path / "data" / "jobs" / "inert-name.mp4").exists()


def test_ac2_upload_empty_filename_falls_back_to_upload(
    api_client: TestClient,
    synthetic_video: Path,
) -> None:
    boundary = "sportscut-empty-filename"
    fields = {"top": "1", "min_len": "0.5", "max_len": "1.0"}
    parts = [
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename=""\r\n'
            "Content-Type: video/mp4\r\n\r\n"
        ).encode()
        + synthetic_video.read_bytes()
        + b"\r\n"
    ]
    for name, value in fields.items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode()
        )
    parts.append(f"--{boundary}--\r\n".encode())
    response = api_client.post(
        "/highlights",
        content=b"".join(parts),
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source_name"] == "upload"


def test_ac2_ac4_url_post_and_get_have_identical_canonical_response(
    api_client: TestClient,
    synthetic_video: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_url = "https://youtu.be/acceptance123"

    def fake_download(url: str, destination: str | Path) -> Path:
        assert url == source_url
        output = Path(destination) / "source.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(synthetic_video, output)
        return output

    monkeypatch.setattr(api.sources, "download_youtube", fake_download)
    post = api_client.post(
        "/highlights",
        data={
            "url": source_url,
            "top": "1",
            "min_len": "0.5",
            "max_len": "1.0",
        },
    )
    assert post.status_code == 200, post.text
    payload = post.json()
    _assert_canonical_response(payload)
    assert payload["source_name"] is None
    assert payload["source_url"] == source_url

    job_dir = _job_dir(tmp_path / "data", payload)
    job = json.loads((job_dir / "job.json").read_text())
    manifest = json.loads((job_dir / "clips" / "highlights.json").read_text())
    assert job["source_name"] is None
    assert job["source_url"] == source_url
    assert job["segments"] == manifest

    get = api_client.get(f"/highlights/{payload['job_id']}")
    assert get.status_code == 200
    assert get.json() == payload


def test_ac4_get_rejects_invalid_unknown_missing_and_malformed_jobs(
    api_client: TestClient,
    synthetic_video: Path,
    tmp_path: Path,
) -> None:
    payload = _post_upload(api_client, synthetic_video)
    job_id = str(payload["job_id"])
    job_path = _job_dir(tmp_path / "data", payload) / "job.json"
    original = job_path.read_bytes()

    rejected = [
        "not-a-uuid",
        "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
        str(uuid.uuid4()),
    ]
    for candidate in rejected:
        response = api_client.get(f"/highlights/{candidate}")
        assert response.status_code == 404
        assert response.json() == {"detail": "not found"}

    job_path.unlink()
    missing = api_client.get(f"/highlights/{job_id}")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "not found"}

    for malformed in (
        b"not json\n",
        b'{"source_name":"x"}\n',
        b'{"source_name":"x","source_url":null,"duration":6,"version":0,'
        b'"segments":[{"start":0,"end":"bad","score":null,'
        b'"reason":"manual","file":"clip.mp4"}]}\n',
    ):
        job_path.write_bytes(malformed)
        response = api_client.get(f"/highlights/{job_id}")
        assert response.status_code == 404
        assert response.json() == {"detail": "not found"}

    job_path.write_bytes(original)


def test_ac5_ac6_source_supports_full_and_single_byte_ranges(
    api_client: TestClient,
    synthetic_video: Path,
    tmp_path: Path,
) -> None:
    payload = _post_upload(api_client, synthetic_video)
    source = (_job_dir(tmp_path / "data", payload) / "input").read_bytes()
    endpoint = f"/highlights/{payload['job_id']}/source"

    full = api_client.get(endpoint)
    assert full.status_code == 200
    assert full.headers["content-type"] == "video/mp4"
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["content-length"] == str(len(source))
    assert full.content == source

    cases = [
        ("bytes=2-5", 2, 5),
        ("bytes=2-", 2, len(source) - 1),
        ("bytes=-4", len(source) - 4, len(source) - 1),
        (f"bytes={len(source) - 2}-{len(source) + 100}", len(source) - 2, len(source) - 1),
    ]
    for header, start, end in cases:
        response = api_client.get(endpoint, headers={"Range": header})
        assert response.status_code == 206
        assert response.headers["accept-ranges"] == "bytes"
        assert response.headers["content-range"] == f"bytes {start}-{end}/{len(source)}"
        assert response.headers["content-length"] == str(end - start + 1)
        assert response.content == source[start : end + 1]

    invalid = [
        "items=0-1",
        "bytes=0-1,3-4",
        "bytes=-0",
        f"bytes={len(source)}-",
        "bytes=",
        "bytes=-",
        "bytes=-2-3",
    ]
    for header in invalid:
        response = api_client.get(endpoint, headers={"Range": header})
        assert response.status_code == 416
        assert response.headers["content-range"] == f"bytes */{len(source)}"


def test_ac7_source_rejects_job_and_path_attacks(
    api_client: TestClient,
    synthetic_video: Path,
    tmp_path: Path,
) -> None:
    payload = _post_upload(api_client, synthetic_video)
    job_id = str(payload["job_id"])
    job_dir = _job_dir(tmp_path / "data", payload)
    secret_fragments = [
        (job_dir / "input").read_bytes()[:24],
        (job_dir / "job.json").read_bytes()[:24],
        (job_dir / "clips" / "highlights.json").read_bytes()[:24],
    ]

    requests = [
        "/highlights/not-a-uuid/source",
        "/highlights/AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA/source",
        f"/highlights/{uuid.uuid4()}/source",
        "/highlights/%2e%2e/source",
        f"/highlights/{job_id}/source/job.json",
    ]
    for path in requests:
        response = api_client.get(path, follow_redirects=False)
        assert response.status_code == 404
        assert all(fragment not in response.content for fragment in secret_fragments)

    (job_dir / "input").unlink()
    missing = api_client.get(f"/highlights/{job_id}/source")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "not found"}


def test_ac8_put_validation_precedes_export_and_preserves_all_files(
    api_client: TestClient,
    synthetic_video: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _post_upload(api_client, synthetic_video)
    job_dir = _job_dir(tmp_path / "data", payload)
    endpoint = f"/highlights/{payload['job_id']}/segments"
    before = _file_snapshot(job_dir)
    calls = 0

    def forbidden_export(*args: object, **kwargs: object) -> list[Path]:
        nonlocal calls
        calls += 1
        raise AssertionError("export must not run for an invalid edit")

    monkeypatch.setattr(api.export, "export_clips", forbidden_export)
    invalid_requests: list[tuple[dict[str, object] | None, str | None]] = [
        ({}, None),
        ({"segments": [], "extra": True}, None),
        ({"segments": [{"start": 0.0, "end": 1.0, "extra": True}]}, None),
        ({"segments": [{"start": "wrong", "end": 1.0}]}, None),
        ({"segments": [{"start": -0.1, "end": 1.0}]}, None),
        ({"segments": [{"start": 1.0, "end": 1.0}]}, None),
        ({"segments": [{"start": 2.0, "end": 1.0}]}, None),
        ({"segments": [{"start": 0.0, "end": float(payload["duration"]) + 0.1}]}, None),
        ({"segments": [{"start": 0.0, "end": 0.1}] * 51}, None),
        (None, '{"segments":[{"start":NaN,"end":1.0}]}'),
        (None, '{"segments":[{"start":0.0,"end":Infinity}]}'),
        (None, '{"segments":{"a":NaN}}'),
        (None, '{"segments":[[Infinity]]}'),
        (None, '{"segments":[],"extra":[-Infinity]}'),
    ]
    for body, content in invalid_requests:
        if content is None:
            response = api_client.put(endpoint, json=body)
        else:
            response = api_client.put(
                endpoint,
                content=content,
                headers={"content-type": "application/json"},
            )
        assert response.status_code == 422, (body, content, response.text)
        assert calls == 0
        assert _file_snapshot(job_dir) == before


def test_ac8_accepts_fifty_overlapping_segments(
    api_client: TestClient,
    synthetic_video: Path,
) -> None:
    payload = _post_upload(api_client, synthetic_video)
    response = api_client.put(
        f"/highlights/{payload['job_id']}/segments",
        json={"segments": [{"start": 0.0, "end": 0.1}] * 50},
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["highlights"]) == 50


def test_ac9_ac10_ac11_real_edits_sort_version_recut_and_empty_replace(
    api_client: TestClient,
    synthetic_video: Path,
    tmp_path: Path,
) -> None:
    post = _post_upload(api_client, synthetic_video)
    job_dir = _job_dir(tmp_path / "data", post)
    endpoint = f"/highlights/{post['job_id']}/segments"

    first = api_client.put(
        endpoint,
        json={
            "segments": [
                {"start": 2.0, "end": 2.75, "reason": "custom mark"},
                {"start": 0.25, "end": 1.25, "reason": ""},
            ]
        },
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    _assert_canonical_response(first_body)
    assert [(item["start"], item["end"]) for item in first_body["highlights"]] == [
        (0.25, 1.25),
        (2.0, 2.75),
    ]
    assert [item["score"] for item in first_body["highlights"]] == [None, None]
    assert [item["reason"] for item in first_body["highlights"]] == [
        "manual",
        "custom mark",
    ]
    first_urls = [item["clip_url"] for item in first_body["highlights"]]
    assert [url.rsplit("/", 1)[-1] for url in first_urls] == [
        "clip_01_v1.mp4",
        "clip_02_v1.mp4",
    ]
    for item, url in zip(first_body["highlights"], first_urls, strict=True):
        clip = job_dir / "clips" / url.rsplit("/", 1)[-1]
        assert abs(media.probe_duration(clip) - (item["end"] - item["start"])) <= 0.5
        served = api_client.get(url)
        assert served.status_code == 200
        assert served.headers["content-type"] == "video/mp4"

    first_job = json.loads((job_dir / "job.json").read_text())
    first_manifest = json.loads((job_dir / "clips" / "highlights.json").read_text())
    assert first_job["version"] == 1
    assert first_job["segments"] == first_manifest

    second = api_client.put(
        endpoint,
        json={"segments": [{"start": 1.0, "end": 1.5}]},
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    second_url = second_body["highlights"][0]["clip_url"]
    assert second_url.endswith("/clip_01_v2.mp4")
    second_job = json.loads((job_dir / "job.json").read_text())
    second_manifest = json.loads((job_dir / "clips" / "highlights.json").read_text())
    assert second_job["version"] == 2
    assert second_job["segments"] == second_manifest
    assert all(api_client.get(url).status_code == 404 for url in first_urls)
    assert api_client.get(second_url).status_code == 200

    empty = api_client.put(endpoint, json={"segments": []})
    assert empty.status_code == 200, empty.text
    assert empty.json()["highlights"] == []
    empty_job = json.loads((job_dir / "job.json").read_text())
    empty_manifest = json.loads((job_dir / "clips" / "highlights.json").read_text())
    assert empty_job["version"] == 3
    assert empty_job["segments"] == []
    assert empty_manifest == []
    assert api_client.get(second_url).status_code == 404


def test_ac12_put_rejects_bad_jobs_without_export_or_filesystem_changes(
    api_client: TestClient,
    synthetic_video: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _post_upload(api_client, synthetic_video)
    job_id = str(payload["job_id"])
    job_dir = _job_dir(tmp_path / "data", payload)
    before = _file_snapshot(job_dir)
    called = False

    def forbidden_export(*args: object, **kwargs: object) -> list[Path]:
        nonlocal called
        called = True
        raise AssertionError("invalid jobs must be rejected before export")

    monkeypatch.setattr(api.export, "export_clips", forbidden_export)
    paths = [
        "/highlights/not-a-uuid/segments",
        "/highlights/AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA/segments",
        f"/highlights/{uuid.uuid4()}/segments",
        "/highlights/%2e%2e/segments",
    ]
    for path in paths:
        response = api_client.put(path, json={"segments": []}, follow_redirects=False)
        assert response.status_code == 404
        assert called is False
        assert _file_snapshot(job_dir) == before

    job_path = job_dir / "job.json"
    job_path.write_text("not json\n")
    malformed_before = _file_snapshot(job_dir)
    response = api_client.put(
        f"/highlights/{job_id}/segments", json={"segments": []}
    )
    assert response.status_code == 404
    assert called is False
    assert _file_snapshot(job_dir) == malformed_before


def test_ac13_recut_failures_are_atomic(
    api_client: TestClient,
    synthetic_video: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = _post_upload(api_client, synthetic_video)
    endpoint = f"/highlights/{post['job_id']}/segments"
    seeded = api_client.put(
        endpoint,
        json={"segments": [{"start": 0.5, "end": 1.25}]},
    )
    assert seeded.status_code == 200, seeded.text
    old_get = api_client.get(f"/highlights/{post['job_id']}").json()
    old_url = old_get["highlights"][0]["clip_url"]
    old_clip = api_client.get(old_url).content
    job_dir = _job_dir(tmp_path / "data", post)
    before = _file_snapshot(job_dir)

    def media_failure(
        video: str | Path,
        segments: list[Segment],
        out_dir: str | Path,
        *,
        version_suffix: str = "",
    ) -> list[Path]:
        partial = Path(out_dir) / f"clip_01{version_suffix}.mp4"
        partial.write_bytes(b"partial-media-error")
        raise media.MediaError("cut failed")

    monkeypatch.setattr(api.export, "export_clips", media_failure)
    failed = api_client.put(
        endpoint,
        json={"segments": [{"start": 1.5, "end": 2.0}]},
    )
    assert failed.status_code == 500
    assert failed.json() == {"detail": "processing failed"}
    assert _file_snapshot(job_dir) == before
    assert api_client.get(f"/highlights/{post['job_id']}").json() == old_get
    assert api_client.get(old_url).content == old_clip

    def unexpected_failure(
        video: str | Path,
        segments: list[Segment],
        out_dir: str | Path,
        *,
        version_suffix: str = "",
    ) -> list[Path]:
        partial = Path(out_dir) / f"clip_01{version_suffix}.mp4"
        partial.write_bytes(b"partial-unexpected-error")
        raise RuntimeError("unexpected cut failure")

    monkeypatch.setattr(api.export, "export_clips", unexpected_failure)
    with pytest.raises(RuntimeError, match="unexpected cut failure"):
        api_client.put(
            endpoint,
            json={"segments": [{"start": 1.5, "end": 2.0}]},
        )
    assert _file_snapshot(job_dir) == before
    assert api_client.get(f"/highlights/{post['job_id']}").json() == old_get
    assert api_client.get(old_url).content == old_clip


def test_ac14_public_export_versioning_and_nullable_score(
    synthetic_video: Path,
    tmp_path: Path,
) -> None:
    manual = Segment(start=0.25, end=0.75, score=None, reason="manual")
    numeric = Segment(start=1.0, end=1.5, score=2.5, reason="detected")
    assert manual.to_dict()["score"] is None
    assert numeric.to_dict()["score"] == 2.5

    versioned_dir = tmp_path / "versioned"
    versioned = export.export_clips(
        synthetic_video, [manual], versioned_dir, version_suffix="_v3"
    )
    assert [path.name for path in versioned] == ["clip_01_v3.mp4"]
    versioned_manifest = json.loads(
        (versioned_dir / "highlights.json").read_text()
    )
    assert versioned_manifest[0]["file"] == "clip_01_v3.mp4"

    default_dir = tmp_path / "default"
    default = export.export_clips(synthetic_video, [numeric], default_dir)
    assert [path.name for path in default] == ["clip_01.mp4"]
    assert json.loads((default_dir / "highlights.json").read_text())[0]["file"] == (
        "clip_01.mp4"
    )

    for suffix in ("v3", "_v0", "_v01", "_v-1", "_v3.mp4", "", None):
        if suffix == "":
            continue
        invalid_dir = tmp_path / f"invalid-{suffix}"
        with pytest.raises(ValueError, match="^invalid version suffix$"):
            export.export_clips(
                synthetic_video,
                [manual],
                invalid_dir,
                version_suffix=suffix,  # type: ignore[arg-type]
            )
        assert not invalid_dir.exists()


def test_ac15_http_documentation_and_updated_design_specs() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    for required in (
        "/highlights/JOB_ID",
        "/highlights/JOB_ID/source",
        "Range",
        "curl -X PUT",
        "/highlights/JOB_ID/segments",
        "50",
        "không có lịch sử hoàn tác",
    ):
        assert required.lower() in readme.lower()

    specs = [
        "docs/superpowers/specs/2026-11-23-t-003-export-segments-as-mp4-clips-plus-design.md",
        "docs/superpowers/specs/2026-11-23-t-005-expose-post-highlights-over-http-with-design.md",
        "docs/superpowers/specs/2026-11-23-t-006-accept-a-youtube-link-as-post-design.md",
    ]
    for spec in specs:
        text = Path(spec).read_text(encoding="utf-8")
        assert "Updated by T-007" in text
