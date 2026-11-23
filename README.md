# SportsCut AI

Tự động cắt highlight từ video thể thao, bắt đầu với bóng đá. Code sản phẩm được một
"văn phòng" AI xây dựng: Claude (PM, Tech Lead, Reviewer) và Codex (Developer, Tester),
còn Hoang là Product Owner.

| Thư mục | Nội dung |
| --- | --- |
| `agent-office/` | Orchestrator `office`: điều phối Claude + Codex, worktree mỗi task, review, PR |
| `sportscut/`, `tests/` | Sản phẩm cắt highlight (do văn phòng xây qua các PR sau) |

## Chạy văn phòng trên chính repo này

```bash
git clone https://github.com/AnhHoangQuach/sportscut-ai && cd sportscut-ai
pip install -e ./agent-office         # lệnh `office`, cần Python 3.11+
claude        # /login bằng gói Pro/Max (một lần)
codex login   # đăng nhập bằng ChatGPT (một lần)

office init                           # tạo .agent-office/ (đã gitignore)
```

Sửa `.agent-office/config.toml` cho repo này:

```toml
[office]
base_branch = "main"
test_cmd = "python -m pytest -q tests"
protected_paths = ["agent-office/", "AGENTS.md", "CLAUDE.md"]   # agent không sửa orchestrator và quy tắc
merge_mode = "auto"                   # review đạt + test pass thì tự merge vào main
```

Rồi:

```bash
office doctor --live
pip install -e './agent-office[dashboard]'
office dashboard     # gửi yêu cầu, bấm Bắt đầu, trả lời khi Claude hỏi; nút "Văn phòng 3D"
office demo          # xem các agent phối hợp bằng agent mô phỏng, không tốn quota
```

Hoặc chỉ dùng terminal: `office request -f agent-office/examples/sportscut/po_request.md`
rồi `office run --watch`.

Khi MVP xong, giao yêu cầu thứ hai để tăng độ chính xác bằng số đo (F1 trên bộ nhãn):
`office request -f agent-office/examples/sportscut/po_request_accuracy.md`. Quy tắc làm việc
chung của các agent (TDD, đo trước tối ưu sau, có bằng chứng mới báo xong) ở [AGENTS.md](AGENTS.md).

Tài liệu đầy đủ (kiến trúc multi-agent, code, văn phòng 3D, công nghệ SportsCut, áp dụng cho dự án khác): [docs/](docs/README.md).

Chi tiết: [agent-office/README.md](agent-office/README.md).

## Theo dõi cầu thủ: đo độ chính xác (eval-player)

Tạo bộ video tổng hợp và chạy phép đo:

```bash
python tests/fixtures/eval_player/build.py
python -m sportscut eval-player tests/fixtures/eval_player --json
```

Mỗi ca có dạng `<thư-mục>/<tên-ca>/{clip.mp4,labels.json}`. Nhãn chứa `players`
(tùy chọn) và `touches`, ví dụ `{"players":[{"team":"red","number":10}],
"touches":[{"t":3.0,"team":"red","number":10}]}`. Video thật dùng cùng định dạng
tại `data/eval_player/<name>/{clip.mp4,labels.json}`. Một dự đoán khớp khi cách nhãn
không quá ±0.5 giây; phép khớp là một-một.

Baseline đo trong T-029:

```json
{"f1": 0.0, "precision": 0.0, "recall": 0.0, "touch_f1_any": 0.0, "team_accuracy": null, "id_accuracy": null, "seconds_per_min": 0.0, "per_clip": [{"clip": "dribble", "duration": 20.0, "touches": 13, "queries": 4, "f1": 0.0, "precision": 0.0, "recall": 0.0, "touch_f1_any": 0.0, "team_accuracy": null, "id_accuracy": null, "seconds_per_min": 0.0}, {"clip": "near_miss", "duration": 20.0, "touches": 6, "queries": 5, "f1": 0.0, "precision": 0.0, "recall": 0.0, "touch_f1_any": 0.0, "team_accuracy": null, "id_accuracy": null, "seconds_per_min": 0.0}, {"clip": "number_hidden", "duration": 20.0, "touches": 8, "queries": 3, "f1": 0.0, "precision": 0.0, "recall": 0.0, "touch_f1_any": 0.0, "team_accuracy": null, "id_accuracy": null, "seconds_per_min": 0.0}, {"clip": "short_passes", "duration": 24.0, "touches": 12, "queries": 6, "f1": 0.0, "precision": 0.0, "recall": 0.0, "touch_f1_any": 0.0, "team_accuracy": null, "id_accuracy": null, "seconds_per_min": 0.0}]}
```

Mục tiêu tiếp theo: `touch_f1_any ≥ 0.9` (T-031), `team_accuracy ≥ 0.95`
(T-032), và `F1 ≥ 0.85` (T-033).
