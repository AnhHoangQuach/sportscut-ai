# 8. Công nghệ sử dụng

## Điều phối agent

| Công nghệ | Dùng để | Vì sao chọn |
|---|---|---|
| Claude Code CLI (`claude -p`) | PM, Tech Lead, Reviewer | Headless, dùng gói Pro/Max, giới hạn công cụ bằng `--allowedTools`, đầu ra JSON |
| Codex CLI (`codex exec`) | Developer, Tester | Headless, dùng gói ChatGPT, sandbox `workspace-write`, ghi câu trả lời cuối ra file |
| Python 3.11+ (thư viện chuẩn) | Orchestrator | `subprocess`, `tomllib`, `dataclasses`, `concurrent.futures`, `threading`; không phụ thuộc ngoài |
| git worktree | Mỗi task một thư mục + nhánh | Song song không giẫm chân, dùng chung lịch sử, dọn dễ |
| GitHub CLI `gh` | Mở và merge PR (tùy chọn) | Dùng đăng nhập sẵn có, không cần token trong config |
| JSON + JSONL trên đĩa | State, sự kiện, inbox | Ghi nguyên tử, đọc được bằng mắt, không cần database |
| `tzdata` (Windows) | Đọc giờ reset có múi giờ | Windows không có sẵn cơ sở dữ liệu múi giờ |
| Superpowers (tùy chọn) | Skill quy trình cho Claude | Kỷ luật TDD, debug, plan, review; quy tắc cũng được nhúng sẵn trong prompt |

## Giao diện

| Công nghệ | Dùng để |
|---|---|
| FastAPI + Uvicorn (extra `[dashboard]`) | REST API + WebSocket `/ws` |
| HTML/CSS/JS thuần | Dashboard 2D, không build, chạy offline |
| three.js r160 (vendored) + OrbitControls | Văn phòng 3D, nạp bằng import map |
| Canvas 2D → `CanvasTexture` | Màn hình máy tính, bảng Kanban trên tường |
| HTML overlay chiếu từ 3D | Nhãn tên, bong bóng thoại, Zzz, nhãn giấy bay |
| Playwright + Chromium | Chụp màn hình kiểm tra giao diện (khi phát triển) |

## Sản phẩm SportsCut

| Công nghệ | Dùng để |
|---|---|
| ffmpeg / ffprobe | Đọc metadata, tách audio, phát hiện cảnh, cắt và ghép clip, sinh video tổng hợp cho test |
| numpy | Đặc trưng âm thanh theo giây (RMS, z-score, spectral flux), chọn đỉnh |
| PySceneDetect (tùy chọn) | Phát hiện chuyển cảnh chính xác hơn |
| Tesseract / EasyOCR (extra tùy chọn) | Đọc bảng tỉ số để bắt bàn thắng |
| scikit-learn (tùy chọn) | Học trọng số tổng hợp tín hiệu (logistic regression) |
| YOLO (extra `vision`, tùy chọn) | Phát hiện bóng/khung thành trên cửa sổ ứng viên |
| pytest | Test, chạy cả trong CI |

## CI

| Công nghệ | Dùng để |
|---|---|
| GitHub Actions (`.github/workflows/agent-office.yml`) | Chạy test orchestrator khi `agent-office/` đổi |
| GitGuardian (GitHub App) | Quét secret trên mỗi PR |
