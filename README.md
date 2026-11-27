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

### Backend LLM (tùy chọn)

Mặc định metadata do template offline tạo ra (miễn phí, không cần mạng). Để Claude viết:
```bash
pip install 'sportscut[llm]'
export ANTHROPIC_API_KEY=...   # chỉ đọc từ biến môi trường, không bao giờ lưu hay ghi log
python -m sportscut eval-meta tests/fixtures/eval_meta --json --meta-backend llm
```

Model mặc định `claude-haiku-5-5`, đổi bằng `SPORTSCUT_LLM_MODEL`. Mỗi trận gửi một request. Clip
nào sai luật eval-meta (định dạng, số/tên ngoài facts, tiếng Việt, thiếu facts), thiếu key, thiếu gói
hoặc lỗi mạng thì dùng template và in cảnh báo `template fallback` ra stderr.
Kết quả chạy thật (T-025): LIVE EVAL NOT RUN: no ANTHROPIC_API_KEY.

### Kịch bản bình luận có mốc thời gian (eval-meta --script, cut --voiceover)

Mỗi clip có 1–3 câu bình luận tiếng Việt đặt quanh khoảnh khắc sự kiện, tức đỉnh âm thanh
trong clip: câu bối cảnh (phút, hai đội, giải) trước đỉnh, câu nêu sự kiện bắt đầu đúng tại đỉnh,
câu tỉ số sau đỉnh. Độ dài ước theo 3,5 âm tiết/giây (mỗi từ tiếng Việt và mỗi chữ số là một âm
tiết), chừa 0,25 s đầu và cuối clip. `script_fits` kiểm tra lời đọc nằm trong clip và các câu không
chồng nhau. Template và backend LLM đều qua cùng một bước kiểm tra; câu LLM sai luật thì dùng template.

```bash
python -m sportscut eval-meta tests/fixtures/eval_meta --json --script
```

Kết quả đo trong T-026 (template, mỗi ca ở clip 10 s và 30 s):

```json
{"score": 1.0, "script_fits": 1.0, "fact_recall": 1.0, "hallucination_rate": 0.0, "vi_rate": 1.0}
```

`sportscut cut VIDEO --out OUT --voiceover` ghi thêm `OUT/clip_NN.script.json` cho mỗi clip
(`clip`, `clip_len`, `peak`, `backend`, `lines` với `start`/`end`/`text`). Âm thanh lồng tiếng sẽ có
ở task sau.
Từ T-027 đã có âm thanh lồng tiếng: xem mục kế tiếp.

### Lồng tiếng bình luận (--voiceover)

Kịch bản trên được đọc thành giọng tiếng Việt bằng Piper, chạy offline trên CPU, rồi trộn vào clip.
Âm thanh gốc được hạ khoảng 12 dB trong lúc có lời bình (thêm 0,15 s trước và sau mỗi câu), ngoài
khoảng đó giữ nguyên. Câu nào đọc dài hơn dự kiến thì câu sau được lùi lại để không chồng nhau; phần
vượt quá cuối clip bị bỏ.

```bash
pip install 'sportscut[tts]'
sportscut download-models --tts
sportscut cut match.mp4 --out out --voiceover --vertical
```

Kết quả là `out/clip_NN.vo.mp4`, và `out/vertical/clip_NN.vo.mp4` khi có `--vertical`; manifest
`highlights.json` ghi thêm `voiceover_file` và `vertical_voiceover_file`. Clip gốc `clip_NN.mp4`
không bị thay đổi. Giọng `vi_VN-vais1000-medium` được tải một lần vào `~/.cache/sportscut/piper`
(hoặc `$XDG_CACHE_HOME/sportscut/piper`), lần chạy `cut` đầu tiên tự tải nếu chưa có; file giọng
không bao giờ được commit vào repo. Không cài extra thì `--voiceover` chỉ ghi kịch bản và in hướng
dẫn cài đặt ra stderr. Lưu ý: piper-tts dùng giấy phép GPL-3.0; người dùng tự cài nó như một extra
tùy chọn, SportsCut không đóng gói kèm.

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

## Phát hiện chạm bóng (T-031)

`detect_touches` giờ tìm các lần chạm bóng của **bất kỳ cầu thủ nào**. Mỗi video được đọc ở 5 khung/giây,
thu về rộng 320 px, rồi dùng lại bộ dò bóng và mặt nạ sân của camera bám bóng (`reframe.py`). Một lần chạm
là lúc quả bóng **đổi hướng hoặc đổi tốc độ** rõ rệt (và vẫn tiếp tục lăn) khi nằm sát một khối cầu thủ
(vùng không phải màu cỏ bên trong sân). Các ứng viên cách nhau dưới 0,4 giây được gộp lại, giữ lần mạnh nhất.

- Bóng lăn ngang qua cầu thủ mà không đổi hướng/tốc độ (tình huống "suýt chạm") **không** tính là chạm.
- Bóng dừng hẳn cạnh chân cầu thủ không tính là chạm; lần chạm tiếp theo của người nhận mới được tính.
- Cảnh cận (close-up) không thấy sân thì không có ứng viên nào.
- Ứng viên chưa có đội và số áo (`team`/`number` là `null`), nên `find_touches` và lệnh `sportscut player`
  vẫn chưa trả về gì cho tới khi T-032/T-033 xong.

Xem các ứng viên của từng clip (khoá `candidates` trong mỗi mục `per_clip`):

```bash
python -m sportscut eval-player tests/fixtures/eval_player --json --debug
```

Các hằng số đã chỉnh (trong `sportscut/player.py`):

```text
KICK_SPAN = 1         # số mẫu trước/sau dùng để tính vận tốc bóng
TURN_DEG = 20.0       # góc đổi hướng tối thiểu, độ
SPEED_JUMP = 0.75     # thay đổi tốc độ tương đối tối thiểu
MIN_SPEED = 0.015     # tốc độ tối thiểu khi bóng rời chân, phần bề rộng khung/giây
REACH = 0.75          # khoảng cách bóng–cầu thủ tối đa, nhân chiều cao khối cầu thủ
BLOB_MIN_AREA = 20    # số điểm ảnh tối thiểu của một khối cầu thủ
TOUCH_NMS = 0.4       # bán kính gộp ứng viên, giây
```

Kết quả đo trong T-031:

```json
{"f1": 0.0, "precision": 0.0, "recall": 0.0, "touch_f1_any": 0.9737, "team_accuracy": 0.0, "id_accuracy": 0.0, "seconds_per_min": 2.0195, "per_clip": [{"clip": "dribble", "duration": 20.0, "touches": 13, "queries": 4, "f1": 0.0, "precision": 0.0, "recall": 0.0, "touch_f1_any": 1.0, "team_accuracy": 0.0, "id_accuracy": 0.0, "seconds_per_min": 2.1604}, {"clip": "near_miss", "duration": 20.0, "touches": 6, "queries": 5, "f1": 0.0, "precision": 0.0, "recall": 0.0, "touch_f1_any": 1.0, "team_accuracy": 0.0, "id_accuracy": 0.0, "seconds_per_min": 1.9514}, {"clip": "number_hidden", "duration": 20.0, "touches": 8, "queries": 3, "f1": 0.0, "precision": 0.0, "recall": 0.0, "touch_f1_any": 1.0, "team_accuracy": 0.0, "id_accuracy": 0.0, "seconds_per_min": 2.0153}, {"clip": "short_passes", "duration": 24.0, "touches": 12, "queries": 6, "f1": 0.0, "precision": 0.0, "recall": 0.0, "touch_f1_any": 0.9091, "team_accuracy": 0.0, "id_accuracy": 0.0, "seconds_per_min": 1.9902}]}
```

## Highlight theo sự kiện: đo độ chính xác (eval)

Tạo bộ video tổng hợp và chạy phép đo:

```bash
python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json
```

Mỗi trận có dạng `<thư-mục>/<trận>/{video.mp4,labels.json}`. Nhãn là danh sách
JSON, ví dụ `[{"start":18.0,"end":30.0,"type":"goal"}]`.

- `goal`: tiếng reo kéo dài, tỷ số thay đổi và có đoạn phát lại.
- `save`: tiếng reo tăng nhanh trong 2–3 giây, tỷ số không đổi.
- `red_card`: tiếng còi 3 kHz, khoảng dừng yên lặng và cảnh cận màu đỏ.
- `controversy`: tiếng còi, khoảng dừng dài có tiếng la ó trầm và đoạn phát lại.
- `distractor`: tiếng cổ động không có sự kiện, nhãn hay thay đổi tỷ số.

Baseline đo trong T-011 (mọi đoạn đều là `other`):

```json
{"f1": 0.8421, "precision": 0.7273, "recall": 1.0, "event_accuracy": 0.0, "per_event": {"goal": {"precision": null, "recall": 0.0, "f1": null}, "save": {"precision": null, "recall": 0.0, "f1": null}, "red_card": {"precision": null, "recall": 0.0, "f1": null}, "controversy": {"precision": null, "recall": 0.0, "f1": null}, "other": {"precision": 0.0, "recall": null, "f1": null}}, "precision_at_5": 0.8889, "per_match": [{"match": "cards", "labels": 4, "predictions": 7, "f1": 0.7273, "precision": 0.5714, "recall": 1.0, "event_accuracy": 0.0, "precision_at_5": 0.8}, {"match": "controversy", "labels": 3, "predictions": 3, "f1": 1.0, "precision": 1.0, "recall": 1.0, "event_accuracy": 0.0, "precision_at_5": 1.0}, {"match": "goals_saves", "labels": 4, "predictions": 6, "f1": 0.8, "precision": 0.6667, "recall": 1.0, "event_accuracy": 0.0, "precision_at_5": 0.8}, {"match": "mixed", "labels": 5, "predictions": 6, "f1": 0.9091, "precision": 0.8333, "recall": 1.0, "event_accuracy": 0.0, "precision_at_5": 1.0}]}
```

Mục tiêu tiếp theo: recall mỗi sự kiện ≥ 0.9, recall bàn thắng ≥ 0.95, F1 không giảm.

Kết quả sau T-013 (bàn thắng = bảng tỷ số đổi + tiếng reo kéo dài):

```json
{"f1": 0.8421, "precision": 0.7273, "recall": 1.0, "event_accuracy": 0.3125, "per_event": {"goal": {"precision": 1.0, "recall": 1.0, "f1": 1.0}, "save": {"precision": null, "recall": 0.0, "f1": null}, "red_card": {"precision": null, "recall": 0.0, "f1": null}, "controversy": {"precision": null, "recall": 0.0, "f1": null}, "other": {"precision": 0.0, "recall": null, "f1": null}}, "precision_at_5": 0.8889, "per_match": [{"match": "cards", "labels": 4, "predictions": 7, "f1": 0.7273, "precision": 0.5714, "recall": 1.0, "event_accuracy": 0.0, "precision_at_5": 0.8}, {"match": "controversy", "labels": 3, "predictions": 3, "f1": 1.0, "precision": 1.0, "recall": 1.0, "event_accuracy": 0.3333, "precision_at_5": 1.0}, {"match": "goals_saves", "labels": 4, "predictions": 6, "f1": 0.8, "precision": 0.6667, "recall": 1.0, "event_accuracy": 0.5, "precision_at_5": 0.8}, {"match": "mixed", "labels": 5, "predictions": 6, "f1": 0.9091, "precision": 0.8333, "recall": 1.0, "event_accuracy": 0.4, "precision_at_5": 1.0}]}
```

SportsCut xác nhận bàn thắng khi tiếng reo kéo dài đi trước thay đổi bảng tỷ số; nếu không tìm thấy bảng tỷ số, hệ thống dùng tiếng reo với độ tin cậy thấp hơn.

Kết quả sau T-014 (cứu thua = tiếng reo ngắn, bật lên nhanh, không có tiếng còi trong 5 giây sau và bảng tỷ số không đổi):

```json
{"f1": 0.8421, "precision": 0.7273, "recall": 1.0, "event_accuracy": 0.625, "per_event": {"goal": {"precision": 1.0, "recall": 1.0, "f1": 1.0}, "save": {"precision": 1.0, "recall": 1.0, "f1": 1.0}, "red_card": {"precision": null, "recall": 0.0, "f1": null}, "controversy": {"precision": null, "recall": 0.0, "f1": null}, "other": {"precision": 0.0, "recall": null, "f1": null}}, "precision_at_5": 0.8889, "per_match": [{"match": "cards", "labels": 4, "predictions": 7, "f1": 0.7273, "precision": 0.5714, "recall": 1.0, "event_accuracy": 0.25, "precision_at_5": 0.8}, {"match": "controversy", "labels": 3, "predictions": 3, "f1": 1.0, "precision": 1.0, "recall": 1.0, "event_accuracy": 0.3333, "precision_at_5": 1.0}, {"match": "goals_saves", "labels": 4, "predictions": 6, "f1": 0.8, "precision": 0.6667, "recall": 1.0, "event_accuracy": 1.0, "precision_at_5": 0.8}, {"match": "mixed", "labels": 5, "predictions": 6, "f1": 0.9091, "precision": 0.8333, "recall": 1.0, "event_accuracy": 0.8, "precision_at_5": 1.0}]}
```

Các ngưỡng của T-014 (còi 2–4 kHz kéo dài ≥ 0,3 giây, tiếng reo < 4 giây, thời gian bật ≤ 0,5 giây) chỉ được chỉnh trên bộ video tổng hợp. Muốn chỉnh cho trận thật cần bộ nhãn data/eval/ do PO gán. Khi video không có bảng tỷ số, SportsCut không gắn nhãn cứu thua.

Kết quả sau T-015 (thẻ đỏ = còi + dừng trận ≥ 8 giây + cận cảnh đỏ giữa khung hình; tranh cãi = còi + dừng trận ≥ 30 giây + tiếng la ó ≥ 10 giây, hoặc tỷ số bị hoàn lại):

```json
{"f1": 0.8421, "precision": 0.7273, "recall": 1.0, "event_accuracy": 1.0, "per_event": {"goal": {"precision": 1.0, "recall": 1.0, "f1": 1.0}, "save": {"precision": 1.0, "recall": 1.0, "f1": 1.0}, "red_card": {"precision": 1.0, "recall": 1.0, "f1": 1.0}, "controversy": {"precision": 1.0, "recall": 1.0, "f1": 1.0}, "other": {"precision": 0.0, "recall": null, "f1": null}}, "precision_at_5": 0.8889, "per_match": [{"match": "cards", "labels": 4, "predictions": 7, "f1": 0.7273, "precision": 0.5714, "recall": 1.0, "event_accuracy": 1.0, "precision_at_5": 0.8}, {"match": "controversy", "labels": 3, "predictions": 3, "f1": 1.0, "precision": 1.0, "recall": 1.0, "event_accuracy": 1.0, "precision_at_5": 1.0}, {"match": "goals_saves", "labels": 4, "predictions": 6, "f1": 0.8, "precision": 0.6667, "recall": 1.0, "event_accuracy": 1.0, "precision_at_5": 0.8}, {"match": "mixed", "labels": 5, "predictions": 6, "f1": 0.9091, "precision": 0.8333, "recall": 1.0, "event_accuracy": 1.0, "precision_at_5": 1.0}]}
```

Các ngưỡng của T-015 (dừng trận ≥ 8 giây cho thẻ đỏ và ≥ 30 giây cho tranh cãi, tiếng la ó 20–220 Hz ≥ 10 giây, ≥ 2 khung hình có giữa khung chủ yếu là màu đỏ trong 15 giây sau tiếng còi, tỷ số được coi là hoàn lại khi bảng trở về trạng thái cũ trong vòng 180 giây) chỉ được chỉnh trên bộ video tổng hợp. Muốn chỉnh cho trận thật cần bộ nhãn data/eval/ do PO gán. Đây là các heuristic chỉ dùng ffmpeg nên độ tin cậy thấp (`event_confidence` 0,5 cho thẻ đỏ và tỷ số bị hoàn lại, 0,4 cho tranh cãi). Nhận diện pha chiếu lại (replay) và nhận diện thẻ/trọng tài bằng mô hình thị giác là việc sau này, sẽ nằm trong gói tùy chọn `[vision]`.

## Theo dõi cầu thủ: xuất video tổng hợp (player)

```bash
python -m sportscut player match.mp4 --team red --number 10 --out reel
```

Mỗi pha chạm được lấy thêm 3 giây trước và 2 giây sau; các đoạn cách nhau dưới
4 giây được gộp. Có thể đổi các giá trị mặc định bằng `--pre`, `--post` và
`--merge-gap`. Thư mục đầu ra chứa `player_red_10.mp4` và `player.json`; nếu
không có pha chạm thì chỉ có manifest. Việc phát hiện pha chạm vẫn là stub cho
đến khi T-031..T-033 hoàn thành.

Lọc clip theo sự kiện và chỉ giữ các pha được xếp hạng cao nhất:

```bash
sportscut cut match.mp4 --out clips --events goal --top 5
```

## API HTTP

Cài phần phụ thuộc API và chạy server cục bộ:

```bash
pip install -e '.[api]'
pip install -e '.[api,youtube]'
sportscut serve --host 127.0.0.1 --port 8000
```

Gửi video và tải một clip từ URL trong kết quả:

```bash
curl -F file=@match.mp4 -F top=5 -F events=goal,save \
  -F min_len=10 -F max_len=30 \
  http://127.0.0.1:8000/highlights
curl -F url=https://www.youtube.com/watch?v=VIDEO_ID \
  http://127.0.0.1:8000/highlights
curl -o clip_01.mp4 "<clip_url>"
```

Phản hồi có dạng `{"job_id":"...","source_name":"match.mp4","source_url":null,
"duration":90,"highlights":[{"start":12,"end":24,
"score":4.2,"reason":"audio peak z=4.2","event":"goal",
"event_confidence":0.8,"clip_url":"http://127.0.0.1:8000/
highlights/.../clips/clip_01.mp4"}]}`. `SPORTSCUT_DATA_DIR` chọn thư mục dữ liệu
(mặc định `./sportscut-data`), còn `SPORTSCUT_MAX_UPLOAD_BYTES` đặt giới hạn
upload (mặc định 20 GiB, đủ cho nguyên trận 90 phút). API dùng mã 400 cho video đầu vào không hợp lệ, 404 cho
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
curl 'http://127.0.0.1:8000/highlights/JOB_ID?event=goal'
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
9. Trên form tải lên, có thể chọn các ô sự kiện như "Bàn thắng" để chỉ xuất
   những sự kiện đó; bỏ trống để giữ mọi sự kiện.
10. Trong trang xem trước, mỗi đoạn có một huy hiệu sự kiện bằng tiếng Việt.
11. Dùng các chip sự kiện, "Tất cả", "Chỉ bàn thắng" hoặc "Top 5 pha hay" để
    chọn các hàng cần xem.
12. Các bộ lọc chỉ ẩn hàng: "Lưu" vẫn lưu tất cả đoạn, còn liên kết clip chỉ
    hiện cho những hàng đang được hiển thị.
13. Mục "Tiêu đề, mô tả và hashtag" có một khối cho cả video và một khối cho mỗi đoạn. Sửa chữ, nhấn
    "Sao chép" để chép tiêu đề, mô tả và hashtag, rồi nhấn "Lưu tiêu đề và hashtag" (tiêu đề 10–80 ký tự,
    mô tả 1–300 ký tự, 3–8 hashtag dạng `#ChuKhongDau`, như `eval-meta`).
14. Sau khi "Lưu" cắt lại clip, chữ của từng đoạn trở về mặc định, chữ của cả video được giữ. Nút
    "Lồng tiếng" hiện khi một đoạn có bản lồng tiếng.

Trang trả về lỗi 404 nếu `JOB_ID` không tồn tại.

## Camera ảo bám cầu thủ (T-019)

`reframe.plan_crop` không còn cắt giữa khung hình mà bám theo cầu thủ. Mỗi mẫu 5 Hz, khung
hình được thu nhỏ còn rộng 320 px. Mặt sân được tìm bằng mặt nạ màu cỏ HSV (hue 60–180°).
Khối điểm không phải màu xanh nằm bên trong sân (sau khi co 3x3) được tính là cầu thủ. Mục
tiêu là trọng tâm của cửa sổ rộng bằng khung crop chứa nhiều khối nhất. Camera đi theo mục
tiêu với vùng chết, làm mượt hàm mũ và tốc độ lia tối đa. Khi không thấy sân, camera giữ
nguyên vị trí; nếu từ đầu clip chưa có phép đo nào thì camera đứng ở giữa. Baseline cũ vẫn
còn là `reframe.center_plan`.

Hằng số cuối cùng: `DEAD_ZONE = 0.06`, `EASE = 0.2`, `MAX_PAN = 0.1` (tỷ lệ chiều rộng khung
hình mỗi giây).

Ngưỡng jitter: jitter ≤ 0.002 (trung bình |sai phân bậc 2| trên lưới 5 Hz / chiều rộng khung)

Trước (T-017, center crop):

```text
{"ball_in_crop": 0.2821, "players_in_crop": 0.4024, "jitter": 0.0, "seconds_per_min": 0.304, "per_clip": [{"clip": "long_pass", "duration": 12.0, "labels": 60, "ball_labels": 60, "player_boxes": 240, "ball_in_crop": 0.0333, "players_in_crop": 0.25, "jitter": 0.0, "seconds_per_min": 0.2907}, {"clip": "occluded", "duration": 12.0, "labels": 60, "ball_labels": 54, "player_boxes": 180, "ball_in_crop": 0.6111, "players_in_crop": 0.8722, "jitter": 0.0, "seconds_per_min": 0.2859}, {"clip": "slow_dribble", "duration": 12.0, "labels": 60, "ball_labels": 60, "player_boxes": 240, "ball_in_crop": 0.5167, "players_in_crop": 0.2542, "jitter": 0.0, "seconds_per_min": 0.2888}, {"clip": "white_distractor", "duration": 12.0, "labels": 60, "ball_labels": 60, "player_boxes": 180, "ball_in_crop": 0.0, "players_in_crop": 0.3333, "jitter": 0.0, "seconds_per_min": 0.3506}]}
```

Sau (T-019):

```text
{"ball_in_crop": 0.5812, "players_in_crop": 0.5988, "jitter": 0.001658, "seconds_per_min": 1.2652, "per_clip": [{"clip": "long_pass", "duration": 12.0, "labels": 60, "ball_labels": 60, "player_boxes": 240, "ball_in_crop": 0.6, "players_in_crop": 0.5, "jitter": 0.001355, "seconds_per_min": 1.28}, {"clip": "occluded", "duration": 12.0, "labels": 60, "ball_labels": 54, "player_boxes": 180, "ball_in_crop": 0.7222, "players_in_crop": 0.7389, "jitter": 0.001839, "seconds_per_min": 1.2681}, {"clip": "slow_dribble", "duration": 12.0, "labels": 60, "ball_labels": 60, "player_boxes": 240, "ball_in_crop": 1.0, "players_in_crop": 0.6542, "jitter": 0.000765, "seconds_per_min": 1.2507}, {"clip": "white_distractor", "duration": 12.0, "labels": 60, "ball_labels": 60, "player_boxes": 180, "ball_in_crop": 0.0167, "players_in_crop": 0.5167, "jitter": 0.002673, "seconds_per_min": 1.2619}]}
```

Thời gian lập kế hoạch cho clip 60 s 1280x720 (testsrc2): 1.1 s (giới hạn 6.0 s).

## Video dọc 9:16 cho TikTok/Reels (cut --vertical)

Thêm `--vertical` vào lệnh `cut` để xuất thêm một bản dọc 9:16 cho mỗi clip:

```bash
sportscut cut match.mp4 --out out --vertical
```

Ngoài `out/clip_NN.mp4`, lệnh ghi thêm `out/vertical/clip_NN.mp4` (1080x1920,
H.264, giữ nguyên âm thanh) và in đường dẫn bản dọc ngay sau đường dẫn clip. Mỗi
mục trong `out/highlights.json` có thêm khóa cuối `vertical_file`, ví dụ
`"vertical_file": "vertical/clip_01.mp4"`. Không có `--vertical` thì kết quả
giữ nguyên như trước.

Khung cắt luôn lấy hết chiều cao và chạy theo đường crop của `plan_crop`. Hiện
`plan_crop` vẫn là crop tĩnh ở giữa khung hình; khi các task bám theo bóng và cầu
thủ hoàn thành, bản dọc sẽ tự bám theo mà không cần đổi lệnh.

Bảng tỉ số của đài truyền hình được tự động dò tìm, cắt ra từ khung hình gốc ở
từng khung hình và phóng to ở dải trên cùng của bản dọc, nên tỉ số luôn đúng và
tự cập nhật ngay sau bàn thắng.

Clip có sự kiện được thêm một dòng chú thích như `BÀN THẮNG · 34'` (hoặc
`CỨU THUA`, `THẺ ĐỎ`, `TRANH CÃI`). Phút được tính từ đầu video, không đọc đồng hồ
trận đấu. Cần cài một phông chữ hỗ trợ tiếng Việt (ví dụ DejaVu Sans hoặc Noto
Sans); kiểm tra bằng `fc-list :lang=vi`.

Nếu không tìm thấy bảng tỉ số, bản dọc không có lớp tỉ số. Khi đó hãy chỉ định
vùng bảng tỉ số bằng `--score-box x,y,w,h` (tính theo pixel của video gốc):

```bash
sportscut cut match.mp4 --out out --vertical --score-box 40,16,160,40
```

Cập nhật (T-045): `plan_crop` nay bám theo cầu thủ bằng camera ảo (xem mục T-019 ở
trên), nên bản dọc cũng bám theo cầu thủ.

### Phụ đề lời bình luận (--subtitles)

Thêm `--subtitles` (cần `--vertical`) để chép lời bình luận gốc thành phụ đề và in
vào phần dưới của bản dọc. Tính năng này dùng gói tùy chọn speech-to-text
(faster-whisper, model `base`). Model được tải về bộ nhớ đệm của Hugging Face ở lần
dùng đầu tiên, hoặc tải trước bằng `sportscut download-models`:

```bash
pip install 'sportscut[asr]'
sportscut download-models
sportscut cut match.mp4 --out out --vertical --subtitles
```

Ngôn ngữ được tự nhận dạng cho từng clip, nên bình luận tiếng Việt và tiếng Anh
đều dùng được. Chỉ âm thanh của các clip đã xuất được chép lời (không chép cả
trận). Ngoài bản dọc có phụ đề, lệnh ghi thêm file phụ đề `out/vertical/clip_NN.srt`
(UTF-8, thời gian tính từ đầu clip). Nếu chưa cài `sportscut[asr]`, lệnh in một dòng
thông báo và vẫn xuất bản dọc, chỉ không có phụ đề.

## Camera bám bóng (T-020)

`reframe.plan_crop` nay bám theo bóng và dùng cụm cầu thủ (T-019) làm dự phòng. Trên các
khung phân tích 5 Hz sẵn có (không giải mã thêm lần nào), bóng được tìm bằng numpy (không
OpenCV): điểm sáng trắng nằm trong mặt sân, gom thành khối nhỏ gần tròn (hộp 3x3 hoặc 5x5
đủ đầy) và có một vành rỗng 2 px xung quanh, nên vạch kẻ, áo trắng và khối lớn bị loại.
Bộ theo dõi giữ ứng viên gần vị trí dự đoán nhất (vận tốc không đổi, trong cổng
`BALL_GATE`), giữ nguyên vị trí khi lỡ vài mẫu và coi là mất bóng sau `BALL_LOST` mẫu
liên tiếp. Trọng số tin cậy bóng tăng/giảm `BLEND_STEP` mỗi mẫu. Mục tiêu là cửa sổ
nhiều cầu thủ nhất mà vẫn giữ bóng cách mép crop ít nhất `BALL_EDGE` chiều rộng crop, được
trộn với mục tiêu cầu thủ của T-019 theo trọng số đó, nên khi chuyển giữa bóng và cầu thủ
camera không giật. Cùng bộ làm mượt của T-019 được dùng lại với hệ số theo từng mẫu, nội
suy giữa hằng số cầu thủ (không đổi) và hằng số bóng. Không có ứng viên bóng thì kết quả
y hệt camera T-019.

Hằng số cuối cùng:

- `BALL_LEVEL = 160`
- `BALL_FILL = 0.4`
- `BALL_GATE = 0.25`
- `BALL_LOST = 5`
- `BLEND_STEP = 0.1`
- `BALL_EDGE = 0.15`
- `BALL_DEAD_ZONE = 0.01`
- `BALL_EASE = 0.3`
- `BALL_MAX_PAN = 0.3`

Đánh đổi: players_in_crop có thể giảm tối đa 0.03 so với T-045, vì trong long_pass và
white_distractor bóng ở xa cầu thủ, và một crop rộng 202 px có chứa bóng chỉ giữ được tối
đa 0.625 số cầu thủ theo nhãn.

Trước (T-045, chỉ cầu thủ):

```text
{"ball_in_crop": 0.5812, "players_in_crop": 0.5988, "jitter": 0.001658, "seconds_per_min": 1.1899, "per_clip": [{"clip": "long_pass", "duration": 12.0, "labels": 60, "ball_labels": 60, "player_boxes": 240, "ball_in_crop": 0.6, "players_in_crop": 0.5, "jitter": 0.001355, "seconds_per_min": 1.2089}, {"clip": "occluded", "duration": 12.0, "labels": 60, "ball_labels": 54, "player_boxes": 180, "ball_in_crop": 0.7222, "players_in_crop": 0.7389, "jitter": 0.001839, "seconds_per_min": 1.1857}, {"clip": "slow_dribble", "duration": 12.0, "labels": 60, "ball_labels": 60, "player_boxes": 240, "ball_in_crop": 1.0, "players_in_crop": 0.6542, "jitter": 0.000765, "seconds_per_min": 1.1854}, {"clip": "white_distractor", "duration": 12.0, "labels": 60, "ball_labels": 60, "player_boxes": 180, "ball_in_crop": 0.0167, "players_in_crop": 0.5167, "jitter": 0.002673, "seconds_per_min": 1.1797}]}
```

Sau (T-020):

```text
{"ball_in_crop": 0.9615, "players_in_crop": 0.5774, "jitter": 0.001892, "seconds_per_min": 4.618, "per_clip": [{"clip": "long_pass", "duration": 12.0, "labels": 60, "ball_labels": 60, "player_boxes": 240, "ball_in_crop": 0.85, "players_in_crop": 0.3667, "jitter": 0.002154, "seconds_per_min": 4.6741}, {"clip": "occluded", "duration": 12.0, "labels": 60, "ball_labels": 54, "player_boxes": 180, "ball_in_crop": 1.0, "players_in_crop": 0.8833, "jitter": 0.002115, "seconds_per_min": 4.5732}, {"clip": "slow_dribble", "duration": 12.0, "labels": 60, "ball_labels": 60, "player_boxes": 240, "ball_in_crop": 1.0, "players_in_crop": 0.7417, "jitter": 0.002177, "seconds_per_min": 4.5969}, {"clip": "white_distractor", "duration": 12.0, "labels": 60, "ball_labels": 60, "player_boxes": 180, "ball_in_crop": 1.0, "players_in_crop": 0.3333, "jitter": 0.001121, "seconds_per_min": 4.6278}]}
```

Thời gian lập kế hoạch cho clip 60 s 1280x720 (white_distractor lặp lại): 4.34 s (giới hạn
6.0 s).

Clip thật: no data/eval_crop clips available.

## Video dọc 9:16: đo khung cắt (eval-crop)

Tạo bộ video tổng hợp có nhãn rồi đo baseline crop giữa khung hình:

```bash
python tests/fixtures/eval_crop/build.py
python -m sportscut eval-crop tests/fixtures/eval_crop --json
```

Mỗi case có `clip.mp4` và `labels.json`. Nhãn là một danh sách lấy mẫu thưa theo
thời gian; ví dụ một dòng:
`{"t": 0.0, "ball": [120, 200], "players": [[103, 163, 14, 30]]}`.
`ball: null` nghĩa là bóng không nhìn thấy, còn `players` có thể bỏ qua khi chưa
gán nhãn cầu thủ. Dữ liệu thật dùng cùng bố cục tại
`data/eval_crop/<name>/{clip.mp4,labels.json}`.

`ball_in_crop` là tỷ lệ tâm bóng nằm trong cửa sổ crop; `players_in_crop` dùng
tâm hộp cầu thủ. `jitter` là trung bình trị tuyệt đối của sai phân bậc hai tâm
crop trên lưới 5 Hz, chia cho chiều rộng khung hình. `seconds_per_min` là thời
gian lập kế hoạch crop trên mỗi phút video.

Baseline đo trong T-017 (center crop):

```json
{"ball_in_crop": 0.2821, "players_in_crop": 0.4024, "jitter": 0.0, "seconds_per_min": 0.3127, "per_clip": [{"clip": "long_pass", "duration": 12.0, "labels": 60, "ball_labels": 60, "player_boxes": 240, "ball_in_crop": 0.0333, "players_in_crop": 0.25, "jitter": 0.0, "seconds_per_min": 0.3134}, {"clip": "occluded", "duration": 12.0, "labels": 60, "ball_labels": 54, "player_boxes": 180, "ball_in_crop": 0.6111, "players_in_crop": 0.8722, "jitter": 0.0, "seconds_per_min": 0.3009}, {"clip": "slow_dribble", "duration": 12.0, "labels": 60, "ball_labels": 60, "player_boxes": 240, "ball_in_crop": 0.5167, "players_in_crop": 0.2542, "jitter": 0.0, "seconds_per_min": 0.3041}, {"clip": "white_distractor", "duration": 12.0, "labels": 60, "ball_labels": 60, "player_boxes": 180, "ball_in_crop": 0.0, "players_in_crop": 0.3333, "jitter": 0.0, "seconds_per_min": 0.3324}]}
```

Mục tiêu: ball_in_crop ≥ 0.95 với jitter thấp (các task R-004 sau).
