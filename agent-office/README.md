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

Giai đoạn 1 là CLI, giai đoạn 2 thêm **dashboard 2D realtime** và **chế độ tự động hoàn toàn**:
các agent tự làm tới khi yêu cầu được giao xong, tự merge khi review đạt và test pass, chỉ hỏi
PO khi yêu cầu chưa rõ. Giai đoạn 3 thêm **văn phòng 3D**: nhìn thấy Claude và Codex giao việc,
báo xong, review, hết quota và nghỉ, merge vào main. Giai đoạn 4 cho các agent **làm song song**
(Codex 2 task cùng lúc), tự gỡ xung đột merge, và thêm rào chắn + thống kê quota.

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
office answer T-002 "Dùng ffmpeg, bỏ qua GPU"   # trả lời task (hoặc yêu cầu R-xxx) bị blocked
office sync                         # đánh dấu done các task đã merge (run cũng tự gọi)
office wake codex                   # bắt agent làm việc lại ngay
```

`office run --once` chạy đúng một bước; `--no-wait` thoát thay vì ngủ khi agent đang nghỉ.

## Dashboard 2D (giai đoạn 2)

```bash
pip install -e './agent-office[dashboard]'   # FastAPI + uvicorn
office dashboard                             # mở http://127.0.0.1:8765
```

Trên dashboard anh làm được mọi việc mà không cần terminal:

- Gửi yêu cầu mới, bấm **Bắt đầu** / **Dừng** runner (`office run --watch` chạy nền,
  log ở `.agent-office/logs/runner.log`).
- Xem Kanban 8 cột (todo → done + blocked), task nào đang được agent nào làm.
- Thẻ agent: rảnh / đang làm gì / nghỉ vì hết quota đến mấy giờ (đếm ngược), nút "Làm lại ngay".
- Khung **Cần anh trả lời**: câu hỏi của Claude cho yêu cầu hoặc task bị chặn, trả lời tại chỗ.
- Bấm vào task: spec, acceptance criteria, ghi chú review/test, lịch sử, log từng lần gọi agent.
- Feed hoạt động realtime qua WebSocket.

Dashboard chỉ nghe ở `127.0.0.1`. Mọi thao tác của PO (từ dashboard hay CLI) đi qua
`.agent-office/inbox.jsonl`; runner đang chạy sẽ nhận ở bước kế tiếp, nên không ghi đè state của nhau.

## Văn phòng 3D (giai đoạn 3)

Xem thử ngay, không cần `claude`/`codex`, không tốn quota:

```bash
pip install -e './agent-office[dashboard]'
office demo            # tạo repo mẫu ở ~/agent-office-demo, chạy agent mô phỏng, mở /office
```

Trong demo, Claude tách yêu cầu SportsCut thành 5 task, giao cho Codex, Codex code + test rồi
đưa Claude review; một task bị yêu cầu sửa, Codex hết quota giữa chừng và nghỉ, Claude vẫn
làm task khác; cuối cùng mọi task được merge và Claude báo PO là xong.

Với agent thật: `office dashboard` rồi bấm **Văn phòng 3D** (hoặc `office dashboard --page office`).

- Mỗi agent có bàn riêng; màn hình và đèn bàn đổi theo trạng thái (rảnh, đang làm, nghỉ Zzz).
- Mỗi tin nhắn giữa agent là một tờ giấy bay từ bàn người gửi sang bàn người nhận, kèm bong bóng
  thoại; merge thì giấy bay vào server `main`.
- Bảng Kanban trên tường, khung **Hội thoại trong văn phòng** bên phải, ô trả lời khi Claude hỏi.
- Tin nhắn là sự kiện `message` trong `events.jsonl` (`frm`, `to`, `text`, `task_id`, `topic`).

`simulate = true` trong `config.toml` bật agent mô phỏng cho repo bất kỳ (`sim_delay` = số giây mỗi bước).

## Làm song song và rào chắn (giai đoạn 4)

`office run` chạy song song theo số phiên trong `config.toml`:

```toml
[parallel]
claude = 1   # spec, review, kiểm tra mục tiêu
codex = 2    # code + test hai task độc lập cùng lúc, mỗi task một worktree
```

Trong lúc Codex code T-002 và T-004, Claude vẫn viết spec hay review task khác. Thêm phiên
thì nhanh hơn nhưng hết quota sớm hơn; khi một phiên chạm giới hạn, cả agent đó nghỉ, mọi task
dở dang được lưu checkpoint. `office run --sequential` chạy từng bước một như trước.

**Xung đột merge:** khi task khác vừa merge và đụng cùng dòng, task quay về Codex với
`git merge main` đang dở; Codex gỡ xung đột, orchestrator kiểm tra không còn marker, rồi task
đi lại test → review → merge (tối đa 2 lần, sau đó hỏi PO). Nếu `main` đã đổi mà merge vẫn
sạch, orchestrator chạy lại `test_cmd` trên bản đã gộp trước khi merge.

**Rào chắn** (`[guardrails]`):

| Khóa | Mặc định | Tác dụng |
|---|---|---|
| `max_calls_per_day` | `{ claude = 0, codex = 0 }` | Số lượt gọi mỗi agent mỗi ngày (0 = không giới hạn); chạm trần thì nghỉ tới nửa đêm |
| `max_tasks_per_request` | 12 | Số task tối đa Claude được tạo cho một yêu cầu |
| `max_diff_lines` | 4000 | Diff lớn hơn thì dừng và hỏi PO thay vì review |
| `block_secrets` | true | Diff có thứ giống key/token/private key thì dừng task |
| `protected_paths` | `[]` | Đường dẫn agent không được sửa |

**Thống kê:** `office stats` (hoặc `--json`, hoặc `GET /api/stats`) cho biết lượt gọi hôm nay,
số lần hết quota, số phiên đang chạy, số xung đột đã gỡ, số lần rào chắn dừng task. Dashboard
hiện số này trên thẻ từng agent; văn phòng 3D hiện "Codex 2 việc T-002, T-004".

## Chế độ tự động hoàn toàn

- `merge_mode = "auto"` (mặc định): Claude approve và test pass thì task được merge vào
  `base_branch` ngay (PR mode: `gh pr merge --squash`; `open_pr = false`: fast-forward branch local),
  task phụ thuộc chạy tiếp. Đặt `"manual"` để dừng ở PR chờ PO merge như giai đoạn 1.
- Claude PM chỉ hỏi khi yêu cầu thật sự mơ hồ (`{"questions": [...]}` lúc tách task hoặc viết spec).
  Yêu cầu/task đó chuyển `blocked`, các task khác vẫn chạy. Trả lời bằng dashboard hoặc
  `office answer R-001 "..."` / `office answer T-004 "..."`.
- Khi mọi task của một yêu cầu đã merge, Claude kiểm tra repo so với yêu cầu gốc: đủ thì đánh dấu
  yêu cầu `done` kèm tóm tắt, thiếu thì tự tạo task bổ sung. Tối đa `max_goal_rounds` vòng (mặc định 3),
  quá thì hỏi PO.
- `office run --watch` chạy mãi, ngủ khi agent hết quota và nhận yêu cầu mới từ inbox.

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
của task trước. Trước khi merge, orchestrator merge `base_branch` mới nhất vào branch của task;
xung đột thì task bị `blocked`.

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
  agents/       claude.py, codex.py, sim.py (agent mô phỏng cho demo)
  runner_proc.py  bật/tắt `office run --watch` từ dashboard
  stats.py      thống kê lượt gọi, quota, xung đột, rào chắn
  dashboard/    server.py (FastAPI + WebSocket), static/ (HTML/CSS/JS, không cần build;
                office.* = văn phòng 3D, vendor/ = three.js r160)
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
python -m pytest -q        # gồm test chạy song song, rào chắn, dashboard, văn phòng 3D, demo
```

Test dùng `tests/fake_agent.py` thay cho `claude`/`codex`, nên không tốn quota.
