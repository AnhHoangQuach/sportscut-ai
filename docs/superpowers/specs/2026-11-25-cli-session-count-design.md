# Design: số phiên Claude Code / Codex chạy cùng lúc

PO 2026-11-25: "tôi muốn thêm setting là bao nhiêu claude code, bao nhiêu codex code nữa".

## Đọc yêu cầu

`[parallel]` đã có số phiên **từng vai** (`pm`, `lead`, `dev`, `tester`). PO muốn đặt thêm số phiên
**từng CLI**: tối đa bao nhiêu `claude` và bao nhiêu `codex` chạy cùng một lúc, mọi vai cộng lại.

## Hành vi

- `[parallel] claude = N`, `codex = M` (mặc định 2 và 3, bằng tổng các vai mặc định, nên office chạy
  như cũ). 0 hoặc không có dòng = không giới hạn thêm.
- Một bước chỉ bắt đầu khi vai còn phiên trống **và** CLI chạy bước đó còn phiên trống.
- Phiên tiếp quản tính cho CLI thực sự chạy nó (PM làm thay Dev = một phiên Claude).
- Config cũ chỉ có `claude`/`codex`: vẫn là số phiên của từng vai trên CLI đó (như trước) và giờ
  cũng là tổng phiên của CLI.
- Vai còn phiên nhưng CLI đã đủ: `slots_idle` + console ghi `codex 2/2 sessions in use ([parallel] codex = 2)`;
  lý do chờ của task ghi `waits for dev (all [parallel] codex sessions busy)`.
- Hiển thị: dòng `Parallel mode: ... (at most claude 2, codex 3 at once)`, sự kiện `runner_started`
  có `cli_parallel`, `/api/state` config có `cli_parallel`, thẻ vai trên dashboard `codex: x/M phiên`,
  `office stats` / `/api/stats` có `providers.<cli>.sessions` và `max_sessions`.

## Acceptance criteria

1. `load_config` trả `cli_parallel == {"claude": 2, "codex": 3}` với config mặc định; dòng thiếu = 0.
2. `plan_steps(..., cli_slots={"codex": 2})` không bao giờ chọn quá 2 bước của vai Codex.
3. Phiên tiếp quản trừ vào phiên của CLI chạy nó.
4. `dispatch` không khởi động thêm bước khi CLI đã đủ phiên và nói lý do trong `slots_idle`.
5. Chạy song song mô phỏng với `codex = 1` hoàn tất mà không lúc nào có hơn 1 phiên Codex.
6. Thống kê có `sessions`/`max_sessions` theo CLI.

## Files

`agent-office/agent_office/{config,scheduler,pipeline,cli,stats}.py`, `dashboard/server.py`,
`dashboard/static/app.js`, `agent-office/tests/test_cli_sessions.py`, `agent-office/tests/test_roles.py`,
`agent-office/README.md`, `docs/01`, `docs/02` (2.2), `docs/06`, `docs/07`.
