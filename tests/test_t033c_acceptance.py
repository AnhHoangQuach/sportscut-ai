"""T-053 (T-033 slice C) Tester acceptance tests, written from the acceptance criteria in .office/TASK.md."""
import ast, importlib.util, json, os, re, subprocess, sys, tomllib
from pathlib import Path
import numpy as np, pytest
from sportscut import jersey, subtitles
from sportscut.cli import main
from sportscut.commentary import voiceover
from sportscut.eval_player import evaluate_dir
ROOT = Path(__file__).resolve().parent.parent
FAKE = """CALLS, RESULTS, IMAGES = [], [], []
class Reader:
    def __init__(self, *args, **kwargs): CALLS.append((args, kwargs))
    def readtext(self, image, **kw): IMAGES.append((image, kw)); return list(RESULTS)
"""
BAD = "SPORTSCUT_NUMBER_READER must be auto, digits or ocr"
@pytest.fixture
def fake(tmp_path, monkeypatch):
    (tmp_path / "fake").mkdir(); (tmp_path / "fake" / "easyocr.py").write_text(FAKE)
    monkeypatch.delitem(sys.modules, "easyocr", raising=False); monkeypatch.syspath_prepend(str(tmp_path / "fake"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache")); monkeypatch.setattr(jersey, "_ocr_reader", None)
    import easyocr
    yield easyocr
    sys.modules.pop("easyocr", None)
def models(n=2):
    d = jersey.ocr_dir(); d.mkdir(parents=True, exist_ok=True)
    for f in jersey.OCR_MODEL_FILES[:n]: (d / f).write_bytes(b"")
B = [[0, 0], [1, 0], [1, 1], [0, 1]]
def test_ac1_lazy_load_once_and_kwargs(fake):
    r = jersey.OcrReader(); assert fake.CALLS == []
    crop = np.zeros((6, 5, 3), np.uint8)
    for _ in range(3): r.read(crop)
    assert len(fake.CALLS) == 1
    assert fake.CALLS[0] == ((["en"],), {"gpu": False, "model_storage_directory": str(jersey.ocr_dir()), "download_enabled": False, "verbose": False})
def test_ac1_scaled_image_and_allowlist(fake):
    crop = np.random.default_rng(1).integers(0, 255, (7, 3, 3), dtype=np.uint8)
    jersey.OcrReader().read(crop)
    ((img, kw),) = fake.IMAGES
    assert img.shape == (28, 12, 3) and np.array_equal(img, np.repeat(np.repeat(crop, 4, 0), 4, 1))
    assert kw == {"allowlist": "0123456789", "detail": 1}
@pytest.mark.parametrize("results, want", [
    ([(B, "10", .9), (B, "7", .95), (B, "abc", .99), (B, "123", .99), (B, "07", .99)], (7, 0.95)),
    ([], (None, 0.0)), ([(B, "9", 1.3)], (9, 1.0)), ([(B, "0", .99), (B, "", .99)], (None, 0.0)),
    ([(B, "12", .8), (B, "34", .8)], (12, 0.8)), ([(B, "5", -0.2)], (5, 0.0)), ([(B, "99", .123456)], (99, 0.1235))])
def test_ac1_parses_results(fake, results, want):
    fake.RESULTS[:] = results
    n, c = jersey.OcrReader().read(np.zeros((4, 4, 3), np.uint8))
    assert (n, c) == want and type(c) is float and (n is None or type(n) is int)
def test_ac1_identity():
    assert jersey.OcrReader.name == "ocr" and jersey.OcrReader().max_reads == jersey.OCR_MAX_READS == 4 and jersey.OCR_SCALE == 4
def test_ac2_dir_constants_availability(fake, tmp_path, monkeypatch):
    assert jersey.ocr_dir() == tmp_path / "cache" / "sportscut" / "easyocr"
    assert jersey.OCR_MODEL_FILES == ("craft_mlt_25k.pth", "english_g2.pth") and jersey.READER_ENV == "SPORTSCUT_NUMBER_READER"
    assert jersey.ocr_available() is False; models(1); assert jersey.ocr_available() is False
    models(2); assert jersey.ocr_available() is True
    monkeypatch.setitem(sys.modules, "easyocr", None); assert jersey.ocr_available() is False
@pytest.mark.parametrize("value", [None, "", "auto", "digits", "ocr", "tesseract", "OCR", " ocr", "Auto"])
@pytest.mark.parametrize("available", [True, False])
def test_ac2_get_reader_env_matrix(fake, monkeypatch, value, available):
    if value is None: monkeypatch.delenv("SPORTSCUT_NUMBER_READER", raising=False)
    else: monkeypatch.setenv("SPORTSCUT_NUMBER_READER", value)
    if available: models()
    assert jersey.ocr_available() is available
    if value in (None, "", "auto"):
        assert type(jersey.get_reader()) is (jersey.OcrReader if available else jersey.DigitReader)
    elif value == "digits": assert type(jersey.get_reader()) is jersey.DigitReader
    elif value == "ocr" and available: assert type(jersey.get_reader()) is jersey.OcrReader
    elif value == "ocr":
        with pytest.raises(ValueError) as e: jersey.get_reader()
        assert "pip install 'sportscut[ocr]'" in str(e.value) and "download-models --ocr" in str(e.value)
    else:
        with pytest.raises(ValueError) as e: jersey.get_reader()
        assert str(e.value) == BAD
    assert fake.CALLS == []  # choosing a reader never loads the model
def test_ac2_ocr_instance_cached(fake, monkeypatch):
    models(); monkeypatch.setenv("SPORTSCUT_NUMBER_READER", "ocr"); a = jersey.get_reader()
    monkeypatch.setenv("SPORTSCUT_NUMBER_READER", "auto"); b = jersey.get_reader()
    assert a is b and isinstance(a, jersey.OcrReader)
    for r in (a, b): r.read(np.zeros((3, 3, 3), np.uint8))
    assert len(fake.CALLS) == 1
def no_dl(monkeypatch):
    monkeypatch.setattr(subtitles, "download_models", lambda *a, **k: pytest.fail("subtitles called"))
    monkeypatch.setattr(voiceover, "download_voice", lambda *a, **k: pytest.fail("voiceover called"))
def test_ac3_cli_ok(monkeypatch, capsys):
    no_dl(monkeypatch); monkeypatch.setattr(jersey, "download_ocr_models", lambda: Path("/c/ocr"))
    assert main(["download-models", "--ocr"]) == 0
    assert capsys.readouterr().out == "downloaded EasyOCR models to /c/ocr\n"
def test_ac3_cli_missing_extra(monkeypatch, capsys, tmp_path):
    no_dl(monkeypatch); monkeypatch.setitem(sys.modules, "easyocr", None); monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert main(["download-models", "--ocr"]) == 1
    assert capsys.readouterr().err == "sportscut download-models: error: needs the [ocr] extra: pip install 'sportscut[ocr]'\n"
def test_ac3_cli_other_error(monkeypatch, capsys):
    no_dl(monkeypatch)
    def boom(): raise RuntimeError("offline")
    monkeypatch.setattr(jersey, "download_ocr_models", boom)
    assert main(["download-models", "--ocr"]) == 1 and capsys.readouterr().err == "sportscut download-models: error: offline\n"
def test_ac3_cli_ocr_and_tts_exit_2(monkeypatch, capsys):
    no_dl(monkeypatch); monkeypatch.setattr(jersey, "download_ocr_models", lambda: pytest.fail("ocr called"))
    for argv in (["download-models", "--ocr", "--tts"], ["download-models", "--tts", "--ocr"]):
        with pytest.raises(SystemExit) as e: main(argv)
        assert e.value.code == 2 and "--ocr and --tts cannot be combined" in capsys.readouterr().err
def test_ac3_help_lists_both():
    out = subprocess.run([sys.executable, "-m", "sportscut", "download-models", "--help"], capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0 and "--ocr" in out.stdout and "--tts" in out.stdout
def test_ac3_download_with_fake(fake):
    d = jersey.ocr_dir(); assert not d.exists()
    assert jersey.download_ocr_models() == d and d.is_dir()
    assert fake.CALLS == [((["en"],), {"gpu": False, "model_storage_directory": str(d), "download_enabled": True, "verbose": False})]
def test_ac4_pyproject():
    p = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]; opt = p["optional-dependencies"]
    assert opt["ocr"] == ["easyocr>=1.7"] and p["dependencies"] == ["numpy>=1.26"]
    assert {"api", "youtube", "llm", "asr", "tts", "dev", "ocr"} <= set(opt) and not any("easyocr" in x for x in opt["dev"])
    assert opt["tts"] == ["piper-tts>=1.3"]
def test_ac5_import_isolation():
    code = "import sys, sportscut.jersey, sportscut.player; print('easyocr' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=True)
    assert out.stdout.strip() == "False"
    tree = ast.parse((ROOT / "sportscut/jersey.py").read_text()); roots = set()
    for node in tree.body:
        if isinstance(node, ast.Import): roots |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom): roots.add(node.module)
    assert roots <= {"__future__", "math", "os", "re", "importlib.util", "pathlib", "collections.abc", "typing", "numpy"}
    for node in ast.walk(tree):  # easyocr imported only inside function bodies
        if isinstance(node, (ast.Import, ast.ImportFrom)) and "easyocr" in ast.dump(node): assert node not in tree.body
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    inside = {id(x) for f in funcs for x in ast.walk(f)}
    assert all(id(n) in inside for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "easyocr")
def test_ac6_root_conftest_forces_digits():
    assert os.environ["SPORTSCUT_NUMBER_READER"] == "digits" and type(jersey.get_reader()) is jersey.DigitReader
    src = (ROOT / "conftest.py").read_text()
    assert "autouse=True" in src and "SPORTSCUT_NUMBER_READER" in src and '"digits"' in src
@pytest.mark.skipif(not jersey.ocr_available(), reason="[ocr] extra not installed")
def test_ac7_ocr_timing(tmp_path, monkeypatch, require_ffmpeg):
    s = importlib.util.spec_from_file_location("t053_build", ROOT / "tests/fixtures/eval_player/build.py")
    build = importlib.util.module_from_spec(s); s.loader.exec_module(build)
    build.build_all(tmp_path / "ep", force=True)
    monkeypatch.setenv("SPORTSCUT_NUMBER_READER", "ocr"); monkeypatch.setattr(jersey, "_ocr_reader", None)
    report = evaluate_dir(tmp_path / "ep"); print(json.dumps(report))
    assert report["seconds_per_min"] <= 6.0
def section():
    t = (ROOT / "README.md").read_text(); i = t.index("## Số áo cầu thủ (T-033)"); j = t.index("\n## ", i + 1)
    assert t.rindex("\n## ", 0, i) == t.index("## Theo dõi cầu thủ: xuất video tổng hợp (player)") - 1
    assert t[j + 1:].startswith("## Đội theo màu áo (T-032)"); return t[i:j]
def test_ac8_readme_section():
    s = section()
    for need in ("SPORTSCUT_NUMBER_READER", "auto", "digits", "ocr", "pip install 'sportscut[ocr]'", "sportscut download-models --ocr", "EasyOCR", "git", "Trước T-033:", "Sau T-033:"):
        assert need in s, need
    texts = re.findall(r"```text\n(.*?)```", s, re.S); assert texts
    vals = {k: v for b in texts for k, v in re.findall(r"^(OCR_SCALE|OCR_MAX_READS) = (\d+)", b, re.M)}
    assert vals == {"OCR_SCALE": str(jersey.OCR_SCALE), "OCR_MAX_READS": str(jersey.OCR_MAX_READS)}
    assert re.search(r"```bash\n[^`]*pip install 'sportscut\[ocr\]'[^`]*sportscut download-models --ocr", s)
def test_ac9_spec_last_line():
    t = (ROOT / "docs/superpowers/specs/2026-11-23-t-033-read-jersey-numbers-around-each-touch-design.md").read_text()
    last = t.rstrip("\n").split("\n")[-1]
    assert last.startswith("Updated by T-053:")
    for w in ("OcrReader", "SPORTSCUT_NUMBER_READER", "download-models --ocr", "[ocr]", "conftest.py"): assert w in last, w
    para = t.rstrip("\n").split("\n\n")[-1]; assert para.startswith("Updated by T-052:") and para.endswith(last)
    assert "\n## " not in t[t.index("## Updated by T-051"):]
@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    import shutil
    if not shutil.which("ffmpeg"): pytest.skip("ffmpeg required")
    p = tmp_path_factory.mktemp("c") / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "color=c=green:s=320x180:r=10:d=2", "-f", "lavfi", "-i",
                    "anoisesrc=d=2:c=white:r=44100:a=0.02:seed=3", "-c:v", "mpeg4", "-c:a", "aac", "-t", "2", str(p)], check=True, capture_output=True)
    return p
@pytest.mark.parametrize("value, needle", [("tesseract", "sportscut player: error: " + BAD), ("ocr", "pip install 'sportscut[ocr]'")])
def test_ac11_player_cli_errors(clip, tmp_path, value, needle):
    env = {**os.environ, "SPORTSCUT_NUMBER_READER": value, "XDG_CACHE_HOME": str(tmp_path / "empty")}
    code = "import sys; sys.modules['easyocr'] = None; from sportscut.cli import main; sys.exit(main(sys.argv[1:]))"
    out_dir = tmp_path / "reel"
    r = subprocess.run([sys.executable, "-c", code, "player", str(clip), "--team", "blue", "--number", "8", "--out", str(out_dir)],
                       capture_output=True, text=True, cwd=ROOT, env=env)
    assert r.returncode == 2, r.stderr
    assert needle in r.stderr
    if value == "tesseract": assert r.stderr.strip().splitlines()[-1] == "sportscut player: error: " + BAD
    assert not out_dir.exists() or not list(out_dir.rglob("*.mp4"))
