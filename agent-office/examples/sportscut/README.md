# Ví dụ: Agent Office xây SportsCut

Repo `sportscut-ai` chứa cả orchestrator (`agent-office/`) lẫn sản phẩm. Các bước chạy nằm ở
README gốc của repo. Điểm quan trọng: đặt `protected_paths = ["agent-office/"]` để agent chỉ
sửa code sản phẩm; task nào đụng vào `agent-office/` sẽ bị chuyển `blocked`.

Yêu cầu PO mẫu: [po_request.md](po_request.md).

Backlog dự kiến Claude PM sẽ tách ra (có thể khác):

1. Khởi tạo project Python + CLI + pytest, kiểm tra ffmpeg
2. Đọc metadata và tách audio bằng ffmpeg
3. Chấm điểm "phấn khích" theo audio (RMS mỗi giây, z-score, tìm đỉnh)
4. Phát hiện chuyển cảnh để bắt biên clip
5. Chọn highlight (top N, khoảng cách tối thiểu, đệm 8s trước / 4s sau)
6. Xuất clip, video ghép, manifest JSON
