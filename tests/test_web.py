import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient

from sportscut.api import app


client = TestClient(app)


def test_root_serves_upload_form():
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert "<!doctype html>" in html.lower()
    assert '<form id="highlights-form">' in html
    for name, input_type in (
        ("file", "file"),
        ("url", "url"),
        ("top", "number"),
        ("min_len", "number"),
        ("max_len", "number"),
    ):
        assert f'<label for="{name}">' in html
        assert f'id="{name}"' in html
        assert f'name="{name}"' in html
        assert f'type="{input_type}"' in html
    assert 'accept="video/*"' in html
    assert 'id="top" name="top" type="number" min="1" step="1"' in html
    assert 'id="min_len" name="min_len" type="number" min="0.1" step="any"' in html
    assert 'id="max_len" name="max_len" type="number" min="0.1" step="any"' in html
    assert "Chỉ chọn một trong hai" in html
    assert 'id="busy" role="status" hidden' in html
    assert 'id="error" role="alert" aria-live="assertive" hidden' in html
    assert 'href="/static/style.css"' in html
    assert 'src="/static/app.js" defer' in html


def test_static_assets_have_expected_content_types():
    javascript = client.get("/static/app.js")
    stylesheet = client.get("/static/style.css")

    assert javascript.status_code == 200
    assert javascript.headers["content-type"].split(";", 1)[0] in {
        "text/javascript",
        "application/javascript",
    }
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert client.get("/static/does-not-exist.css").status_code == 404


def test_frontend_submission_contract():
    javascript = client.get("/static/app.js").text

    assert 'addEventListener("submit"' in javascript
    assert "event.preventDefault()" in javascript
    assert "Hãy chọn một tệp video hoặc nhập một liên kết YouTube." in javascript
    assert "if ((file && url) || (!file && !url))" in javascript
    assert "const formData = new FormData()" in javascript
    assert 'formData.append("file", file)' in javascript
    assert 'formData.append("url", url)' in javascript
    for name in ("top", "min_len", "max_len"):
        assert f'const {name} = document.querySelector("#{name}").value.trim()' in javascript
        assert f'if ({name})' in javascript
        assert f'formData.append("{name}", {name})' in javascript
    assert 'fetch("/highlights", {' in javascript
    assert 'method: "POST"' in javascript
    assert "body: formData" in javascript
    assert "Content-Type" not in javascript
    assert "submit.disabled = true" in javascript
    assert 'form.setAttribute("aria-busy", "true")' in javascript
    assert "busy.hidden = false" in javascript
    assert "response.ok" in javascript
    assert "data?.detail" in javascript
    assert 'item.msg' in javascript
    assert 'Lỗi ${response.status}: ${message}' in javascript
    assert "window.location.assign(`/jobs/${encodeURIComponent(data.job_id)}`)" in javascript
    assert "finally" in javascript
    assert "submit.disabled = false" in javascript
    assert 'form.removeAttribute("aria-busy")' in javascript
    assert "busy.hidden = true" in javascript
    assert "Không thể kết nối hoặc phản hồi từ máy chủ không hợp lệ." in javascript


def test_frontend_non_ok_null_payload_uses_status_fallback():
    javascript = client.get("/static/app.js").text

    assert "const detail = data?.detail" in javascript
    assert 'typeof detail === "string"' in javascript
    assert "Array.isArray(detail)" in javascript
    assert "Không thể xử lý video." in javascript
    assert 'showError(`Lỗi ${response.status}: ${message}`)' in javascript


def test_wheel_install_contains_web_resources(tmp_path):
    wheel_dir = tmp_path / "wheel"
    target = tmp_path / "target"
    outside = tmp_path / "outside"
    wheel_dir.mkdir()
    target.mkdir()
    outside.mkdir()
    project_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheel_dir), "."],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheel_dir.glob("sportscut-*.whl"))
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(target), str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )
    script = """
from importlib import resources
from pathlib import Path

root = resources.files("sportscut")
assert Path(root).resolve().is_relative_to(Path(__import__("sportscut").__file__).resolve().parent)
for name in ("index.html", "app.js", "style.css"):
    asset = root.joinpath("web", name)
    assert asset.is_file(), name
    assert asset.read_text(encoding="utf-8").strip(), name
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(target)
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=outside,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
