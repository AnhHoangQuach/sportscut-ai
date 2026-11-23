# 9. Vận hành và xử lý sự cố

## Lệnh

| Lệnh | Tác dụng |
|---|---|
| `office init` | Tạo `.agent-office/`, `AGENTS.md`, `CLAUDE.md` |
| `office doctor [--live]` | Kiểm tra git, gh, claude, codex, quy tắc, plugin Superpowers; `--live` thử đăng nhập |
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
| Merge thất bại "uncommitted changes on main" | Có thay đổi chưa commit ở repo chính | Commit hoặc stash ở repo chính |
| Eval làm task quay vòng mãi | Chỉ số dao động ngẫu nhiên | Đặt `max_drop` nhỏ (ví dụ 0.01), cố định seed trong eval |

## Ở đâu có gì

- Log từng lần gọi agent: `.agent-office/logs/<T-xxx hoặc R-xxx>/`
- Log runner khi bật từ dashboard: `.agent-office/logs/runner.log`
- Ghi chú trong worktree: `../<repo>-worktrees/T-xxx/.office/`
- Lịch sử mọi sự kiện: `.agent-office/events.jsonl`
