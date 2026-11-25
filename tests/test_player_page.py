import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient
from sportscut.api import app  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / "sportscut" / "web"
SPEC = WEB.parents[1] / "docs/superpowers/specs/2026-11-23-t-008-serve-a-web-upload-page-for-design.md"
EXPECTED = {  # id: (tag, exact attribute values, attributes that must be present)
    "player-section": ("section", {}, ()), "player-form": ("form", {}, ()),
    "player-file": ("input", {"name": "file", "type": "file", "accept": "video/*"}, ()),
    "player-job-id": ("input", {"name": "job_id", "type": "text"}, ()),
    "player-team-name": ("input", {"name": "team_name", "type": "text"}, ()),
    "player-team-color": ("input", {"name": "team_color", "type": "color", "value": "#ff0000"}, ()),
    "player-number": ("input", {"name": "number", "type": "number", "min": "1", "max": "99", "step": "1"}, ()),
    "player-submit": ("button", {"type": "submit"}, ()), "player-touches": ("ol", {}, ()),
    "player-busy": ("p", {"role": "status"}, ("hidden",)), "player-empty": ("p", {}, ("hidden",)),
    "player-error": ("p", {"role": "alert", "aria-live": "assertive"}, ("hidden",)), "player-result": ("div", {}, ("hidden",)),
    "player-reel": ("video", {}, ("controls",)), "player-source": ("video", {}, ("controls",)),
}


class Collect(HTMLParser):  # start tags + text keyed by id (labels by 'label:<for>')
    def __init__(self):
        super().__init__()
        self.tags, self.text, self.current = [], {}, None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        self.current = attrs.get("id") or (tag == "label" and "label:" + attrs.get("for", ""))

    def handle_data(self, data):
        if self.current and data.strip():  # first text run right after the start tag
            self.text[self.current], self.current = data.strip(), None


def test_player_section_markup():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    page = Collect()
    page.feed(response.text)
    ids = [attrs.get("id") for _, attrs in page.tags]
    assert ids.index("player-section") > ids.index("highlights-form")
    for key, (tag, values, present) in EXPECTED.items():
        assert ids.count(key) == 1, key
        found_tag, attrs = page.tags[ids.index(key)]
        assert found_tag == tag and all(attrs.get(k) == v for k, v in values.items()), key
        assert all(name in attrs for name in present), key
        assert tag != "input" or page.text.get("label:" + key), key
        assert tag != "video" or "src" not in attrs, key
    assert (page.text["player-title"], page.text["player-empty"]) == (
        "Theo dõi cầu thủ", "Không tìm thấy pha chạm bóng nào.")


def test_player_js_contract():
    source = (WEB / "app.js").read_text(encoding="utf-8")
    for marker in ('fetch("/players", { method: "POST", body: playerData })',
                   '#player-team-name").value.trim()', '|| document.querySelector("#player-team-color").value',
                   'append("team"', 'append("number"', 'append("file", playerFile)', 'append("job_id"',
                   "`/highlights/${encodeURIComponent(data.job_id)}/source`", 'addEventListener("click"',
                   "playerSource.currentTime = touch.t", 'document.createElement("button")',
                   ".textContent", "data.reel_url"):
        assert marker in source, marker
    assert "innerHTML" not in source and "content-type" not in source.lower() and not re.search(r"https?://", source, re.I)
    assert source.index("fetch(") == source.index('fetch("/highlights"')
    assert source.index("finally") < source.index("#player-form") > source.index("busy.hidden = true")


def test_player_css_and_spec_note():
    css = " ".join((WEB / "style.css").read_text(encoding="utf-8").split())
    for rule in ("#busy, #player-busy {", "#error, #player-error {", "video { width: 100%;",
                 "#player-section { margin-top: 2rem;", "#player {", ".clip-player {"):
        assert rule in css, rule
    _, marker, note = SPEC.read_text(encoding="utf-8").rpartition("## Updated by T-034")
    assert marker and "\n## " not in note
    assert all(s in note for s in ("Theo dõi cầu thủ", "#player-section", "#highlights-form"))
