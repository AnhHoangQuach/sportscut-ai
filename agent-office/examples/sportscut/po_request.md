# SportsCut MVP: tự động cắt highlight trận bóng đá

Tôi cần một CLI Python `sportscut cut match.mp4` tự tìm khoảnh khắc hay trong video
bóng đá và xuất:

- tối đa 10 clip highlight, mỗi clip 10–30 giây, đặt tên theo thứ tự thời gian;
- một file `highlights.mp4` ghép các clip lại;
- một file `highlights.json` liệt kê từng clip: start, end, score, lý do chọn.

Ràng buộc:

- Chỉ dùng tín hiệu rẻ trước: độ ồn khán giả/bình luận viên (audio) và chuyển cảnh.
  Chưa dùng model ML.
- Dùng ffmpeg (cài sẵn trên máy). Thiếu ffmpeg thì báo lỗi rõ ràng.
- Video 90 phút xử lý xong dưới 10 phút trên laptop.
- Có tùy chọn `--top N`, `--min-len`, `--max-len`, `--out DIR`.
- Test tự động dùng video/audio tổng hợp sinh bằng ffmpeg, không commit video thật.
