import json
from pathlib import Path
from sportscut import player, reel
from sportscut.player import PlayerQuery, Touch

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
WEB = ROOT / "sportscut" / "web"


def sec(heading):
    return README.split(heading + "\n", 1)[1].split("\n## ", 1)[0]


def test_stale_notes_removed():
    for stale in ("vẫn chưa trả về gì cho tới khi T-032/T-033 xong", "vẫn là stub", "chưa lọc theo số áo"):
        assert stale not in README


def test_t031_and_t032_bullets():
    t031 = sec("## Phát hiện chạm bóng (T-031)")
    for marker in ("T-032", "T-033", "find_touches", "sportscut player"):
        assert marker in t031
    report = t031.split("Kết quả đo trong T-031:", 1)[1].split("```json\n", 1)[1].split("```", 1)[0]
    assert json.loads(report)["touch_f1_any"] == 0.9737
    assert "T-033" in sec("## Đội theo màu áo (T-032)")


def test_player_section_lists_manifest_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(reel, "probe_duration", lambda *a: 10.0)
    monkeypatch.setattr(player, "find_touches", lambda *a: [Touch(5.0, "red", 10, 0.9, None)])
    monkeypatch.setattr(reel, "export_clips", lambda *a: [])
    monkeypatch.setattr(reel, "concat_clips", lambda *a: None)
    manifest = reel.make_player_reel("v.mp4", PlayerQuery("red", 10), tmp_path)
    section = sec("## Theo dõi cầu thủ: xuất video tổng hợp (player)")
    for key in list(manifest) + list(manifest["touches"][0]):
        assert f"`{key}`" in section
    assert "player.json" in section and "--min-confidence" in section


def test_api_player_paragraph():
    api = sec("## API HTTP")
    curls = ("curl -F file=@match.mp4 -F team=red -F number=10 http://127.0.0.1:8000/players",
             "curl -F job_id=JOB_ID -F team=red -F number=10 http://127.0.0.1:8000/players",
             'curl -o reel.mp4 "<reel_url>"')
    assert any(all(c in b.split("```", 1)[0] for c in curls) for b in api.split("```bash\n")[1:])
    start = api.index("POST /players")
    assert api.index("/highlights/JOB_ID/segments") < start < api.index("Hiện việc xử lý diễn ra đồng bộ")
    para = api[start:api.index("Hiện việc xử lý")]
    for marker in ("-F team=", "-F number=", "reel_url", "job_id", "422", "404", "null", "#rrggbb", "đồng bộ"):
        assert marker in para


def test_web_step_15():
    web = sec("## Trang web: tải lên, xem trước và chỉnh mốc cắt")
    assert any(line.startswith("15. ") for line in web.splitlines())
    html = (WEB / "index.html").read_text(encoding="utf-8")
    labels = ("Không tìm thấy pha chạm bóng nào.", "Màu áo", "Số áo", "Tạo video cầu thủ", "Video tổng hợp", "Các pha chạm bóng")
    assert "Theo dõi cầu thủ" in web and all(label in web and label in html for label in labels)
    assert "currentTime = touch.t" in (WEB / "app.js").read_text(encoding="utf-8")
