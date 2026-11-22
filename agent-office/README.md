# Agent Office

Văn phòng phần mềm gồm hai agent AI, chạy bằng CLI trên máy bạn, **không dùng API key**:

| Vai | Agent | Gọi qua |
| --- | --- | --- |
| Product Owner | Bạn | `office request`, merge PR |
| Product Manager, Tech Lead, Reviewer | Claude Code | `claude -p` (đăng nhập gói Pro/Max) |
| Developer, Tester | Codex | `codex exec` (đăng nhập gói ChatGPT) |

Luồng: yêu cầu của PO → Claude tách task + viết spec/acceptance criteria → Codex code + test
trong **git worktree riêng của task** → orchestrator chạy lại test → Claude review diff (tối đa 3
vòng) → mở PR → bạn merge.

Đây là **giai đoạn 1** (CLI). Dashboard 2D và văn phòng 3D ở giai đoạn sau chỉ cần đọc
`.agent-office/state.json` và `.agent-office/events.jsonl`.

## Cài đặt

Yêu cầu: Python 3.11+, git, [Claude Code](https://docs.claude.com/en/docs/claude-code) và
[Codex CLI](https://github.com/openai/codex) đã đăng nhập, `gh` (GitHub CLI) nếu muốn tự mở PR.

```bash
git clone https://github.com/AnhHoangQuach/sportscut-ai && cd sportscut-ai
pip install -e ./agent-office          # cung cấp lệnh `office`
claude          # chạy một lần, /login bằng tài khoản Pro/Max
codex login     # đăng nhập bằng ChatGPT
```

Orchestrator **xóa** `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `OPENAI_API_KEY`, `CODEX_API_KEY`
khỏi môi trường trước khi gọi CLI, nên dù shell của bạn có key thì vẫn dùng gói thuê bao.

## Dùng

```bash
cd sportscut-ai                     # repo đích (ở đây là chính repo này), đã có commit trên main
office init                         # tạo .agent-office/ (đã nằm trong git exclude)
$EDITOR .agent-office/config.toml   # base_branch, test_cmd, protected_paths, open_pr...
office doctor --live                # kiểm tra 2 CLI đã đăng nhập

office request "Tôi cần CLI cắt highlight video bóng đá..."   # hoặc -f yeu_cau.md
office run                          # chạy đến khi hết việc; tự ngủ khi agent hết quota
office status                       # agent + task
office board                        # kanban theo stage
office show T-001                   # spec, AC, lịch sử, đường dẫn log
office answer T-002 "Dùng ffmpeg, bỏ qua GPU"   # trả lời task bị blocked
office sync                         # đánh dấu done các task đã merge (run cũng tự gọi)
office wake codex                   # bắt agent làm việc lại ngay
```

`office run --once` chạy đúng một bước; `--no-wait` thoát thay vì ngủ khi agent đang nghỉ.

## State machine

```
todo → spec → dev → test → review → pr → done
               ↑      │       │
               └──────┘       │   test fail (tối đa 3 lần)
               ↑              │
               └──────────────┘   review "changes" (vòng 1–2)
                                  vòng 3 vẫn "changes" → blocked → office answer
```

Task chỉ sang `spec` khi các task nó phụ thuộc đã `done` (đã merge), để worktree mới luôn có code
của task trước.

## Hết quota (usage limit)

- Mọi mẫu nhận diện nằm trong `agent_office/limits.py` (`STRONG_PATTERNS`, `WEAK_PATTERNS`).
- Đọc được giờ reset (epoch, `resets 8pm (Asia/Saigon)`, `try again in 2 hours`,
  `resets_in_seconds`) → nghỉ đến giờ đó + 1 phút.
- Không có giờ reset → nghỉ 15 → 30 → 60 phút, hết giờ thì gửi một probe rẻ ("Reply OK").
- 2 lần lỗi lạ liên tiếp cũng bị coi là hết quota.
- Khi bị ngắt: commit WIP trong worktree, ghi `.office/CHECKPOINT.md`, task giữ nguyên stage.
  Lần sau Codex nhận prompt "RESUMING" và làm tiếp.
- Mỗi agent nghỉ độc lập: Codex nghỉ thì Claude vẫn viết spec/review task khác.

## Bảo vệ đường dẫn

`protected_paths` trong config liệt kê thư mục agent không được sửa (ví dụ `agent-office/` khi
orchestrator nằm chung repo với sản phẩm). Diff của task đụng vào đó thì task bị `blocked`.

## Cấu trúc

```
agent_office/
  cli.py        lệnh office
  pipeline.py   xử lý từng stage, checkpoint, rest/wake
  scheduler.py  chọn bước tiếp theo theo agent đang rảnh
  models.py     Task, Agent, Stage, chuyển trạng thái hợp lệ
  store.py      state.json (ghi nguyên tử) + events.jsonl
  limits.py     nhận diện usage limit + giờ reset
  worktree.py   git worktree, commit, diff, gh pr
  agents/       claude.py, codex.py
  prompts/      prompt từng vai (sửa thoải mái)
examples/sportscut/   yêu cầu PO mẫu cho dự án đầu tiên
tests/                test end-to-end với CLI giả lập
```

Trong mỗi worktree, thư mục `.office/` chứa `TASK.md`, `CHECKPOINT.md`, `TEST_REPORT.md`,
`REVIEW-n.md` cho agent đọc; không bao giờ được commit. Log đầy đủ mỗi lần gọi agent ở
`.agent-office/logs/<task>/`.

## Test

```bash
pip install -e '.[dev]'
python -m pytest -q
```

Test dùng `tests/fake_agent.py` thay cho `claude`/`codex`, nên không tốn quota.
