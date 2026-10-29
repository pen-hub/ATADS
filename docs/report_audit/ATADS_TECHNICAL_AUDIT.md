# Khảo sát kỹ thuật repository ATADS

**Tên đề tài:** Hệ thống phát hiện tai nạn giao thông tự động từ camera  
**Ngày khảo sát:** 15-10-2026 (Asia/Bangkok)  
**Repository:** `E:\Dung\cv`  
**Phạm vi:** Tổng hợp mã nguồn, cấu hình, trọng số, giao diện và kiểm thử hiện có để làm tư liệu cho người viết báo cáo đồ án. Tài liệu này mô tả implementation được tìm thấy, không phải chương thuyết minh hoàn chỉnh.

> Không sửa mã nguồn ứng dụng. Tài liệu này bổ sung từ các kết quả audit trước và kiểm tra metadata hai trọng số trong môi trường hiện có. Không đọc `.env`, token, mật khẩu hoặc thông tin xác thực.

## Mục lục

1. [Quy ước mức độ bằng chứng](#1-quy-ước-mức-độ-bằng-chứng)
2. [Thông tin chung và mục đích](#2-thông-tin-chung-và-mục-đích)
3. [Cấu trúc repository](#3-cấu-trúc-repository)
4. [Kiến trúc, công nghệ và cách khởi chạy](#4-kiến-trúc-công-nghệ-và-cách-khởi-chạy)
5. [Mô hình, trọng số và cấu hình inference](#5-mô-hình-trọng-số-và-cấu-hình-inference)
6. [Pipeline video/camera](#6-pipeline-videocamera)
7. [Tracking và quản lý track ID](#7-tracking-và-quản-lý-track-id)
8. [Luật nghi ngờ, xác minh và kết luận](#8-luật-nghi-ngờ-xác-minh-và-kết-luận)
9. [Che khuất, mất track, queue và lỗi](#9-che-khuất-mất-track-queue-và-lỗi)
10. [Bounding box, quỹ đạo, hướng và ROI](#10-bounding-box-quỹ-đạo-hướng-và-roi)
11. [Giao diện và chức năng](#11-giao-diện-và-chức-năng)
12. [Lưu dữ liệu và bằng chứng](#12-lưu-dữ-liệu-và-bằng-chứng)
13. [Kết quả kiểm tra đã có](#13-kết-quả-kiểm-tra-đã-có)
14. [Kế hoạch thực nghiệm Chương 4](#14-kế-hoạch-thực-nghiệm-chương-4)
15. [Hạn chế và nội dung chưa xác minh](#15-hạn-chế-và-nội-dung-chưa-xác-minh)
16. [Bảng ánh xạ chức năng và mã nguồn](#16-bảng-ánh-xạ-chức-năng-và-mã-nguồn)
17. [Nguồn tham khảo](#17-nguồn-tham-khảo)
18. [Tóm tắt cho người viết báo cáo](#tóm-tắt-cho-người-viết-báo-cáo)

## 1. Quy ước mức độ bằng chứng

- **CODE_VERIFIED** — tìm thấy trực tiếp trong code; không tự chứng minh nó đã chạy thành công.
- **RUNTIME_VERIFIED** — đã quan sát một hành vi trong môi trường hiện tại; luôn giới hạn đúng phạm vi quan sát.
- **TEST_VERIFIED** — test có kết quả cụ thể.
- **CONFIG_ONLY** — giá trị được khai báo trong cấu hình; chưa khẳng định runtime đã nạp/áp dụng.
- **UNVERIFIED** — chưa có bằng chứng xác minh trong đợt khảo sát.

Một tính năng có thể có nhiều nhãn khác nhau cho các khía cạnh khác nhau. Ví dụ: đường dẫn model là `CONFIG_ONLY`, file checkpoint tồn tại là `RUNTIME_VERIFIED`, còn chất lượng dự đoán là `UNVERIFIED`.

## 2. Thông tin chung và mục đích

ATADS là ứng dụng giám sát giao thông cục bộ với mục đích nhận diện phương tiện, theo dõi track, tìm các tương tác đáng chú ý trong hình ảnh, thu thập thêm tín hiệu từ model `accident`, rồi tạo sự kiện để người vận hành xem xét. Tên ứng dụng/version trong FastAPI là ATADS 1.0.0 (`backend/main.py`). Đây là mô tả mục đích theo code và UI (**CODE_VERIFIED**), không phải chứng nhận rằng hệ thống tự động phát hiện chính xác tai nạn ngoài thực tế.

Hệ thống có hai luồng nguồn trong code: video tải lên và camera (webcam theo index hoặc camera IP theo URL RTSP/RTSPS/HTTP/HTTPS). Camera phải được truy cập từ máy chạy backend. Việc hỗ trợ endpoint/nguồn là **CODE_VERIFIED**; độ ổn định với từng thiết bị, URL và mạng là **UNVERIFIED**.

## 3. Cấu trúc repository

| Nhóm | File/thư mục chính | Trách nhiệm và bằng chứng |
|---|---|---|
| API/backend | `backend/main.py` | FastAPI lifespan, upload, camera/pipeline, status, stream, events, review, config, export, logs và reports. **CODE_VERIFIED** |
| Core | `backend/core/pipeline.py`, `backend/core/config.py` | Vòng đời nguồn, frame processing, queue xác minh, metrics; đọc/validate/lưu settings. **CODE_VERIFIED** |
| AI | `backend/detection/models.py` | Nạp YOLO checkpoints, `vehicle.track`, `accident.predict`, chuẩn hóa detection. **CODE_VERIFIED** |
| Phân tích | `backend/analysis/suspicion.py`, `backend/analysis/event_verifier.py` | Heuristic candidate và tổng hợp bằng chứng theo thời gian. **CODE_VERIFIED** |
| Tracking | `backend/tracking/bytetrack.py`, `backend/tracking/trajectory.py` | Trỏ tới cấu hình ByteTrack của Ultralytics; lưu lịch sử quỹ đạo quan sát. **CODE_VERIFIED** |
| Evidence/storage | `backend/evidence/buffer.py`, `backend/storage/local_storage.py` | Buffer clip, lưu event JSON/ảnh/clip, truy vấn và export. **CODE_VERIFIED** |
| Frontend | `frontend/index.html`, `frontend/js/app.js`, `frontend/css/app.css` | Giao diện web tĩnh dùng JS thuần, CSS và các kênh REST/WebSocket/MJPEG. **CODE_VERIFIED** |
| Cấu hình | `config/settings.json`, `config/rules.json`, `config/roi.json` nếu tồn tại | Đường dẫn model, inference, luật và ROI; giá trị cụ thể là **CONFIG_ONLY** cho tới khi xác minh nạp runtime. |
| Kiểm thử | `tests/test_core.py` | 15 test unittest cho config, ROI, storage, verifier, suspicion, trajectory và pipeline synthetic. Kết quả **TEST_VERIFIED** |
| Khởi chạy Windows | `start_atads.bat`, `start_atads_cpu_diagnostic.bat`, `wait_for_atads.ps1` | Check môi trường/checkpoint/GPU, chạy Uvicorn loopback và đợi readiness. Nội dung **CODE_VERIFIED**; startup app đầy đủ chưa chạy trong audit. |
| Tài liệu dự án | `README.md`, `docs/API.md`, `docs/ARCHITECTURE.md`, `docs/DETECTION_RULES.md`, `docs/TEST_REPORT.md` | Có mô tả dự án, nhưng một số phát biểu cũ mâu thuẫn với code hiện tại; cần ưu tiên implementation/test mới. |

## 4. Kiến trúc, công nghệ và cách khởi chạy

### Kiến trúc thực tế

Ứng dụng là web local: FastAPI ở backend và HTML/CSS/JavaScript thuần ở frontend. Frontend dùng `fetch` cho REST, WebSocket `/api/ws` cho cập nhật event/verification và `<img>` nhận MJPEG từ `/api/pipeline/stream`. Uvicorn được script Windows cấu hình bind `127.0.0.1`, port mặc định `8765` (**CODE_VERIFIED**).

```mermaid
flowchart LR
  O[Người vận hành / trình duyệt] -->|REST: upload, start/stop, config, event review| A[FastAPI: backend/main.py]
  O <-->|WebSocket: event, verification, error| A
  O <-->|MJPEG: frame đã vẽ| A
  A --> P[Pipeline / reader thread]
  V[Video upload] --> P
  C[Webcam index hoặc URL RTSP/HTTP(S)] --> P
  P --> D[YOLO phương tiện + ByteTrack]
  D --> R[ROI / trajectory / suspicion]
  R --> Q[Bounded verification queue]
  Q --> M[YOLO accident]
  M --> E[EventVerifier]
  P --> B[EvidenceBuffer]
  E --> S[LocalStorageService]
  B --> S
  S --> A
```

Sơ đồ phản ánh quan hệ trong code; không chứng minh hiệu năng hoặc khả năng vận hành liên tục (**CODE_VERIFIED**).

### Framework/thư viện trong môi trường hiện có

Đọc từ `.venv` ngày khảo sát (**RUNTIME_VERIFIED** cho import/phiên bản): Python 3.10.0, FastAPI 0.143.0, OpenCV 5.0.0, PyTorch 2.12.0+cu130, Ultralytics 8.4.160. `torch.cuda.is_available()` là True, GPU được nhận diện là NVIDIA GeForce RTX 5060 Laptop GPU, compute capability `(12, 0)`. `requirements.txt` liệt kê FastAPI, Uvicorn, python-multipart, Ultralytics, OpenCV và psutil; PyTorch được để riêng theo wheel phần cứng. CUDA khả dụng không đồng nghĩa đã xác minh inference model hoặc đạt realtime.

### Cách khởi chạy được khai báo

`start_atads.bat` chuyển thư mục về root dự án, kiểm dependency, kiểm hai file `best.pt`, chạy GPU check, kiểm port 8765, khởi động readiness helper và gọi:

```text
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765 --log-level info
```

Đây là lệnh tìm thấy trong file (**CODE_VERIFIED**), không phải kết quả khởi chạy thành công của audit. `start_atads_cpu_diagnostic.bat` là đường chạy chẩn đoán CPU được cung cấp; không có tự fallback CPU trong `ModelManager` khi device CUDA lỗi. `backend/main.py:57` khởi tạo Settings, storage/log/upload, nạp models và Pipeline trong lifespan.

## 5. Mô hình, trọng số và cấu hình inference

### Checkpoint và class metadata

| Nhiệm vụ | Đường dẫn nguyên trạng trong `config/settings.json` | Classes đọc trực tiếp từ checkpoint | Bằng chứng |
|---|---|---|---|
| Phương tiện | `E:/Dung/cv/runs/detect/phuong_tien/huan_luyen/weights/best.pt` | `{0: 'bus', 1: 'car', 2: 'motorcycle', 3: 'truck'}` | Đường dẫn **CONFIG_ONLY**, file tồn tại và metadata đọc được **RUNTIME_VERIFIED**; `ModelManager` lấy `model.names`. |
| Tai nạn | `E:/Dung/cv/runs/detect/yolo_v11_small_accident/huan_luyen/weights/best.pt` | `{0: 'accident'}` | Đường dẫn **CONFIG_ONLY**, file tồn tại và metadata đọc được **RUNTIME_VERIFIED**; code yêu cầu có class `accident`. |

Metadata classes được truy xuất bằng `YOLO(checkpoint)` trong `.venv` mà không thực hiện inference. Đây chỉ xác minh checkpoint load được để đọc metadata; không phải kết quả nhận diện. Có sự khác biệt với một số class list trong `README.md`; dùng metadata checkpoint/code hiện tại làm nguồn ưu tiên.

**Đối chiếu yêu cầu cũ về `vehicle.pt`:** cấu hình hiện tại vẫn trỏ tới `.../phuong_tien/huan_luyen/weights/best.pt`. Trong thư mục weights có file `best.pt`, `last.pt`, `vehicle7.pt`; không thấy file `vehicle.pt`. Audit này ghi nhận hiện trạng, không thay đổi cấu hình.

### Tham số hiện tại

| Khóa | Giá trị | Nguồn/ý nghĩa |
|---|---:|---|
| `device` | `0` | `config/settings.json`; device GPU đầu tiên nếu CUDA nạp thành công |
| `vehicle_confidence` | `0.50` | Ngưỡng predict/track phương tiện hiện tại |
| `accident_confidence` | `0.45` | Ngưỡng YOLO accident |
| `vehicle_imgsz`, `accident_imgsz` | `640`, `640` | Kích thước inference |
| `verification_queue_size` | `3` | Queue task accident bounded |
| `verification_interval_frames` | `5` | Có trong config cũ; **pipeline hiện tại không dùng khóa này** |
| `verification_interval_seconds` | Không có trong settings hiện tại | Pipeline dùng fallback `0.5` giây; interval model accident theo event được điều khiển theo thời gian |
| `suspicion_iou_threshold` | `0.08` | Chỉ là tín hiệu hỗ trợ sau khi hai track tiến gần; overlap một mình không tạo candidate |
| `suspicion_distance_ratio` | `0.16` | Ngưỡng khoảng cách chuẩn hóa |
| `suspicion_consecutive_frames` | `3` | Tên khóa ngưỡng đếm candidate |
| `verifier_window_seconds` | `3` | Cửa sổ lấy mẫu verifier |
| `verifier_min_positive_frames` | `2` | Số mẫu để `review_ready` |
| `verifier_min_confidence` | `0.55` | Confidence để observation là positive |
| `accident_verification_timeout_seconds` | `3.0` | Thời gian xác minh tối đa trước UNCERTAIN |
| `evidence_pre_seconds`, `evidence_post_seconds` | `5`, `5` | Buffer clip hai phía sự kiện |
| `upload_max_mb` | `1024` | Giới hạn upload được cấu hình |

`verifier_sample_interval_seconds` fallback `0.5`; `trajectory_min_displacement_ratio` fallback `0.025`; `trajectory_turn_threshold_degrees` fallback `75`. Các fallback là **CODE_VERIFIED**, còn config không lưu những khóa này là **CONFIG_ONLY**.

`backend/detection/models.py:72` dùng `YOLO.track` cho phương tiện với `persist=True`, `tracker="bytetrack.yaml"`, confidence/imgsz/device cấu hình. `accident_predict` gọi `YOLO.predict` trên một frame, không phải video action model. Code có warm-up model 64×64 và phát lỗi nếu CUDA inference không hoạt động; chưa chạy startup/inference model đầy đủ trong audit này.

## 6. Pipeline video/camera

1. **Upload:** `POST /api/videos/upload` (`backend/main.py:125`) kiểm tra extension, kích thước theo config, tạo ID tên file server, ghi vào `data/uploads`, tính SHA-256 và thử `cv2.VideoCapture` để đọc metadata/kiểm file decode.
2. **Chọn nguồn:** `POST /api/pipeline/start` (`backend/main.py:212`) nhận `source_type=video` với upload ID, hoặc `source_type=camera` với webcam index `0..16`/URL RTSP, RTSPS, HTTP, HTTPS.
3. **Mở capture:** `Pipeline.start` kiểm nguồn, reset tracking và khởi reader thread. `_read_video` dùng `cv2.VideoCapture(path)`. `_read_camera` dùng DirectShow trên Windows khi nguồn là index; URL thử FFmpeg với timeout; đặt `CAP_PROP_BUFFERSIZE=1` nếu backend hỗ trợ.
4. **Đọc frame:** `_capture_loop` đọc tuần tự. Với file video, timestamp suy từ FPS metadata và loop pace theo FPS/tốc độ phát. Với camera, timestamp là monotonic elapsed. Nếu `read()` thất bại với camera, pipeline tạo lỗi và kết thúc; không có reconnect tự động.
5. **Nhận diện phương tiện/tracking:** `_process` gọi `vehicle_track` trên từng frame.
6. **ROI và quỹ đạo:** lọc detection theo tâm bbox khi ROI bật, cập nhật trajectory từ các detection có `track_id`.
7. **Phát hiện candidate:** `SuspicionAnalyzer` phát trigger khi tương tác/đổi hướng ảnh lặp đủ ngưỡng. Pipeline tạo event SUSPECTED, lưu ảnh và khởi động buffer bằng chứng.
8. **Xác minh phụ:** event đang hoạt động được đưa vào queue khi tới chu kỳ `verification_interval_seconds`. Worker gọi model accident trên ảnh frame snapshot rồi cập nhật verifier/event.
9. **Render/đầu ra:** pipeline vẽ bbox/ID/quỹ đạo/hướng/ROI, mã hóa JPEG và lưu frame mới nhất; API cung cấp MJPEG. WebSocket phát event/verification/error; status API cung cấp metrics.
10. **Kết thúc:** video hết nguồn tự dừng; stop/pause/resume qua action API. Cuối nguồn, clip evidence pending được finalize dạng partial nếu chưa thu đủ post-window.

## 7. Tracking và quản lý `track_id`

- `ModelManager.vehicle_track` gọi Ultralytics `YOLO.track(..., persist=True, tracker="bytetrack.yaml")`; ID detection lấy từ `result.boxes.id`. Đây là sử dụng tracker ByteTrack tích hợp Ultralytics (**CODE_VERIFIED**). `backend/tracking/bytetrack.py` tra cứu file cấu hình `cfg/trackers/bytetrack.yaml` bên trong gói Ultralytics.
- `persist=True` giữ trạng thái tracker qua các frame của cùng lượt nguồn; `Pipeline.start` gọi `reset_tracking()` trước lượt mới. ID là ID do tracker sinh trong luồng, không phải định danh vật thể bền vững xuyên video/camera.
- `TrajectoryTracker` lưu điểm đáy giữa `(x1+x2)/2, y2` cho từng ID có detection, timestamp, frame index, bbox, class và confidence. Lịch sử bounded mặc định 6 giây, 96 điểm/track, tối đa 128 track, gap tối đa 0.75 giây, hướng cần dịch chuyển ít nhất 8 pixel.
- Khi track vắng quá `max_gap_seconds`, thêm điểm `missing`; hàm `direction()` từ chối tính hướng nếu lịch sử có khoảng cách quá dài. Điểm thiếu không được nội suy/predict thành vị trí quan sát.
- Test trajectory xác nhận tách lịch sử từng ID, hướng đơn giản, chèn marker missing, reset và giới hạn số điểm (**TEST_VERIFIED**). Tính ổn định ID trên video thật/occlusion chưa được đánh giá.

## 8. Luật nghi ngờ, xác minh và kết luận

### Giai đoạn A — candidate trong `SuspicionAnalyzer`

Code theo dõi điểm đáy giữa chuẩn hóa của các track có ID. Với mỗi cặp phương tiện, candidate chỉ xuất hiện khi khoảng cách Euclid giữa hai điểm đáy không quá `0.16` và đang giảm so với lần đo trước. IoU bbox từ `0.08` trở lên chỉ được ghi nhận làm tín hiệu hỗ trợ khi điều kiện tiến gần đã đạt; hai bbox chồng lấn đứng riêng không tạo candidate.
Một candidate đơn track cũng có thể xuất hiện khi đổi hướng giữa hai đoạn quan sát vượt `75°`, mỗi đoạn vượt dịch chuyển chuẩn hóa `0.025` (fallback). Candidate được đếm theo khóa track/pair; khóa cấu hình tên `suspicion_consecutive_frames=3`.

**Chi tiết quan trọng:** implementation không đảm bảo “3 frame liền nhau” nghiêm ngặt trong mọi trường hợp. Counter giảm một khi toàn frame không có candidate nào; khi vẫn có candidate khác, counter của pair vắng có thể không giảm. Do đó khi mô tả nên gọi là ngưỡng đếm candidate theo code, không diễn giải mạnh hơn tên khóa. Đây là heuristic trên mặt phẳng ảnh, không đo vận tốc vật lý và không chứng minh đã xảy ra va chạm.

### Giai đoạn B — YOLO accident và `EventVerifier`

Khi có event, worker lấy mẫu inference accident theo chu kỳ. Một quan sát positive cần thỏa:

- đúng thời điểm lấy mẫu (mặc định 0.5 s);
- có class `accident` và confidence từ `0.55`;
- nếu có track xe liên quan, phần giao giữa bbox accident và bbox xe liên quan phải chiếm ít nhất 1% diện tích bbox xe (mẫu số trong `_overlap_ratio` là diện tích đối số thứ hai).

Nếu không có xe trong frame event, điều kiện association bị bỏ qua; observation quality vẫn là poor. Cách ghép bbox này chỉ là association heuristic, không phải quan hệ nhân quả.

`EventVerifier.add` giữ history tối đa 240 phần tử và dùng cửa sổ 3 giây. Ban đầu event ở `SUSPECTED`. Có ít nhất hai positive mẫu với các track liên quan được quan sát đưa technical status thành `READY_FOR_REVIEW`; **không tự chuyển thành CONFIRMED**. Khi elapsed từ lần lấy mẫu đầu tiên đạt 3 giây, trạng thái kỹ thuật thành `UNCERTAIN`, cần con người xem lại. Quyết định reviewer được lưu riêng; field `status` giữ các giá trị legacy để API/UI hiện hữu tương thích.

`UNCERTAIN` là hết thời gian thu bằng chứng/khó kết luận, không đồng nghĩa model đã kết luận tai nạn hoặc không có tai nạn. `CONFIRMED`/`REJECTED` là quyết định thủ công. Các tài liệu cũ mô tả auto-confirm không còn phù hợp với code/test hiện tại.

## 9. Che khuất, mất track, queue và lỗi

- **Che khuất/không có xe liên quan:** verifier có trường `observation_quality` (poor/partial/good). Thiếu bất kỳ track event nào được đánh dấu poor và không thể thành READY_FOR_REVIEW; mẫu thiếu không được coi là bằng chứng âm. Cách xử lý này chưa được đánh giá với bộ clip che khuất.
- **Mất track trajectory:** điểm `missing` ngắt đoạn nét; hướng không tính qua gap dài. Heuristic suspicion riêng có `_last_seen` track timeout 10 đơn vị timestamp trước khi dọn pair state. Đây không phải optical-flow recovery.
- **Queue inference:** `BoundedWorker` có `maxsize` theo config (3). Khi đầy, loại task cũ nhất khỏi queue rồi đưa observation mới; đếm `dropped`. Điều này hạn chế backlog nhưng có thể bỏ mẫu accident trung gian. Metric `dropped_verifications` đếm task xác minh bỏ, không phải frame video.
- **Lỗi camera:** camera không mở được hoặc mất đọc frame sẽ ghi lỗi pipeline và kết thúc nguồn. Không có reconnect logic. Với file lỗi decode, `_read_video` fail. Pipeline dừng không đồng nghĩa lỗi model; cần xem `last_error`, log và nguồn.
- **Lỗi model/device:** `ModelManager` không tự chuyển GPU sang CPU. Lỗi warmup/inference trên device cấu hình gây lỗi load; có BAT chẩn đoán CPU riêng.
- **Evidence không hoàn tất:** nếu nguồn dừng trước post-event window, clip có thể partial và ghi `post_event_window_incomplete`; codec không mở được/thiếu frame có lý do tương ứng.
- **Ngưỡng upload/định dạng:** backend kiểm extension và max MB cấu hình, ID upload được tạo server; API upload thử mở/đọc video. Không có kiểm thử upload qua browser/API trong phiên audit.

## 10. Bounding box, quỹ đạo, hướng và ROI

- **Bounding box:** `_draw` vẽ bbox từ detector, màu theo có/không track ID; nhãn có class, confidence và có thể kèm ID. **CODE_VERIFIED**; hình vẽ qua UI stream chưa chạy end-to-end.
- **Quỹ đạo:** polyline các điểm bottom-center quan sát theo từng track. Các đoạn bị ngắt khi điểm `missing`; có thể tô đậm một track chọn. **CODE_VERIFIED**, logic cập nhật/giới hạn được test.
- **Hướng:** `TrajectoryTracker.direction()` tính vector chuẩn hóa từ vài điểm observed gần nhất; UI có thể bật mũi tên. Chỉ là hướng chuyển động trong mặt phẳng ảnh, không hiệu chỉnh thành hướng/vận tốc vật lý.
- **ROI:** frontend cho phép vẽ polygon từ tối thiểu 3 điểm, lưu theo hash nguồn/video; backend validate điểm chuẩn hóa `[0,1]`, tối đa 32 điểm. Filter dùng tâm bbox nằm trong polygon. Unit test xác nhận lọc ROI và test persistence/validation (**TEST_VERIFIED**). Code UI hướng thao tác ROI theo video upload; quy trình vẽ ROI cho camera chưa được xác nhận.
- Visualization có API cấu hình trajectory, IDs, direction, history và focused track; backend có endpoint xóa trajectory.

## 11. Giao diện và chức năng

Giao diện trong `frontend/index.html` có các trang tổng quan, giám sát video, trung tâm cảnh báo, lịch sử, báo cáo, thông số hệ thống, cấu hình và log. `frontend/js/app.js` là JavaScript thuần.

| Chức năng | Trạng thái code | Đã kiểm chứng |
|---|---|---|
| Dashboard, model/system status | Có | UI/API chưa chạy browser; CUDA runtime riêng đã kiểm tra |
| Upload video, preview, điều khiển start/pause/resume/stop | Có | Pipeline synthetic test; browser upload/API chưa |
| Webcam USB và camera IP RTSP/HTTP(S) | Có | OpenCV webcam index 1 từng được probe độc lập và đọc được frame; app tích hợp/camera IP chưa |
| Detection, track list, ID, FPS/latency | Có | Fake-model integration; không xác minh detector thật trên cảnh trong audit |
| ROI, trajectory, direction, track selection | Có | Logic ROI/trajectory unit-tested; browser drawing/stream chưa |
| Event list, detail, evidence, manual review | Có | Storage review test; API/browser end-to-end chưa |
| Lọc/tìm kiếm/phân trang, CSV/JSON export | Có | CSV header test; browser/JSON full export chưa |
| Cấu hình model/rules/device, logs, reports | Có | Validation/persistence code; chưa kiểm thử giao diện qua browser |

Có nút/chức năng trong code không được hiểu là đã xác nhận vận hành thực tế. Với luồng camera, backend phải chạy trên máy có webcam hoặc truy cập được camera IP qua mạng.

## 12. Lưu dữ liệu và bằng chứng

`data_dir` hiện là `data` (tương đối với project root). `LocalStorageService` tạo các thư mục:

- `data/uploads/`: video được upload;
- `data/events/AT-*.json`: event metadata/trạng thái/detection/trajectory/reason/notes;
- `data/evidence/images/`: ảnh JPEG tại thời điểm event;
- `data/evidence/videos/`: video evidence MP4 nếu codec ghi hoạt động;
- `data/exports/`: CSV hoặc JSON;
- `data/logs/atads.log`: log ứng dụng.

Không thấy SQLite/ORM trong luồng khảo sát; event được lưu thành file JSON. Ghi JSON dùng temp file rồi `os.replace`; thao tác được khóa trong process. Ảnh gọi OpenCV `imwrite`. Evidence buffer giữ trước/sau 5 giây với lấy mẫu tối đa 12 fps; nếu nguồn kết thúc sớm thì lưu partial hoặc thông báo không đủ frame/codec.

API upload dùng ID server, giới hạn loại/size và xác minh decode. BAT chỉ bind loopback; route API được đọc không có auth/role user. Chưa đánh giá deploy ngoài localhost, retention/xóa dữ liệu, backup, concurrency đa tiến trình hay quyền truy cập file. Không đưa credential camera vào tài liệu; URL thật nếu có user/pass phải được bảo vệ trong vận hành.

## 13. Kết quả kiểm tra đã có

### Runtime quan sát được

- **RUNTIME_VERIFIED:** `.venv` import Python 3.10.0, OpenCV 5.0.0, PyTorch 2.12.0+cu130, Ultralytics 8.4.160, FastAPI 0.143.0.
- **RUNTIME_VERIFIED:** CUDA available, nhận NVIDIA GeForce RTX 5060 Laptop GPU, capability `(12,0)`.
- **RUNTIME_VERIFIED:** Hai file `best.pt` tồn tại tại đường dẫn cấu hình; YOLO load được metadata class nêu tại mục 5. Không chạy prediction.
- **RUNTIME_VERIFIED (phạm vi hẹp):** Có ghi nhận probe OpenCV riêng trước đó mở và đọc frame từ webcam index 1; không phải kiểm thử pipeline/application/model tích hợp, cũng không xác nhận camera chạy liên tục.
- Gọi endpoint backend local trong audit bị sandbox chặn quyền socket. Đây là giới hạn môi trường kiểm tra, không phải bằng chứng backend lên hay xuống.

### Test tự động

Lệnh đã chạy:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

**TEST_VERIFIED:** 15 test chạy, tất cả PASS (`Ran 15 tests ... OK`). Nội dung bao gồm config validation/ROI, event persistence/review, CSV header, event verifier, trigger approaching/stable/concurrent, trajectory bounds/gap/reset/direction và một integration test video synthetic 36 frame với fake models. `pytest` không có trong `.venv`; không cài thêm.

Kết quả này không phải benchmark YOLO thật, không phải thử video giao thông thực, không phải browser E2E và không chứng minh precision/recall/realtime.

## 14. Kế hoạch thực nghiệm Chương 4

### Tập kiểm thử có ground truth

Lập manifest cho từng clip/camera: ID, SHA-256, quyền sử dụng, độ phân giải, FPS, duration, ánh sáng/góc nhìn/chất lượng; nhãn sự kiện gồm start/end time, loại tai nạn, phương tiện liên quan và mức che khuất. Gán nhãn độc lập một phần tập bởi hai người, thống nhất quy tắc khớp event. Tách tập theo video/camera, tránh chia frame cùng clip giữa chỉnh tham số và đánh giá cuối.

Bao gồm tối thiểu:

1. Tai nạn rõ ràng ở nhiều khoảng cách/góc nhìn.
2. Xe đi sát, nhập làn/cắt ngang nhưng không va chạm.
3. Che khuất một phần và mất track.
4. Ùn tắc/dừng chờ kéo dài.
5. Camera xa, độ phân giải thấp, rung/nén, thiếu sáng.
6. Video âm tính không có tai nạn.
7. Webcam USB realtime chạy bền 10–30 phút.
8. Camera IP RTSP trên mạng ổn định và bài thử ngắt mạng.

### Quy trình và log

Ghi cấu hình đầy đủ, hash checkpoint, version Python/CUDA/driver/PyTorch/Ultralytics, device, độ phân giải/FPS nguồn, imgsz, ROI, playback speed và thời điểm chạy. Warm-up model 30–60 giây; chạy mỗi kịch bản ít nhất 3 lượt 5–10 phút cùng một lượt dài 30 phút; ghi metrics mỗi giây, event ID, status và log lỗi. Báo cáo median, p95, min/max, độ lệch; phân biệt file replay với realtime camera. Không chỉnh nhiều biến trong cùng một lượt.

### Chỉ số

| Chỉ số | Định nghĩa cần dùng | Dữ liệu cần thu |
|---|---|---|
| FPS đọc nguồn | Frame đọc / wall-clock trong cửa sổ đo | Read counter, monotonic timestamp; FPS metadata chỉ tham khảo |
| FPS xử lý | Frame hoàn thành xử lý / wall-clock | Read/process counters và timestamps |
| FPS trình duyệt | Frame mới render / wall-clock | Browser presentation marks hoặc capture có frame ID |
| Inference latency | thời gian riêng mỗi lần gọi model | Timing model phương tiện và accident |
| Pipeline latency | Từ đầu xử lý frame đến JPEG sẵn sàng | monotonic start/end backend |
| End-to-end latency | Capture timestamp đến thời điểm frame hiển thị | Timestamp gắn frame và browser presentation; cần clock đồng bộ |
| Tỷ lệ queue drop | Số tác vụ xác minh bị loại / task submit | submitted, accepted, dropped, queue size |
| Event precision/recall | TP/(TP+FP), TP/(TP+FN) ở cấp event | Ground truth và quy tắc ghép event công bố trước |
| False alarms/hour | Event FP / giờ video hoặc camera | Clip âm tính và thời lượng quan sát |
| Tỷ lệ cần duyệt | Event SUSPECTED/UNCERTAIN phải xử lý thủ công / tổng event | Event states và quyết định manual |

Định nghĩa tiêu chí khớp event trước khi chạy (overlap thời gian, cùng phương tiện nếu nhãn đủ). Không gọi operational FPS là độ chính xác. Không đưa mAP nếu chưa có tập detection phù hợp.

## 15. Hạn chế và nội dung chưa xác minh

### Hạn chế thấy từ code

- Heuristic suspicion dựa trên ảnh (IoU, khoảng cách, góc đổi hướng), không có calibration camera/đo vận tốc vật lý.
- Verifier dùng YOLO frame-based và ngưỡng heuristic; không phải mô hình video/action/va chạm đã được chứng minh.
- Association accident-vehicle chỉ dựa trên overlap bbox 1%; khi thiếu track thì không bắt buộc association.
- Queue ưu tiên tác vụ mới nhưng có thể loại observation cũ; chưa có số liệu hậu quả cho recall.
- Camera mất đọc sẽ dừng; không tự reconnect.
- Các metrics hiện tại không bao gồm pipeline truyền/hiển thị trình duyệt đầu-cuối. `queue_size`/`dropped_verifications` là queue verifier, không phải dropped video frames.
- API local chưa có xác thực người dùng/role trong routes đã kiểm tra; không tự ý expose server ra mạng.
- File config còn khóa `verification_interval_frames=5`, nhưng code pipeline hiện dùng `verification_interval_seconds` fallback 0.5 s. Cần tránh mô tả khóa frame là chu kỳ runtime hiện tại.
- Tài liệu README/architecture/rules/test report cũ có chi tiết không còn khớp code (bao gồm model/runtime, class list, auto-confirm, số test/interval). Cần cập nhật/đối chiếu trước khi trích dẫn.

### Chưa xác minh

- Khởi chạy server đầy đủ, startup load cả model trên device cấu hình và mở dashboard trong browser.
- Upload video qua frontend/API, MJPEG thực tế, xử lý clip người dùng hết video và lưu clip evidence/codec.
- Inference thật trên video giao thông, webcam tích hợp pipeline, RTSP/HTTP camera, chất lượng detection và phân loại event.
- Reconnect sau mất camera, ổn định 10–30 phút, RAM/VRAM/nhiệt khi chạy lâu.
- FPS thực, latency inference/pipeline/browser/E2E và tần suất task queue drop.
- Event precision, recall, false alarm, missed event, mAP hoặc hiệu quả xử lý che khuất.
- Bảo mật khi triển khai khác localhost, retention, backup và xóa dữ liệu.

## 16. Bảng ánh xạ chức năng và mã nguồn

| Chức năng | File/hàm/lớp quan trọng |
|---|---|
| Khởi tạo API/services/models | `backend/main.py:57` `lifespan`; `backend/detection/models.py:17` `ModelManager` |
| Upload/preview video | `backend/main.py:125` `upload_video`; `:174` preview |
| Chọn nguồn video/camera | `backend/main.py:212` `start_pipeline`; `backend/core/pipeline.py:147` `Pipeline.start`; `:191` `_read_video`; `:198` `_read_camera` |
| Đọc frame, pacing và lỗi capture | `backend/core/pipeline.py:216` `_capture_loop`; `:574` `_fail` |
| Phát hiện phương tiện và ByteTrack | `backend/detection/models.py:72` `vehicle_track`; `backend/tracking/bytetrack.py:4` `tracker_config` |
| Dự đoán accident | `backend/detection/models.py:82` `accident_predict` |
| ROI filter | `backend/core/pipeline.py:414` `_filter_roi`; API `backend/main.py:190`, `:198` |
| Phân tích candidate/suspicion | `backend/analysis/suspicion.py:17` `SuspicionAnalyzer.analyze` |
| Quỹ đạo và hướng | `backend/tracking/trajectory.py:7` `TrajectoryTracker.update`, `direction` |
| Queue inference | `backend/core/pipeline.py:25` `BoundedWorker.submit`, `_run`, `stop` |
| Ghép bằng chứng thời gian/trạng thái | `backend/analysis/event_verifier.py:14` `EventVerifier.add`; `backend/core/pipeline.py:426` `_run_verification` |
| Vẽ bbox/ROI/quỹ đạo | `backend/core/pipeline.py:366` `_draw` |
| Evidence video buffer | `backend/evidence/buffer.py:13` `EvidenceBuffer.trigger`, `add`, `_finalize` |
| Lưu/review/export event | `backend/storage/local_storage.py:13` `LocalStorageService`; `backend/main.py:332-387` event/export routes |
| MJPEG/WebSocket/status | `backend/main.py:284-315` status/frame/stream/WebSocket |
| Settings/rules validation | `backend/core/config.py:18` `Settings`, `validate`, `update`; `config/settings.json`, `config/rules.json` |
| Frontend điều khiển và cập nhật | `frontend/index.html`; `frontend/js/app.js` `uploadVideo`, `pipeline`, `connectSocket`, `saveConfig` |
| Kiểm thử | `tests/test_core.py` (15 test; unittest) |

Số dòng là theo trạng thái file tại ngày khảo sát; khi code đổi, tìm lại tên hàm trước khi trích dẫn vào báo cáo.

## 17. Nguồn tham khảo

Không sử dụng tài liệu bên ngoài trong đợt tổng hợp này; tránh đưa citation học thuật không được kiểm chứng. Nguồn bằng chứng là repository và runtime cục bộ:

- `backend/main.py`, `backend/core/pipeline.py`, `backend/core/config.py`
- `backend/detection/models.py`, `backend/tracking/bytetrack.py`, `backend/tracking/trajectory.py`
- `backend/analysis/suspicion.py`, `backend/analysis/event_verifier.py`
- `backend/evidence/buffer.py`, `backend/storage/local_storage.py`
- `frontend/index.html`, `frontend/js/app.js`, `frontend/css/app.css`
- `config/settings.json`, `config/rules.json`, `requirements.txt`, `tests/test_core.py`
- Các audit thành phần đã tổng hợp: `docs/report_audit/project_inventory.md`, `architecture_and_pipeline.md`, `ai_models_and_rules.md`, `ui_storage_features.md`, `test_plan.md`, `evidence_matrix.md`.

## TÓM TẮT CHO NGƯỜI VIẾT BÁO CÁO

### Dữ kiện có thể dùng

- Hệ thống là web local FastAPI + frontend HTML/CSS/JS; frontend giao tiếp bằng REST, WebSocket và MJPEG.
- Code hỗ trợ video upload, webcam index và URL RTSP/RTSPS/HTTP(S); không đồng nghĩa mọi camera đã chạy thực tế.
- Cấu hình hiện tại dùng hai checkpoint: phương tiện `E:/Dung/cv/runs/detect/phuong_tien/huan_luyen/weights/best.pt`; accident `E:/Dung/cv/runs/detect/yolo_v11_small_accident/huan_luyen/weights/best.pt`.
- Metadata checkpoint đọc được: phương tiện `{bus, car, motorcycle, truck}`, accident `{accident}`. Đây là thông tin lớp, không phải đánh giá accuracy.
- Code dùng Ultralytics YOLO track với ByteTrack cho phương tiện; verifier gọi YOLO accident trên frame theo event. Quỹ đạo là điểm đáy giữa detection theo track ID.
- Candidate dựa trên IoU, khoảng cách đang giảm hoặc đổi hướng quỹ đạo ảnh. Verifier tự động chỉ tạo SUSPECTED/UNCERTAIN; người vận hành mới CONFIRMED/REJECTED.
- Runtime nhận CUDA trên RTX 5060 Laptop GPU với PyTorch 2.12.0+cu130; **chưa đo hiệu năng model**.
- 15 test `unittest` hiện có pass; pipeline test dùng video synthetic và fake models.

### Cần nêu thận trọng

- Yêu cầu trước đó về `vehicle.pt` chưa khớp cấu hình hiện tại: config đang dùng `best.pt`; file `vehicle.pt` không thấy ở đường dẫn đó.
- `verification_interval_frames=5` trong JSON không phải interval hiện dùng; pipeline fallback `verification_interval_seconds=0.5`.
- Heuristic không chứng minh va chạm; không tuyên bố realtime, chính xác cao, precision/recall/FPS nếu chưa đo.
- README/docs cũ có thông tin lỗi thời; đối chiếu source/test trước khi trích.

### Phải kiểm thử trước khi viết kết quả Chương 4

1. Khởi chạy app thật, xác nhận startup models/API/UI và log.
2. Chạy video giao thông có ground truth: tai nạn rõ, tương tác không va chạm, che khuất, ùn tắc, xa/chất lượng thấp và video âm tính.
3. Chạy webcam tích hợp pipeline và RTSP camera; kiểm tra thời lượng dài, ngắt kết nối và khả năng phục hồi.
4. Thu số FPS đọc/ xử lý/hiển thị, latency inference/pipeline/end-to-end, CPU/GPU/RAM, queue/drop; báo median và p95 qua nhiều lượt.
5. Tính event precision/recall, false alarm trên giờ video và tỷ lệ cần người duyệt theo protocol/ground truth được công bố.
6. Kiểm tra event JSON, ảnh/clip bằng chứng, review sau restart và CSV/JSON export.

**Không thể xác minh trong khảo sát này:** app/browser end-to-end đang chạy, model inference thật trên video giao thông, camera IP/webcam qua app, chất lượng/độ chính xác, FPS/latency thực tế, xử lý bền và reconnect, codec evidence trong môi trường người dùng. Không trình bày các mục đó như kết quả đã đạt.
