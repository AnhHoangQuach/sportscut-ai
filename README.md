# SportsCut AI

Tự động cắt highlight từ video thể thao, bắt đầu với bóng đá. Code sản phẩm được một
"văn phòng" AI xây dựng: Claude (PM, Tech Lead, Reviewer) và Codex (Developer, Tester),
còn Hoang là Product Owner.

| Thư mục | Nội dung |
| --- | --- |
| `agent-office/` | Orchestrator `office`: điều phối Claude + Codex, worktree mỗi task, review, PR |
| `sportscut/`, `tests/` | Sản phẩm cắt highlight (do văn phòng xây qua các PR sau) |

## Chạy văn phòng trên chính repo này

```bash
git clone https://github.com/AnhHoangQuach/sportscut-ai && cd sportscut-ai
pip install -e ./agent-office         # lệnh `office`, cần Python 3.11+
claude        # /login bằng gói Pro/Max (một lần)
codex login   # đăng nhập bằng ChatGPT (một lần)

office init                           # tạo .agent-office/ (đã gitignore)
```

Sửa `.agent-office/config.toml` cho repo này:

```toml
[office]
base_branch = "main"
test_cmd = "python -m pytest -q tests"
protected_paths = ["agent-office/", "AGENTS.md", "CLAUDE.md"]   # agent không sửa orchestrator và quy tắc
merge_mode = "auto"                   # review đạt + test pass thì tự merge vào main
```

Rồi:

```bash
office doctor --live
pip install -e './agent-office[dashboard]'
office dashboard     # gửi yêu cầu, bấm Bắt đầu, trả lời khi Claude hỏi; nút "Văn phòng 3D"
office demo          # xem các agent phối hợp bằng agent mô phỏng, không tốn quota
```

Hoặc chỉ dùng terminal: `office request -f agent-office/examples/sportscut/po_request.md`
rồi `office run --watch`.

Khi MVP xong, giao yêu cầu thứ hai để tăng độ chính xác bằng số đo (F1 trên bộ nhãn):
`office request -f agent-office/examples/sportscut/po_request_accuracy.md`. Quy tắc làm việc
chung của các agent (TDD, đo trước tối ưu sau, có bằng chứng mới báo xong) ở [AGENTS.md](AGENTS.md).

Tài liệu đầy đủ (kiến trúc multi-agent, code, văn phòng 3D, công nghệ SportsCut, áp dụng cho dự án khác): [docs/](docs/README.md).

Chi tiết: [agent-office/README.md](agent-office/README.md).

## Bình luận AI: đo chất lượng tiêu đề, caption, hashtag (eval-meta)

```bash
python -m sportscut eval-meta tests/fixtures/eval_meta --json
```

Mỗi ca trong `cases.json` gồm `facts`, các nhóm `must_mention` (chỉ cần khớp một
giá trị trong mỗi nhóm) và danh sách `forbidden`. Tiêu đề phải dài 10–80 ký tự,
caption tối đa 300 ký tự, và có 3–8 hashtag ASCII duy nhất. Điểm ca bằng
`fact_recall` khi đúng định dạng, không bị phát hiện bịa số/tên cấm và đạt
heuristic tiếng Việt; nếu không thì bằng 0.

Baseline template đo trong T-023:

```json
{"score": 1.0, "format_ok": 1.0, "fact_recall": 1.0, "hallucination_rate": 0.0, "vi_rate": 1.0}
```

Mọi PR thuộc R-005 phải báo cáo điểm này và điểm không được giảm.

## Theo dõi cầu thủ: đo độ chính xác (eval-player)

Tạo bộ video tổng hợp và chạy phép đo:

```bash
python tests/fixtures/eval_player/build.py
python -m sportscut eval-player tests/fixtures/eval_player --json
```

Mỗi ca có dạng `<thư-mục>/<tên-ca>/{clip.mp4,labels.json}`. Nhãn chứa `players`
(tùy chọn) và `touches`, ví dụ `{"players":[{"team":"red","number":10}],
"touches":[{"t":3.0,"team":"red","number":10}]}`. Video thật dùng cùng định dạng
tại `data/eval_player/<name>/{clip.mp4,labels.json}`. Một dự đoán khớp khi cách nhãn
không quá ±0.5 giây; phép khớp là một-một.

Baseline đo trong T-029:

```json
{"f1": 0.0, "precision": 0.0, "recall": 0.0, "touch_f1_any": 0.0, "team_accuracy": null, "id_accuracy": null, "seconds_per_min": 0.0, "per_clip": [{"clip": "dribble", "duration": 20.0, "touches": 13, "queries": 4, "f1": 0.0, "precision": 0.0, "recall": 0.0, "touch_f1_any": 0.0, "team_accuracy": null, "id_accuracy": null, "seconds_per_min": 0.0}, {"clip": "near_miss", "duration": 20.0, "touches": 6, "queries": 5, "f1": 0.0, "precision": 0.0, "recall": 0.0, "touch_f1_any": 0.0, "team_accuracy": null, "id_accuracy": null, "seconds_per_min": 0.0}, {"clip": "number_hidden", "duration": 20.0, "touches": 8, "queries": 3, "f1": 0.0, "precision": 0.0, "recall": 0.0, "touch_f1_any": 0.0, "team_accuracy": null, "id_accuracy": null, "seconds_per_min": 0.0}, {"clip": "short_passes", "duration": 24.0, "touches": 12, "queries": 6, "f1": 0.0, "precision": 0.0, "recall": 0.0, "touch_f1_any": 0.0, "team_accuracy": null, "id_accuracy": null, "seconds_per_min": 0.0}]}
```

Mục tiêu tiếp theo: `touch_f1_any ≥ 0.9` (T-031), `team_accuracy ≥ 0.95`
(T-032), và `F1 ≥ 0.85` (T-033).

## Theo dõi cầu thủ: xuất video tổng hợp (player)

```bash
python -m sportscut player match.mp4 --team red --number 10 --out reel
```

Mỗi pha chạm được lấy thêm 3 giây trước và 2 giây sau; các đoạn cách nhau dưới
4 giây được gộp. Có thể đổi các giá trị mặc định bằng `--pre`, `--post` và
`--merge-gap`. Thư mục đầu ra chứa `player_red_10.mp4` và `player.json`; nếu
không có pha chạm thì chỉ có manifest. Việc phát hiện pha chạm vẫn là stub cho
đến khi T-031..T-033 hoàn thành.

## API HTTP

Cài phần phụ thuộc API và chạy server cục bộ:

```bash
pip install -e '.[api]'
pip install -e '.[api,youtube]'
sportscut serve --host 127.0.0.1 --port 8000
```

Gửi video và tải một clip từ URL trong kết quả:

```bash
curl -F file=@match.mp4 -F top=5 -F min_len=10 -F max_len=30 \
  http://127.0.0.1:8000/highlights
curl -F url=https://www.youtube.com/watch?v=VIDEO_ID \
  http://127.0.0.1:8000/highlights
curl -o clip_01.mp4 "<clip_url>"
```

Phản hồi có dạng `{"job_id":"...","source_name":"match.mp4","source_url":null,
"duration":90,"highlights":[{"start":12,"end":24,
"score":4.2,"reason":"audio peak z=4.2","clip_url":"http://127.0.0.1:8000/
highlights/.../clips/clip_01.mp4"}]}`. `SPORTSCUT_DATA_DIR` chọn thư mục dữ liệu
(mặc định `./sportscut-data`), còn `SPORTSCUT_MAX_UPLOAD_BYTES` đặt giới hạn
upload (mặc định 2 GiB). API dùng mã 400 cho video đầu vào không hợp lệ, 404 cho
clip không tồn tại, 413 cho upload quá lớn, 422 cho tham số sai và 500 khi xử lý
phía server thất bại.

Liên kết chỉ được phép trỏ tới một video trên youtube.com, www.youtube.com,
m.youtube.com hoặc youtu.be, dài tối đa 3 giờ; video được tải dưới dạng MP4 tối
đa 720p và 2 GiB. `file` và `url` loại trừ lẫn nhau. API trả mã 400 khi liên kết
không hợp lệ hoặc tải thất bại. Người gửi liên kết chịu trách nhiệm bảo đảm mình
có quyền sử dụng video đó.

Đọc lại job và phát nguồn gốc có hỗ trợ HTTP Range (để tua trong thẻ `<video>`):

```bash
curl http://127.0.0.1:8000/highlights/JOB_ID
curl -H 'Range: bytes=0-1048575' \
  http://127.0.0.1:8000/highlights/JOB_ID/source -o source-part.mp4
```

Chỉnh thủ công bằng `PUT` với toàn bộ danh sách đoạn thay thế:

```bash
curl -X PUT -H 'Content-Type: application/json' \
  -d '{"segments":[{"start":12.5,"end":24,"reason":"manual goal"}]}' \
  http://127.0.0.1:8000/highlights/JOB_ID/segments
```

Mỗi lần `PUT` thay thế hoàn toàn danh sách cũ (danh sách rỗng cũng hợp lệ), nhận tối
đa 50 đoạn và không có lịch sử hoàn tác. Clip mới dùng tên có phiên bản để trình
duyệt không phát lại bản đã cache.

Hiện việc xử lý diễn ra đồng bộ, chưa có xác thực, các thư mục job thành công
không tự xóa, và server mặc định chỉ lắng nghe trên localhost.

## Trang web: tải lên, xem trước và chỉnh mốc cắt

```bash
pip install -e '.[api,youtube]'
sportscut serve
```

1. Mở `http://127.0.0.1:8000/`.
2. Chọn một tệp hoặc dán liên kết YouTube rồi nhấn "Tạo highlight".
3. Trang sẽ chuyển tới `http://127.0.0.1:8000/jobs/JOB_ID`.
4. Nhấn "▶ Đoạn N" để phát một đoạn.
5. Nhập mốc đầu hoặc cuối theo `mm:ss.s` (cũng nhận số giây như `75.5`), hoặc
   dùng "Đầu/Cuối = hiện tại" và các nút ±0.5 s.
6. Nhấn "Xóa" để xóa một đoạn.
7. Nhấn "Thêm đoạn tại thời điểm hiện tại" để thêm một đoạn 10 giây.
8. Nhấn "Lưu" để cắt lại toàn bộ clip. Mỗi lần lưu thay thế cả danh sách, không
   có hoàn tác và các liên kết clip cũ sẽ ngừng hoạt động.

Trang trả về lỗi 404 nếu `JOB_ID` không tồn tại.
