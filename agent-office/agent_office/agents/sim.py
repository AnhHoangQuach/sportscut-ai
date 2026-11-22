"""Simulated agents for `office demo` and `simulate = true`.

They behave like Claude and Codex (plan, spec, code, test, review, run out of quota)
without calling any CLI, so you can watch the whole office work for free.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from ..limits import detect
from .base import AgentResult, CliAgent

SPORTSCUT_TASKS = [
    {"key": "1", "title": "Khởi tạo CLI sportscut + pytest", "depends_on": [],
     "brief": "Tạo package sportscut, lệnh `sportscut --help`, kiểm tra ffmpeg, cấu hình pytest."},
    {"key": "2", "title": "Tách audio bằng ffmpeg", "depends_on": ["1"],
     "brief": "Đọc thời lượng/fps và tách WAV mono 16 kHz từ video."},
    {"key": "3", "title": "Chấm điểm phấn khích theo audio", "depends_on": ["2"],
     "brief": "RMS mỗi giây, chuẩn hóa z-score, tìm đỉnh âm thanh khán giả."},
    {"key": "4", "title": "Phát hiện chuyển cảnh", "depends_on": ["1"],
     "brief": "Tìm mốc chuyển cảnh để bắt biên clip vào cảnh gần nhất."},
    {"key": "5", "title": "Chọn highlight và xuất clip", "depends_on": ["3", "4"],
     "brief": "Top N, đệm 8s/4s, xuất clip + highlights.mp4 + highlights.json."},
]


_STATE_LOCK = threading.Lock()  # sessions run in parallel threads and share one state file


def _resolve_conflicts(cwd: Path) -> None:
    """Keep both sides of every conflict (each task only appends its own lines)."""
    out = subprocess.run(["git", "diff", "--name-only", "--diff-filter=U"], cwd=cwd, capture_output=True,
                         text=True).stdout
    for name in filter(None, out.splitlines()):
        f = cwd / name
        keep = [ln for ln in f.read_text().splitlines(keepends=True)
                if not ln.startswith(("<<<<<<< ", "=======", ">>>>>>> "))]
        f.write_text("".join(keep))
    subprocess.run(["git", "add", "-A"], cwd=cwd, capture_output=True)


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower().encode("ascii", "ignore").decode()).strip("_")
    return s[:30] or "feature"


class SimAgent(CliAgent):
    def __init__(self, name: str, delay: float, state_file: Path):
        super().__init__(cfg=None)
        self.name = name
        self.delay = delay
        self.state_file = state_file

    def _state(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, st: dict[str, Any]) -> None:
        self.state_file.write_text(json.dumps(st))

    def run(self, prompt: str, cwd: Path, log_path: Path | None = None, **extra: Any) -> AgentResult:
        cwd = Path(cwd)
        kind = self._kind(prompt)
        with _STATE_LOCK:
            st = self._state()
            n = st.get(f"{self.name}:{kind}", 0) + 1
            st[f"{self.name}:{kind}"] = n
            self._save(st)
        time.sleep(0.2 if kind == "probe" else self.delay)
        with _STATE_LOCK:
            st = self._state()
            out, err, code = self._answer(kind, n, prompt, cwd, st)
        res = AgentResult(self.name, code, out, err, text=out if code == 0 else "")
        res.limit = detect(self.name, out, err, code)
        if log_path:
            log_path.write_text(f"[simulated {self.name}] {kind} #{n}\n--- prompt ---\n{prompt}\n"
                                f"--- exit {code} ---\n{out}\n{err}\n", encoding="utf-8")
            res.log_path = str(log_path)
        return res

    def _kind(self, prompt: str) -> str:
        if "Reply with exactly: OK" in prompt:
            return "probe"
        for marker, kind in (("Split the request", "breakdown"), ("implementation spec", "spec"),
                             ("Tech Lead reviewer", "review"), ("has been built, reviewed and merged", "goal"),
                             ("**Tester**", "test"), ("**Developer**", "dev")):
            if marker in prompt:
                return kind
        return "other"

    def _answer(self, kind: str, n: int, prompt: str, cwd: Path, st: dict) -> tuple[str, str, int]:
        task = re.search(r"task (T-\d+)", prompt)
        tid = task.group(1) if task else "T-000"
        if kind == "probe":
            return "OK", "", 0
        if kind == "breakdown":
            return json.dumps({"tasks": SPORTSCUT_TASKS}, ensure_ascii=False), "", 0
        if kind == "spec":
            title = re.search(r"## Task T-\d+: (.+)", prompt)
            t = title.group(1).strip() if title else tid
            return json.dumps({
                "spec": f"### {t}\n\nThêm module `sportscut/{_slug(t)}.py` và test tương ứng.\n\n"
                        "Assumptions: Python 3.11, ffmpeg có trong PATH.",
                "acceptance_criteria": [f"{t} chạy được qua CLI", "Có test tự động cho trường hợp chính",
                                        "Báo lỗi rõ khi đầu vào sai"],
                "test_plan": [f"test_{_slug(t)}_happy_path", f"test_{_slug(t)}_bad_input"],
                "out_of_scope": ["Model ML"]}, ensure_ascii=False), "", 0
        if kind == "review":
            first_t3 = tid == "T-003" and not st.get("t3_reviewed")
            if first_t3:
                st["t3_reviewed"] = True
                self._save(st)
                return json.dumps({"verdict": "changes", "summary": "Thiếu test cho audio im lặng.",
                                   "comments": [{"file": "sportscut/scoring.py", "line": 12, "severity": "major",
                                                 "text": "Chia cho độ lệch chuẩn = 0 khi audio im lặng; thêm guard và test."}]},
                                  ensure_ascii=False), "", 0
            return json.dumps({"verdict": "approve", "summary": f"{tid} đạt đủ acceptance criteria, test rõ ràng.",
                               "comments": []}, ensure_ascii=False), "", 0
        if kind == "goal":
            return json.dumps({"done": True, "summary": "`sportscut cut match.mp4` tìm khoảnh khắc hay theo audio "
                                                        "và chuyển cảnh, xuất clip + highlights.json."},
                              ensure_ascii=False), "", 0
        if kind == "dev" and "MERGE CONFLICT" in prompt:
            _resolve_conflicts(cwd)
            return "Đã gộp main, giữ cả hai phần trong sportscut/commands.py, pytest pass.", "", 0
        if kind == "dev":
            if n == 2 and not st.get("limit_done"):  # run out of quota once, mid-task
                st["limit_done"] = True
                self._save(st)
                (cwd / "sportscut").mkdir(exist_ok=True)
                (cwd / "sportscut" / f"wip_{tid.lower().replace('-', '_')}.py").write_text("# work in progress\n")
                return "", "You've hit your usage limit. Try again in 20 seconds.", 1
            slug = tid.lower().replace("-", "_")
            (cwd / "sportscut").mkdir(exist_ok=True)
            (cwd / "tests").mkdir(exist_ok=True)
            (cwd / "sportscut" / "__init__.py").touch()
            reg = cwd / "sportscut" / "commands.py"  # every task registers here -> parallel tasks conflict
            lines = reg.read_text() if reg.exists() else "COMMANDS = []\n"
            if f"'{tid}'" not in lines:
                reg.write_text(lines + f"COMMANDS.append('{tid}')\n")
            (cwd / "sportscut" / f"{slug}.py").write_text(f'"""{tid} (simulated)."""\n\n\ndef run():\n    return "{tid}"\n')
            (cwd / "tests" / f"test_{slug}.py").write_text(
                f"from sportscut.{slug} import run\n\n\ndef test_run():\n    assert run() == \"{tid}\"\n")
            return f"Đã thêm sportscut/{slug}.py và tests/test_{slug}.py, pytest pass.", "", 0
        if kind == "test":
            (cwd / ".office").mkdir(exist_ok=True)
            (cwd / ".office" / "TEST_REPORT.md").write_text("Mọi AC có test, pytest: pass\n")
            return "3 passed\nRESULT: PASS", "", 0
        return "OK", "", 0
