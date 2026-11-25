# 7. Áp dụng Agent Office cho một dự án khác

Agent Office không gắn với SportsCut. Bất kỳ repo git nào có lệnh test chạy được từ dòng lệnh đều
dùng được: web app, API, thư viện, script dữ liệu, mobile (nếu test chạy được trên máy).

## 7.1 Chuẩn bị máy (một lần)

```bash
pip install -e '/đường/dẫn/agent-office[dashboard]'   # hoặc copy thư mục agent-office/ sang dự án mới
claude          # gõ /login, chọn gói Pro/Max
codex login     # đăng nhập ChatGPT
gh auth login   # nếu muốn mở PR trên GitHub
```

Không đặt `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`. Nếu có, Agent Office tự gỡ khi gọi CLI.

## 7.2 Gắn vào repo mới

```bash
cd ~/du-an-moi            # repo git đã có ít nhất 1 commit trên nhánh chính
office init               # tạo .agent-office/ + AGENTS.md + CLAUDE.md (nếu chưa có)
```

1. **Điền `AGENTS.md` → "Project specifics":** ngôn ngữ, cách cài, lệnh test, lệnh eval (nếu có),
   cấu trúc thư mục, ràng buộc hiệu năng/bảo mật. Đây là thứ cả Claude và Codex đọc mỗi lần.
2. **Sửa `.agent-office/config.toml`:**

```toml
[office]
base_branch = "main"
test_cmd = "npm test"             # lệnh orchestrator tự chạy để xác nhận; nên luôn đặt
setup_cmd = "npm ci"              # chuẩn bị môi trường mỗi worktree, agent tự cài thêm khi thiếu (mục 2.7)
open_pr = true                     # false = merge local, không cần GitHub
merge_mode = "auto"                # "manual" nếu muốn tự bấm merge từng PR
protected_paths = ["AGENTS.md", "CLAUDE.md", ".github/", "infra/"]

[parallel]
pm = 1
lead = 1
dev = 2
tester = 1
claude = 2                         # tổng phiên Claude Code cùng lúc (mọi vai)
codex = 3                          # tổng phiên Codex cùng lúc (mọi vai)

[quality]
eval_cmd = ""                      # có số đo chất lượng thì đặt ở đây (xem 7.4)

[guardrails]
max_calls_per_day = { claude = 0, codex = 0 }
max_diff_lines = 4000
block_secrets = true
```

3. Commit `AGENTS.md`, `CLAUDE.md` (để mọi worktree có), **không** commit `.agent-office/`
   (thêm vào `.gitignore`).
4. Kiểm tra: `office doctor --live` (gửi một prompt nhỏ cho mỗi agent để chắc đăng nhập ổn).

## 7.3 Viết yêu cầu PO tốt

Agent tự làm tới khi xong, nên chất lượng yêu cầu quyết định kết quả. Mẫu:

```markdown
# <Tên tính năng>

<Mục tiêu: ai dùng, để làm gì, khi nào coi là xong>

Đầu ra mong muốn:
- <lệnh/endpoint/màn hình cụ thể>
- <định dạng dữ liệu>

Ràng buộc:
- <công nghệ bắt buộc / cấm>
- <hiệu năng, bảo mật>
- <cách test: dữ liệu giả, không gọi dịch vụ thật>

Tiêu chí đo (nếu là bài toán chất lượng):
- <chỉ số> ≥ <ngưỡng> trên <bộ dữ liệu>
```

```bash
office request -f yeu-cau.md
office dashboard          # bấm "Bắt đầu", xem ở "Văn phòng 3D"
# hoặc chỉ terminal:
office run --watch
```

Claude chỉ hỏi khi thật sự thiếu thông tin; câu hỏi hiện ở dashboard, trả lời ở đó hoặc
`office answer T-003 "..."`.

## 7.4 Khi sản phẩm có "độ chính xác" (AI, tìm kiếm, gợi ý, OCR...)

1. Yêu cầu đầu tiên: **xây bộ đo**. Dữ liệu có nhãn nhỏ trong repo (cho CI) + dữ liệu thật ngoài git,
   một lệnh in JSON (`{"f1": ...}` hoặc `{"accuracy": ...}`, `{"latency_ms": ...}`).
2. Đặt `eval_cmd`, `metric`, `higher_is_better` (false cho chỉ số càng thấp càng tốt như latency).
3. Các yêu cầu sau: mỗi cải tiến phải tăng số; task nào làm số tụt tự quay lại Codex.

## 7.5 Tùy biến cho đội khác

| Tình huống | Làm gì |
|---|---|
| Chỉ có gói Claude, không có Codex | `[roles] dev = "claude"`, `tester = "claude"`: Claude chạy bước dev/test với quyền ghi (`--allowedTools Edit Write Bash`) trong worktree; bốn vai vẫn riêng nhưng chung một quota |
| Repo lớn, test chậm | `test_cmd` chỉ chạy test nhanh; để CI GitHub chạy bộ đầy đủ với `open_pr = true`, `merge_mode = "manual"` |
| Cần người duyệt trước khi merge | `merge_mode = "manual"`: dừng ở PR, `office sync` (hoặc runner) tự nhận biết khi PR đã merge |
| Quota ít | `[parallel] dev = 1` hoặc `codex = 1` (tổng phiên Codex), đặt `max_calls_per_day` (tính theo CLI) |
| Monorepo | Một `.agent-office/` ở gốc; `protected_paths` cho các phần agent không được đụng |
| Muốn thử không tốn quota | `office demo`, hoặc `simulate = true` trong config |

## 7.6 Danh sách kiểm tra bàn giao

- [ ] `office doctor --live` ra `ok` cho git, claude, codex (và gh nếu dùng PR)
- [ ] `AGENTS.md` đã điền "Project specifics" và đã commit
- [ ] `test_cmd` chạy xanh trên nhánh chính
- [ ] `docs/superpowers/` (README, INDEX.md, DECISIONS.md) và `.gitattributes` với `merge=union` đã commit; ghi sẵn các quyết định gốc của PO vào `DECISIONS.md` (task đầu tiên cũng tự tạo nếu thiếu)
- [ ] `protected_paths` gồm file quy tắc, CI, hạ tầng
- [ ] `.agent-office/` trong `.gitignore`
- [ ] (tùy chọn) plugin Superpowers cho Claude, `office doctor` báo `installed`
- [ ] (nếu có số đo) `eval_cmd` in JSON đúng chỉ số
- [ ] Chạy thử một yêu cầu nhỏ (ví dụ "thêm lệnh --version") để thấy cả vòng: spec → code → test → review → merge
