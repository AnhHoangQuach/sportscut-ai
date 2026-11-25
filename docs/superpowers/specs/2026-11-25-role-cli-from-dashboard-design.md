# Design: chọn CLI và model cho từng vai ngay trên dashboard

PO 2026-11-25: "hiện tại đang setting pm claude, tech lead claude, developer codex, tester codex
=> tôi muốn có thể set tuỳ ý từng role dùng model nào trên giao diện luôn được không".

## Đọc yêu cầu

`[roles]` (PR #13) đã cho chọn CLI của từng vai, nhưng chỉ bằng cách sửa `config.toml` rồi chạy lại
`office run`. Model chỉ đặt được theo CLI (`[claude] model`, `[codex] model`), mọi vai trên CLI đó
dùng chung. PO muốn: trên dashboard, mỗi vai (PM, Tech Lead, Developer, Tester) chọn được **CLI**
(claude / codex) và **model** (tuỳ chọn), áp dụng luôn, không phải sửa file hay khởi động lại.

## Hành vi

- Ô "Vai & model" trên dashboard: mỗi vai một dòng, chọn CLI, gõ model (gợi ý `opus`, `sonnet`,
  `haiku` cho Claude; để trống = model mặc định của CLI ở `[claude]`/`[codex] model`), nút **Lưu**.
- `POST /api/roles/{role}` `{"provider": "codex", "model": "gpt-5-codex"}` → lệnh `set_role` qua inbox
  (giống mọi thao tác của PO). Không có runner thì áp dụng ngay; có runner thì runner áp dụng ở vòng
  dispatch kế tiếp (vài giây), **không cần khởi động lại**.
- Lưu bền: `config.toml` vẫn là nơi duy nhất ghi cấu hình. `set_role` sửa đúng dòng `pm = "..."` và
  `pm_model = "..."` trong `[roles]` (thêm dòng nếu thiếu), giữ nguyên chú thích và các mục khác.
  Sửa tay `config.toml` vẫn được, nhưng như trước thì cần chạy lại `office run`.
- Model của vai được truyền cho lần gọi CLI của vai đó (`--model`), thay cho model của CLI. Vai làm
  thay (failover) chạy bằng CLI và model **của chính nó**.
- Bước đang chạy giữ CLI đã bắt đầu. Đổi vai giữa chừng: nếu lần gọi đó hết quota thì CLI cũ (các vai
  còn lại trên nó) nghỉ, vai đã chuyển thì không; lỗi khác chỉ lưu checkpoint, bước sau chạy CLI mới.
- Trạng thái nghỉ đi theo CLI: vai chuyển sang CLI đang nghỉ thì nghỉ cùng (cùng giờ thức); chuyển sang
  CLI đang chạy được thì hết nghỉ.
- Giới hạn `[parallel] claude/codex`, ngân sách ngày, failover tự tính theo CLI mới (đều dựa trên
  `roles_of(provider)`). Cả bốn vai cùng một CLI: không còn vai nào để làm thay, khi CLI nghỉ thì chờ.
- Sự kiện `role_changed` (role, provider, model, from_provider, from_model) và lời nhắn trên bảng tin.
  `/api/state` `roles[]` có `model`, `config.models` có model mặc định của từng CLI; thẻ vai hiện
  `@codex · gpt-5-codex`.

## Acceptance criteria

1. `set_role(office_dir, "pm", "codex", "gpt-5-codex")` đổi `[roles]` trong `config.toml`,
   `load_config` trả `roles["pm"] == "codex"`, `role_models["pm"] == "gpt-5-codex"`; chú thích và các
   mục khác giữ nguyên; role/CLI/model không hợp lệ → `ValueError`, file không đổi.
2. `Office.submit({"cmd": "set_role", ...})` không có runner: áp dụng ngay, vai chạy CLI mới.
3. Runner đang chạy: lệnh trong inbox được áp dụng ở bước kế tiếp, lần gọi sau của vai đi CLI mới với
   `--model` mới, không khởi động lại.
4. Model của vai có trong lệnh CLI của vai đó; vai không đặt model dùng model của CLI.
5. Vai chuyển sang CLI đang nghỉ thì nghỉ cùng; chuyển sang CLI không nghỉ thì hết nghỉ.
6. Đổi vai trong lúc nó đang gọi CLI: hết quota ở lần gọi đó làm CLI cũ nghỉ, không làm CLI mới nghỉ.
7. Dashboard: `POST /api/roles/pm` 200 và `/api/state` thấy CLI + model mới; CLI sai → 400; vai sai → 404.

## Files

`agent-office/agent_office/{config,store,pipeline}.py`, `agents/{claude,codex}.py`,
`dashboard/server.py`, `dashboard/static/{index.html,app.js,style.css}`,
`agent-office/tests/test_role_settings.py`, `agent-office/README.md`, `docs/01`, `docs/06`, `docs/09`.
