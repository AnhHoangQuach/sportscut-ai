# SportsCut v2: highlight bóng đá chính xác cao, đo được bằng số

Làm sau khi bản MVP (`po_request.md`) đã xong. Mục tiêu: highlight chọn ra phải trùng với
những pha mà người xem thật sự coi là hay (bàn thắng, cơ hội lớn, cứu thua, thẻ đỏ...), và
mọi cải tiến phải chứng minh bằng con số, không cảm tính.

## 1. Đo trước, tối ưu sau (task đầu tiên, bắt buộc)

- Lệnh `sportscut eval DIR --json` chạy pipeline trên từng trận trong `DIR` và in một dòng
  JSON: `{"f1", "precision", "recall", "goal_recall", "precision_at_10", "seconds_per_min", "per_match": [...]}`.
- Mỗi trận là một thư mục: `video.mp4` + `labels.json`
  (`[{"start": 1834.0, "end": 1851.0, "type": "goal|chance|save|card|foul|other", "importance": 1-3}]`).
  Hỗ trợ cả `labels.csv` dạng `mm:ss,mm:ss,type` cho dễ ghi nhãn bằng tay, kèm lệnh chuyển đổi.
- So khớp theo sự kiện: một clip dự đoán khớp một nhãn khi IoU thời gian ≥ 0.3 hoặc clip chứa
  trọn khoảnh khắc chính của nhãn; mỗi nhãn chỉ khớp một clip. Từ đó tính precision, recall,
  F1, riêng `goal_recall` cho nhãn `goal`, và precision@10.
- Bộ eval tổng hợp trong `tests/fixtures/eval/`, sinh bằng script ffmpeg (tiếng ồn khán giả
  nổi lên, tiếng còi, chuyển cảnh, replay quay chậm, bảng tỉ số đổi số), có nhãn biết trước.
  CI chạy eval trên bộ này. Không commit video thật.
- Ghi điểm của bản MVP hiện tại làm mốc (baseline) trong README.
- Sau task này, cấu hình `eval_cmd = "sportscut eval tests/fixtures/eval --json"` trong
  `.agent-office/config.toml` để mọi task sau không được làm tụt F1.

## 2. Pipeline đa tín hiệu (mỗi tín hiệu là một task, có điểm trước/sau)

1. **Âm thanh tốt hơn RMS:** nền thích nghi (median trượt) để sân ồn cả trận vẫn bắt được
   đỉnh; spectral flux và năng lượng dải cao cho tiếng hò reo; phát hiện tiếng còi (âm tần
   2–4 kHz); độ cao giọng bình luận viên.
2. **Cảnh quay:** phát hiện chuyển cảnh (PySceneDetect hoặc ffmpeg `select=scene`); phát hiện
   **replay** (hiệu ứng chuyển/logo replay, đoạn quay chậm) vì đài thường chiếu lại ngay sau pha
   hay; tỉ lệ cận cảnh (ăn mừng, cầu thủ).
3. **Bảng tỉ số (OCR):** tự tìm vùng bảng tỉ số (vùng chữ đứng yên), OCR 1–2 giây một lần;
   tỉ số đổi = bàn thắng, lùi lại để lấy đúng khoảnh khắc ghi bàn. Đây là tín hiệu chính xác
   nhất cho bàn thắng.
4. **Tổng hợp điểm:** mỗi giây một vector đặc trưng, học trọng số trên phần dev của bộ nhãn
   (ví dụ logistic regression), chọn đỉnh + loại trùng, ưu tiên bàn thắng; eval in thêm bảng
   ablation (bỏ từng tín hiệu thì F1 còn bao nhiêu).
5. **Biên clip:** bắt đầu/kết thúc bám theo chuyển cảnh, có đoạn dẫn trước pha bóng, không cắt
   giữa câu bình luận.
6. **Thị giác (tùy chọn, làm sau cùng và chỉ khi các bước trên chưa đạt mục tiêu):** YOLO
   phát hiện bóng/khung thành chỉ trên các cửa sổ ứng viên, cài qua extra `sportscut[vision]`.

## 3. Mục tiêu

- Trên bộ trận thật của tôi (`data/eval/`): F1 ≥ 0.75, `goal_recall` ≥ 0.95, precision@10 ≥ 0.8.
- Trên bộ tổng hợp trong CI: F1 ≥ 0.9.
- Tốc độ: trận 90 phút xử lý dưới 10 phút trên CPU laptop; OCR/vision phải lấy mẫu thưa,
  không chạy mọi khung hình. Model nặng là extra tùy chọn, bản cơ bản vẫn chạy chỉ với ffmpeg.

## 4. Ràng buộc

- Mỗi task một PR nhỏ, ghi rõ F1 trước và sau trong mô tả PR.
- Tín hiệu mới mà không làm tăng F1 (hoặc goal_recall) trên bộ dev thì không merge.
- Không commit video, model weights hay dữ liệu có bản quyền; tải model qua lệnh riêng.
