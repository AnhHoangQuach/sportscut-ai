"""Independent acceptance tests for T-008's browser upload page."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import sys
import tomllib

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

    def one_element(self, **expected: str) -> dict[str, str | None]:
        matches = [attrs for _, attrs in self.tags if all(attrs.get(k) == v for k, v in expected.items())]
        assert len(matches) == 1, f"expected one element with {expected}, found {len(matches)}"
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
    vietnamese_label_terms = {
        "file": ("tệp", "video"),
        "url": ("liên kết", "youtube"),
        "top": ("số", "đoạn"),
        "min_len": ("thời lượng", "tối thiểu"),
        "max_len": ("thời lượng", "tối đa"),
    }
    for name, input_type in expected.items():
        control = page.one("input", id=name, name=name, type=input_type)
        assert "required" not in control
        label = page.labels.get(name, "").lower()
        assert label, f"missing associated label for {name}"
        assert all(term in label for term in vietnamese_label_terms[name]), label
    assert page.one("input", id="file").get("accept") == "video/*"
    assert page.one("input", id="top").get("min") == "1"
    assert page.one("input", id="top").get("step") == "1"
    for name in ("min_len", "max_len"):
        assert float(page.one("input", id=name)["min"] or "0") > 0
        assert page.one("input", id=name).get("step") == "any"

    normalized = " ".join(html.split()).lower()
    assert "chỉ chọn một trong hai" in normalized
    assert "tệp video" in normalized and "liên kết youtube" in normalized
    page.one("button", id="submit")
    assert "hidden" in page.one_element(id="busy", role="status")
    error = page.one_element(id="error", role="alert")
    assert "hidden" in error and error.get("aria-live") == "assertive"
    assert "đang xử lý" in normalized


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

    assert 'addEventListener("submit"' in source or "addEventListener('submit'" in source
    assert "preventDefault()" in source
    assert re.search(r"files\s*\[\s*0\s*\]", source)
    assert re.search(r"urlInput\.value\.trim\(\)", source)
    assert "Hãy chọn một tệp video hoặc nhập một liên kết YouTube." in source
    source_check = re.search(
        r"if\s*\(\s*\(.*?file.*?&&.*?url.*?\)\s*\|\|\s*"
        r"\(\s*!.*?file.*?&&\s*!.*?url.*?\)\s*\)\s*\{.*?return\s*;?\s*\}",
        compact,
    )
    assert source_check
    assert source_check.start() < source.index("new FormData()") < source.index("fetch(")
    assert "new FormData()" in source
    assert re.search(r"if\s*\(\s*file\s*\).*append\(\s*[\"']file[\"']", compact)
    assert re.search(r"else.*append\(\s*[\"']url[\"']", compact)
    assert ".trim()" in source
    for field in ("top", "min_len", "max_len"):
        assert re.search(rf"#{field}[^\n]*\.value\.trim\(\)", source)
        assert re.search(rf"if\s*\([^)]*{field}[^)]*\).*append\(\s*[\"']{field}[\"']", compact)

    assert re.search(r"fetch\(\s*[\"']/highlights[\"']\s*,", source)
    assert re.search(r"method\s*:\s*[\"']POST[\"']", source)
    assert re.search(r"body\s*:\s*formData", source)
    assert not re.search(r"content-type", source, re.IGNORECASE)
    fetch_at = source.index("fetch(")
    assert source.index(".disabled = true") < fetch_at
    assert source.index('setAttribute("aria-busy", "true")') < fetch_at
    assert source.index("busy.hidden = false") < fetch_at
    finally_at = source.index("finally")
    assert source.index(".disabled = false") > finally_at
    assert "removeAttribute(\"aria-busy\")" in source or "removeAttribute('aria-busy')" in source
    assert source.index("busy.hidden = true") > finally_at
    assert "await response.json()" in source
    assert "detail" in source and ".msg" in source and ".join(\"; \")" in source
    assert "Lỗi ${response.status}:" in source
    assert "Không thể xử lý video." in source
    assert "Không thể kết nối hoặc phản hồi từ máy chủ không hợp lệ." in source
    assert re.search(r"typeof\s+data\.job_id\s*!==\s*[\"']string[\"']", compact)
    assert re.search(r"!\s*data\.job_id", source)
    assert "window.location.assign(`/jobs/${encodeURIComponent(data.job_id)}`)" in source


def test_acceptance_non_ok_json_without_detail_keeps_status_and_fallback() -> None:
    source = TestClient(app).get("/static/app.js").text
    compact = re.sub(r"\s+", " ", source)

    assert "Không thể xử lý video." in source
    assert "Lỗi ${response.status}:" in source
    null_safe_detail_access = (
        "data?.detail" in source
        or re.search(r"data\s*&&\s*(?:typeof\s+)?data\.detail", compact)
        or re.search(r"data\s*!={1,2}\s*null.*?data\.detail", compact)
        or re.search(r"if\s*\(\s*!data\s*\).*?else.*?data\.detail", compact)
    )
    assert null_safe_detail_access, (
        "a non-OK response containing valid JSON null must not throw while reading detail"
    )


def test_acceptance_packaging_is_declared_without_a_frontend_build_or_dependency() -> None:
    project = Path(__file__).resolve().parents[1]
    configuration = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    assert configuration["tool"]["setuptools"]["package-data"]["sportscut"] == [
        "web/*.html",
        "web/*.js",
        "web/*.css",
    ]
    assert configuration["project"]["dependencies"] == ["numpy>=1.26"]
    assert not (project / "sportscut" / "web" / "__init__.py").exists()
    assert not (project / "package.json").exists()


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
    probe = f"""
import sys
sys.path.insert(0, {str(target)!r})
from importlib import resources
from pathlib import Path
import sportscut
assert Path(sportscut.__file__).resolve().is_relative_to(Path({str(target)!r}).resolve())
for name in ('index.html', 'app.js', 'style.css'):
    item = resources.files('sportscut').joinpath('web', name)
    assert item.is_file(), name
    assert item.read_text(encoding='utf-8').strip(), name
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        check=False,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
