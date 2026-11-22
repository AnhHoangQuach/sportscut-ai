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

Chi tiết: [agent-office/README.md](agent-office/README.md).
