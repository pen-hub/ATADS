# Ma trận bằng chứng khảo sát ATADS

- **Ngày khảo sát:** 2026-10-15 (Asia/Bangkok)
- **Phạm vi:** Gộp các kết luận chính từ mã nguồn, cấu hình, runtime và test hiện có.
- **Giới hạn:** Không có phiên chạy UI/browser hoàn chỉnh trong audit này; endpoint gọi localhost bị sandbox chặn socket nên không suy ra server lên hay xuống. Không có dữ liệu gán nhãn để đánh giá chất lượng mô hình.

## Định nghĩa nhãn

- `CODE_VERIFIED`: Đọc trực tiếp mã nguồn hiện có; không đồng nghĩa đã chạy.
- `RUNTIME_VERIFIED`: Quan sát được một hành vi cụ thể trong runtime/phần cứng; ghi rõ phạm vi quan sát.
- `TEST_VERIFIED`: Bài kiểm thử có kết quả pass/fail cụ thể.
- `CONFIG_ONLY`: Chỉ là giá trị trong config/tài liệu, chưa xác minh hành vi runtime tương ứng.
- `UNVERIFIED`: Chưa xác minh được trong phạm vi khảo sát.

| Kết luận | Nhãn | Bằng chứng cụ thể |
|---|---|---|
| App là web local: FastAPI + frontend HTML/CSS/JS, REST/WS/MJPEG | CODE_VERIFIED | `backend/main.py:57-...`; `frontend/index.html`; `frontend/js/app.js` |
| Hỗ trợ nguồn file video, webcam index và URL RTSP/HTTP(S) | CODE_VERIFIED | `backend/main.py:212`; `backend/core/pipeline.py:147,191,198`; UI source selector |
| Video upload giới hạn loại/kích thước và thử decode | CODE_VERIFIED | `backend/main.py:125` |
| Detector phương tiện chạy YOLO track persist với ByteTrack | CODE_VERIFIED | `backend/detection/models.py:72-80` |
| Accident model chạy theo chu kỳ trong event đang hoạt động, qua bounded queue | CODE_VERIFIED | `backend/core/pipeline.py:25-...`, `:324-...`, `:426-...` |
| Candidate suspicion yêu cầu track tiến gần và khoảng cách giảm; IoU chỉ hỗ trợ, overlap đơn thuần không kích hoạt; quỹ đạo đổi hướng độc lập | CODE_VERIFIED | `backend/analysis/suspicion.py:27-95` |
| Kết luận tự động chỉ SUSPECTED/UNCERTAIN; CONFIRMED/REJECTED là manual review | CODE_VERIFIED | `backend/analysis/event_verifier.py:14-76`; `backend/core/pipeline.py:426-...`; storage update |
| Track trajectory là bottom-center quan sát, bị ngắt đoạn khi gap dài | CODE_VERIFIED | `backend/tracking/trajectory.py:7-...` |
| Event/evidence/export lưu local bằng JSON/JPEG/MP4/CSV/JSON | CODE_VERIFIED | `backend/storage/local_storage.py`; `backend/evidence/buffer.py` |
| Checkpoint phương tiện cấu hình là `best.pt`, không phải `vehicle.pt` | CONFIG_ONLY | `config/settings.json:2`; file path được enumerate |
| Cả hai checkpoint `best.pt` tồn tại trong workspace tại ngày khảo sát | RUNTIME_VERIFIED | File listing: 19,185,427 byte và 19,205,530 byte |
| PyTorch runtime nhận CUDA RTX 5060 Laptop GPU capability 12.0 | RUNTIME_VERIFIED | Import qua `.venv`: torch 2.12.0+cu130, `cuda_available=True`, device name/capability |
| Webcam index 1 có thể mở và đọc frame trong probe OpenCV riêng trước phiên audit | RUNTIME_VERIFIED | Ghi nhận probe trước đó; không phải kiểm thử pipeline/app hoàn chỉnh |
| 15 unit/integration test hiện có đều pass | TEST_VERIFIED | `.venv\Scripts\python.exe -m unittest discover -s tests -v`: `Ran 15 tests ... OK` |
| Integration test xác nhận video synthetic + fake models tạo event review không tự xác nhận | TEST_VERIFIED | `tests/test_core.py::PipelineIntegrationTests.test_video_pipeline_stores_review_events_without_auto_confirmation` |
| Camera stream thật chạy bền, tự phục hồi sau mất kết nối | UNVERIFIED | Mã không reconnect; chưa chạy RTSP/webcam qua app thời lượng dài |
| Throughput/latency thực tế của YOLO trên video người dùng và trình duyệt | UNVERIFIED | Không benchmark model thật trong audit; metric code không đo đầy đủ E2E |
| Precision/recall/mAP hoặc cảnh báo giả của hệ thống | UNVERIFIED | Không có ground truth/event benchmark |
| Browser render, upload API, MJPEG và event review end-to-end | UNVERIFIED | Chưa chạy browser; sandbox chặn socket local trong audit |
| Quy tắc hiện tại là IoU 0.08, distance 0.16, consecutive 3; verifier confidence 0.55, window 3s, 2 positive, uncertain 2.5s | CONFIG_ONLY | `config/rules.json`; một số khóa trajectory/sample không có trong file và dùng fallback code |

## Chênh lệch với tài liệu mô tả cũ

`docs/DETECTION_RULES.md`, `docs/ARCHITECTURE.md` và `docs/TEST_REPORT.md` có nội dung cần đối chiếu lại với mã trước khi trích dẫn; nổi bật là mô tả auto-confirm, interval theo frame và số test. Trong khảo sát này, source code và kết quả chạy test được xem là bằng chứng cho implementation hiện tại; tài liệu cũ không được gán nhãn RUNTIME_VERIFIED.

## Khuyến nghị khi dùng cho thuyết minh

Chương 3 có thể mô tả kiến trúc/pipeline theo các hàng CODE_VERIFIED. Chương 4 chỉ ghi số liệu nếu có log/manifest test mới cùng cấu hình, model hash và protocol; hiện tại có thể ghi kết quả 15 test phần mềm (TEST_VERIFIED) và thông tin CUDA runtime (RUNTIME_VERIFIED), nhưng không suy ra độ chính xác hoặc realtime từ các kết quả này.
