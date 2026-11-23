"""Independent acceptance tests for T-008's browser upload page."""

from __future__ import annotations

from html.parser import HTMLParser
import os
from pathlib import Path
import re
import subprocess
import sys

from fastapi.testclient import TestClient

from sportscut.api import app


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.labels: dict[str, str] = {}
        self._label_for: str | None = None
        self._label_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        self.tags.append((tag, attributes))
        if tag == "label" and attributes.get("for"):
            self._label_for = attributes["for"]
            self._label_text = []

    def handle_data(self, data: str) -> None:
        if self._label_for:
            self._label_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._label_for:
            self.labels[self._label_for] = " ".join(self._label_text).strip()
            self._label_for = None

    def one(self, tag: str, **expected: str) -> dict[str, str | None]:
        matches = [attrs for actual_tag, attrs in self.tags if actual_tag == tag and all(attrs.get(k) == v for k, v in expected.items())]
        assert len(matches) == 1, f"expected one <{tag}> with {expected}, found {len(matches)}"
        return matches[0]


def _page() -> tuple[str, _PageParser]:
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    parser = _PageParser()
    parser.feed(response.text)
    return response.text, parser


def test_acceptance_upload_page_has_complete_accessible_vietnamese_form() -> None:
    html, page = _page()
    assert re.search(r"<!doctype\s+html", html, re.IGNORECASE)
    page.one("html", lang="vi")
    page.one("form", id="highlights-form")

    expected = {
        "file": "file",
        "url": "url",
        "top": "number",
        "min_len": "number",
        "max_len": "number",
    }
    for name, input_type in expected.items():
        control = page.one("input", id=name, name=name, type=input_type)
        assert "required" not in control
        assert page.labels.get(name), f"missing associated label for {name}"
    assert page.one("input", id="file").get("accept") == "video/*"
    assert page.one("input", id="top").get("min") == "1"
    assert page.one("input", id="top").get("step") == "1"
    for name in ("min_len", "max_len"):
        assert float(page.one("input", id=name)["min"] or "0") > 0
        assert page.one("input", id=name).get("step") == "any"

    normalized = " ".join(html.split()).lower()
    assert "một" in normalized and "tệp" in normalized and "youtube" in normalized
    page.one("button", id="submit")
    assert "hidden" in page.one("div", id="busy", role="status")
    error = page.one("div", id="error", role="alert")
    assert "hidden" in error and error.get("aria-live") == "assertive"


def test_acceptance_page_uses_only_local_declared_assets() -> None:
    html, page = _page()
    stylesheet = page.one("link", rel="stylesheet")
    script = page.one("script", src="/static/app.js")
    assert stylesheet.get("href") == "/static/style.css"
    assert "defer" in script
    references = [value for _, attrs in page.tags for key, value in attrs.items() if key in {"href", "src"} and value]
    assert references == ["/static/style.css", "/static/app.js"]
    assert not re.search(r"https?://", html, re.IGNORECASE)


def test_acceptance_static_assets_are_served_with_safe_content_types() -> None:
    client = TestClient(app)
    javascript = client.get("/static/app.js")
    stylesheet = client.get("/static/style.css")
    missing = client.get("/static/not-a-real-asset.js")
    assert javascript.status_code == stylesheet.status_code == 200
    assert javascript.headers["content-type"].split(";", 1)[0] in {"text/javascript", "application/javascript"}
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert missing.status_code == 404
    assert not re.search(r"https?://", javascript.text + stylesheet.text, re.IGNORECASE)


def test_acceptance_frontend_submission_and_response_contract() -> None:
    source = TestClient(app).get("/static/app.js").text
    compact = re.sub(r"\s+", " ", source)

    assert "Hãy chọn một tệp video hoặc nhập một liên kết YouTube." in source
    assert re.search(r"if\s*\(\s*\(.*file.*&&.*url.*\)\s*\|\|\s*\(\s*!.*file.*&&\s*!.*url", compact)
    assert "new FormData()" in source
    assert re.search(r"if\s*\(\s*file\s*\).*append\(\s*[\"']file[\"']", compact)
    assert re.search(r"else.*append\(\s*[\"']url[\"']", compact)
    assert ".trim()" in source
    for field in ("top", "min_len", "max_len"):
        assert re.search(rf"if\s*\([^)]*{field}[^)]*\).*append\(\s*[\"']{field}[\"']", compact)

    assert re.search(r"fetch\(\s*[\"']/highlights[\"']\s*,", source)
    assert re.search(r"method\s*:\s*[\"']POST[\"']", source)
    assert re.search(r"body\s*:\s*formData", source)
    assert not re.search(r"content-type", source, re.IGNORECASE)
    assert "aria-busy" in source and ".disabled = true" in source
    assert "finally" in source and ".disabled = false" in source
    assert "removeAttribute(\"aria-busy\")" in source or "removeAttribute('aria-busy')" in source
    assert "detail" in source and ".msg" in source and ".join(\"; \")" in source
    assert "Lỗi ${response.status}:" in source
    assert "Không thể xử lý video." in source
    assert "Không thể kết nối hoặc phản hồi từ máy chủ không hợp lệ." in source
    assert re.search(r"typeof\s+.*job_id.*===\s*[\"']string[\"']", compact)
    assert "window.location.assign(`/jobs/${encodeURIComponent(data.job_id)}`)" in source


def test_acceptance_built_wheel_contains_all_web_resources(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[1]
    wheel_dir = tmp_path / "wheel"
    target = tmp_path / "installed"
    wheel_dir.mkdir()
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheel_dir), str(project)],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    wheels = list(wheel_dir.glob("sportscut-*.whl"))
    assert len(wheels) == 1
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(target), str(wheels[0])],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    probe = """
from importlib import resources
for name in ('index.html', 'app.js', 'style.css'):
    item = resources.files('sportscut').joinpath('web', name)
    assert item.is_file(), name
    assert item.read_text(encoding='utf-8').strip(), name
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(target)
    completed = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        check=False,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    # -I deliberately ignores PYTHONPATH, so insert the isolated target explicitly.
    if completed.returncode != 0:
        isolated_probe = f"import sys; sys.path.insert(0, {str(target)!r});" + probe
        completed = subprocess.run(
            [sys.executable, "-I", "-c", isolated_probe],
            check=False,
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
    assert completed.returncode == 0, completed.stderr
