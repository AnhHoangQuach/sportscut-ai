# Ví dụ: Agent Office xây SportsCut

Repo `sportscut-ai` chứa cả orchestrator (`agent-office/`) lẫn sản phẩm. Các bước chạy nằm ở
README gốc của repo. Điểm quan trọng: đặt `protected_paths = ["agent-office/"]` để agent chỉ
sửa code sản phẩm; task nào đụng vào `agent-office/` sẽ bị chuyển `blocked`.

Yêu cầu PO mẫu: [po_request.md](po_request.md) (MVP), rồi
[po_request_accuracy.md](po_request_accuracy.md) (độ chính xác cao, đo bằng F1).

Sau khi task "eval" của yêu cầu thứ hai được merge, bật cổng chất lượng trong
`.agent-office/config.toml`:

```toml
[quality]
eval_cmd = "sportscut eval tests/fixtures/eval --json"
metric = "f1"
```

Từ đó task nào làm F1 thấp hơn bản đang có trên `main` sẽ bị trả về Codex để sửa.

Để có số đo thật, anh đặt 3–5 trận (video anh có quyền dùng) vào `data/eval/<tên trận>/video.mp4`
kèm `labels.csv` (`mm:ss,mm:ss,type`, ví dụ `30:34,30:51,goal`). Thư mục `data/` không vào git.

Backlog MVP dự kiến (Claude PM có thể tách khác):

1. Khởi tạo project Python + CLI + pytest, kiểm tra ffmpeg
2. Đọc metadata và tách audio bằng ffmpeg
3. Chấm điểm "phấn khích" theo audio (RMS mỗi giây, z-score, tìm đỉnh)
4. Phát hiện chuyển cảnh để bắt biên clip
5. Chọn highlight (top N, khoảng cách tối thiểu, đệm 8s trước / 4s sau)
6. Xuất clip, video ghép, manifest JSON
