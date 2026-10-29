# Kiểm kê dự án ATADS

- **Ngày khảo sát:** 2026-10-15 (Asia/Bangkok)
- **Phạm vi:** Đọc cấu trúc, mã backend/frontend, cấu hình, hướng dẫn, mô hình và kiểm thử hiện có trong repository `E:\Dung\cv`.
- **Giới hạn:** Đây là kiểm kê tĩnh cộng với kiểm thử tự động hiện có. Chưa xác nhận toàn bộ giao diện và pipeline đang chạy liên tục với camera/video thật. Không mở hoặc ghi nội dung bí mật trong `.env`.

Tên đề tài theo yêu cầu: **Hệ thống phát hiện tai nạn giao thông tự động từ camera**.

## Cấu trúc quan trọng

| Thành phần | File thực tế | Chức năng | Trạng thái xác minh | Bằng chứng |
|---|---|---|---|---|
| Điểm vào API | `backend/main.py` | Khởi tạo FastAPI, lifespan, endpoints, phục vụ frontend tĩnh | CODE_VERIFIED | `lifespan`, routes `/api/*` |
| Pipeline | `backend/core/pipeline.py` | Nạp nguồn, đọc frame, inference phương tiện, suspicion, xác minh bất đồng bộ, MJPEG/metrics | CODE_VERIFIED; một integration test TEST_VERIFIED | `Pipeline.start`, `_capture_loop`, `_process`, `_run_verification`; `tests/test_core.py` |
| Cấu hình | `backend/core/config.py`, `config/settings.json`, `config/rules.json`, `config/roi.json` (nếu có) | Đọc/kiểm tra settings, luật, ROI | CODE_VERIFIED; giá trị hiện tại CONFIG_ONLY | `Settings`, `validate`, `update` |
| Nhận diện | `backend/detection/models.py` | Nạp hai YOLO checkpoint; track phương tiện với ByteTrack; dự đoán lớp accident | CODE_VERIFIED; đường dẫn/file CONFIG_ONLY; môi trường GPU RUNTIME_VERIFIED | `ModelManager`, `vehicle_track`, `accident_predict` |
| Phát hiện dấu hiệu | `backend/analysis/suspicion.py` | Chỉ dùng cặp track tiến gần (bbox overlap chỉ hỗ trợ) hoặc đổi hướng quỹ đạo ảnh để tạo trigger cần xem xét | CODE_VERIFIED; unit test TEST_VERIFIED | `SuspicionAnalyzer.analyze` |
| Xác minh thời gian | `backend/analysis/event_verifier.py` | Tích lũy mẫu model accident, association track, tạo SUSPECTED/UNCERTAIN | CODE_VERIFIED; unit test TEST_VERIFIED | `EventVerifier.add` |
| Tracking quỹ đạo | `backend/tracking/bytetrack.py`, `backend/tracking/trajectory.py` | Adapter/tra cứu cấu hình ByteTrack; lịch sử điểm đáy bbox theo track | CODE_VERIFIED; trajectory tests TEST_VERIFIED | `TrajectoryTracker.update`, `direction`; Ultralytics `bytetrack.yaml` |
| Bằng chứng | `backend/evidence/buffer.py` | Giữ frame trước sự kiện và thu frame sau sự kiện thành clip MP4 | CODE_VERIFIED; ghi clip thực tế chưa kiểm thử trong audit này | `EvidenceBuffer.add`, `trigger`, `_finalize` |
| Lưu trữ | `backend/storage/local_storage.py` | JSON từng event, ảnh JPEG, clip, CSV/JSON export trong data dir | CODE_VERIFIED; JSON review và CSV header TEST_VERIFIED | `LocalStorageService.save_event`, `update_event`, `export_events` |
| Giao diện | `frontend/index.html`, `frontend/js/app.js`, `frontend/css/app.css` | Trang HTML/CSS/JS thuần; REST, WebSocket, MJPEG; controls video/camera | CODE_VERIFIED; giao diện đầy đủ chưa chạy kiểm thử browser | `source-mode`, `uploadVideo`, `pipeline`, `connectSocket` |
| Cấu hình chạy Windows | `start_atads.bat`, `start_atads_cpu_diagnostic.bat`, `wait_for_atads.ps1` | Kiểm dependency/checkpoint/GPU, khởi động Uvicorn trên loopback và readiness | CODE_VERIFIED; chưa xác minh toàn bộ tiến trình server trong audit | nội dung BAT/PS1 |
| Kiểm thử | `tests/test_core.py` | unittest: config, ROI, storage, suspicion/verifier, trajectory, integration video giả | TEST_VERIFIED | 15 test qua bằng `python -m unittest discover -s tests -v` |
| Tài liệu hiện có | `README.md`, `docs/API.md`, `docs/ARCHITECTURE.md`, `docs/DETECTION_RULES.md`, `docs/TEST_REPORT.md` | Hướng dẫn và mô tả trước đây | CODE_VERIFIED là các file tồn tại; một số nội dung không khớp code hiện tại | Đối chiếu nội dung tài liệu với module đang chạy |

## Môi trường và checkpoint

Đọc bằng Python trong `.venv`: Python 3.10.0; OpenCV 5.0.0; PyTorch 2.12.0+cu130; Ultralytics 8.4.160; FastAPI 0.143.0. `torch.cuda.is_available()` trả về `True`, GPU là NVIDIA GeForce RTX 5060 Laptop GPU, capability `(12, 0)`. Đây là xác minh khả dụng của runtime/PyTorch; chưa thay thế phép chạy inference từ ứng dụng.

`config/settings.json` hiện chỉ đường dẫn phương tiện tới `E:/Dung/cv/runs/detect/phuong_tien/huan_luyen/weights/best.pt`, không phải `vehicle.pt`. File `best.pt` phương tiện (19,185,427 byte) và file accident `E:/Dung/cv/runs/detect/yolo_v11_small_accident/huan_luyen/weights/best.pt` (19,205,530 byte) đều tồn tại tại thời điểm khảo sát. Không có xác minh chất lượng hoặc độ chính xác checkpoint.

## Các giới hạn kiểm kê

- Chưa kiểm thử trình duyệt, REST API từ browser, stream MJPEG, IP camera, âm thanh/codec mọi loại.
- `pytest` không có trong `.venv`; bộ kiểm thử dùng thư viện chuẩn `unittest` và chạy đủ 15 test.
- Không có báo cáo accuracy/mAP hoặc ground truth sự kiện đủ để kết luận chất lượng mô hình.
- Những chỉ số FPS/latency trong giao diện là chỉ số nội bộ pipeline; không thể diễn giải là độ trễ đầu-cuối tới màn hình người dùng.
- Tài liệu trong `docs/` cũ có chỗ mô tả luật cũ (ví dụ tự xác nhận). Mã hiện tại và test được ưu tiên cho kết luận trong đợt khảo sát này.
