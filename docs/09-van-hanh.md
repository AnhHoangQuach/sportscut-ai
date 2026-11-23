# 9. Vận hành và xử lý sự cố

## Lệnh

| Lệnh | Tác dụng |
|---|---|
| `office init` | Tạo `.agent-office/`, `AGENTS.md`, `CLAUDE.md` |
| `office doctor [--live]` | Kiểm tra git, claude, codex, quy tắc, plugin Superpowers và GitHub (remote, mạng tới api.github.com, `gh` đăng nhập tài khoản nào, có quyền ghi repo không) kèm lệnh sửa; `--live` thử đăng nhập agent |
| `office request "..."` / `-f file.md` | Thêm yêu cầu PO |
| `office triage` | Giao lại cho Tech Lead mọi task/yêu cầu đang chờ PO vì lý do kỹ thuật (tự chạy mỗi lần office khởi động) |
| `office run [--watch] [--sequential] [--once] [--no-wait]` | Chạy văn phòng; `--watch` chạy mãi, chờ việc mới |
| `office dashboard [--page office]` | Mở dashboard (hoặc thẳng văn phòng 3D) tại `http://127.0.0.1:8765` |
| `office demo` | Văn phòng mô phỏng, không tốn quota |
| `office status` / `board` / `show T-003` | Xem trạng thái, Kanban, chi tiết task |
| `office answer T-003 "..."` / `office answer R-001 "..."` | Trả lời câu hỏi của Claude |
| `office wake codex` | Cho agent làm lại ngay (bỏ qua giờ nghỉ) |
| `office stats [--json]` | Lượt gọi, quota, xung đột, rào chắn, lịch sử điểm eval |
| `office sync` | Nhận biết PR đã được merge tay |

## Sự cố thường gặp

| Hiện tượng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `0 step(s) done` | Chưa có yêu cầu nào | `office request ...` rồi chạy lại |
| Văn phòng 3D đứng yên | Runner chưa chạy, hoặc agent đều đang nghỉ / chờ PO | Bấm "Bắt đầu"; xem khung "Cần anh trả lời"; `office status` để thấy lý do chờ |
| Agent "nghỉ" liên tục | Hết quota thật, hoặc CLI lỗi lặp lại (chưa đăng nhập, sai lệnh) | Xem `.agent-office/logs/<task>/...log`; `office doctor --live` |
| Task `blocked` | Chỉ còn một lý do: câu hỏi **nghiệp vụ** cho PO (Tech Lead đã lọc). Vướng kỹ thuật (rào chắn, hết lượt test/review/xung đột, thiếu thư viện) do Tech Lead tự xử lý, task hiện nhãn "Tech Lead xử lý" | `office show T-xxx` xem câu hỏi; trả lời bằng `office answer`. Task bị "gác lại" thì xem dòng `Tech Lead` trong `docs/superpowers/DECISIONS.md` |
| Task `blocked` vì thiếu thư viện/tool | Đã thử `dep_retries` lần mà vẫn thiếu; `setup_cmd` lỗi; tool hệ thống (ffmpeg) chưa có | Xem mục `ENVIRONMENT` trong log dev; sửa `setup_cmd` hoặc cài tool trên máy; `office answer T-xxx "đã cài"` (xem [2.7](02-quota-song-song-rao-chan.md#27-agent-tự-cài-dependency-khi-thiếu)) |
| "Another `office run` is already working" | Đã có runner khác | Dừng runner kia (nút "Dừng" hoặc Ctrl+C); file `runner.pid` cũ tự bị bỏ qua nếu tiến trình đã chết |
| Task `blocked` "environment problem for the user", tin "Cần anh sửa trên máy" | Duyệt xong nhưng `git push` / `gh pr create` / `gh pr merge` bị GitHub từ chối: `gh` chưa đăng nhập hoặc token hết hạn, tài khoản `gh` không có quyền ghi repo (đăng nhập nhầm tài khoản), `GH_TOKEN` cũ ghi đè, hoặc mất mạng lâu | Chạy `office doctor` (xem [9.1](#91-office-không-tạo-được-pr--merge)), làm theo dòng `->`; office tự kiểm tra lại mỗi 5 phút và tạo PR / merge tiếp, không cần `office answer` |
| Merge thất bại "uncommitted changes on main" | Có thay đổi chưa commit ở repo chính | Commit hoặc stash ở repo chính |
| Eval làm task quay vòng mãi | Chỉ số dao động ngẫu nhiên | Đặt `max_drop` nhỏ (ví dụ 0.01), cố định seed trong eval |

## 9.1 Office không tạo được PR / merge

`git push`, `gh pr create`, `gh pr merge` luôn chạy **trong chính tiến trình office** (không
trong sandbox của Claude hay Codex), dùng đăng nhập `gh`, keychain, `GH_TOKEN` và mạng của
chính shell đã chạy `office run`. Office gọi `gh` kèm `-R owner/repo` lấy từ remote (`origin`),
nên `gh` không đoán nhầm repo khi có fork hay nhiều remote.

Khi GitHub từ chối, office phân loại lỗi:

| Loại | Office làm gì |
|---|---|
| Đăng nhập (`gh auth login`, HTTP 401, token hết hạn) | Chạy kiểm tra GitHub, chặn task với nhãn "environment problem for the user", nhắn anh lệnh cần chạy. Không gọi Tech Lead |
| Quyền (HTTP 403, "must be a collaborator", "Permission to ... denied") | Như trên, nêu rõ `gh` đang đăng nhập tài khoản nào và repo của ai |
| Mạng (không phân giải được tên, timeout, connection refused) | Thử lại sau 2, 5, 10, 15 phút; vẫn lỗi thì báo như trên |
| Lỗi khác (PR không merge được do branch protection, ...) | Giao Tech Lead như trước |

Sau khi anh sửa trên máy, office tự kiểm tra lại mỗi 5 phút và đưa task về bước PR. Tech Lead
chạy trong sandbox không có mạng / không có đăng nhập GitHub, nên lỗi `gh` mà nó tự thấy không
nói gì về máy anh; vì thế những lỗi này không còn giao cho Tech Lead "chờ 60 phút".

Lệnh thường dùng trên máy (chạy trong Terminal thường, cùng shell sẽ chạy `office run`):

```sh
gh auth status                       # đang đăng nhập tài khoản nào, token còn hạn không
gh auth login --hostname github.com --git-protocol https --web
gh auth switch --user <chủ-repo>     # nếu đã đăng nhập nhiều tài khoản
gh auth setup-git                    # git push dùng cùng đăng nhập với gh
unset GH_TOKEN GITHUB_TOKEN          # nếu biến cũ ghi đè đăng nhập
gh api repos/<owner>/<repo> --jq .permissions   # cần push: true
office doctor                        # phần "GitHub" phải toàn ok
```

Đừng chạy `office run` từ bên trong một phiên Claude Code / Codex (sandbox chặn mạng và
keychain); hãy chạy trong Terminal hoặc bằng nút "Bắt đầu" trên dashboard.

## Ở đâu có gì

- Log từng lần gọi agent: `.agent-office/logs/<T-xxx hoặc R-xxx>/`
- Log runner khi bật từ dashboard: `.agent-office/logs/runner.log`
- Ghi chú trong worktree: `../<repo>-worktrees/T-xxx/.office/`
- Lịch sử mọi sự kiện: `.agent-office/events.jsonl`
