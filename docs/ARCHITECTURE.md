# Kiến trúc ATADS

```text
Upload → OpenCV VideoCapture → YOLO phương tiện → ByteTrack
                                      ↓
                         SuspicionAnalyzer (track/ảnh)
                                      ↓ dấu hiệu
                       Collision pair candidates
                         (quan sát nhiều thời điểm)
                                      ↓ gate đạt
      circular frame buffer → bounded queue → YOLO accident
                                                ↓ timestamp
                                         EventVerifier
                                                ↓
                              JSON atomic + ảnh + clip nếu codec hỗ trợ
                                                ↓
                                    FastAPI / WebSocket → Dashboard
```

## Module

- `backend/detection/models.py`: checkpoint, names, class `accident`, strict CUDA, inference có lock.
- `backend/core/pipeline.py`: video reader, metrics, box overlay, candidate pair theo thời gian và queue xác minh.
- `backend/analysis/suspicion.py`: tương tác bbox/quỹ đạo sinh dấu hiệu; không trực tiếp kích hoạt model tai nạn.
- `backend/analysis/event_verifier.py`: luật thời gian trên output YOLO từng ảnh; không phải model video.
- `backend/evidence/buffer.py`: frame thật trước/sau, encode clip nếu codec mở được.
- ROI polygon chuẩn hóa được lưu trong `config/roi.json` theo SHA-256 video; ByteTrack vẫn nhìn toàn frame, còn detections ngoài vùng không đi vào suspicion analyzer.
- `backend/storage/local_storage.py`: JSON atomic, serialized writes, CSV/JSON.
- `backend/main.py`: API localhost, upload validation, evidence confinement.
- `frontend/`: dashboard tiếng Việt gọi API thật.

Pipeline: `STOPPED → RUNNING ↔ PAUSED → STOPPED`; lỗi reader thành `ERROR`.
Event kỹ thuật: `SUSPECTED → READY_FOR_REVIEW | UNCERTAIN`. Quyết định người duyệt lưu riêng: `PENDING → CONFIRMED | REJECTED | UNCERTAIN`. Xử lý evidence lưu riêng: `COLLECTING → READY_FOR_REVIEW | COMPLETE | ERROR`. Model confidence không thể tự xác nhận tai nạn.

Mẫu inference có event ID, timestamp nguồn, frame index, crop region, detections/confidence và observation quality. Crop mở rộng quanh các track liên quan. Queue overflow và lỗi model được ghi vào `evidence_issues`. Worker không chặn đọc frame và kết quả được bỏ nếu generation của nguồn đã đổi. Track thiếu so với danh sách liên quan làm quality kém; điểm đó không được tính như negative accident.

Confidence phương tiện mặc định `0.5` đi vào `YOLO.track`; ByteTrack dùng cấu hình `bytetrack.yaml` trong package Ultralytics (hiện package: high 0.25, low 0.1, new 0.25, buffer 30 frame, match 0.8). Bounding box hiển thị chỉ là detection quan sát hiện tại; không giữ bbox predicted sau khi mất detection. Candidate pair chờ tối thiểu 3 quan sát/0.6 giây, lịch sử hai track và tín hiệu closing/suspicion hoặc overlap mạnh trước khi enqueue YOLO accident. Chế độ `diagnostics_enabled` trong `config/rules.json` bật log đếm detection/track, latency/FPS và lý do gate.

Upload giới hạn kích thước, tên file do server tạo, OpenCV phải mở được file. API chỉ bind loopback qua BAT. Đường dẫn evidence được giới hạn trong data root. Cấu hình model có hiệu lực sau lần khởi động lại.

ROI, webcam, benchmark trên footage, luật ground truth, tua video chưa triển khai. Tương tác gần nhau không phải kết luận tai nạn.
