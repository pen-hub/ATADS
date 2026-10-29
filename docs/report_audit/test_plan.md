# Kế hoạch kiểm thử và đo thực nghiệm

- **Ngày khảo sát:** 2026-10-15 (Asia/Bangkok)
- **Phạm vi:** Đề xuất kiểm thử tiếp nối 15 test unit/integration hiện có.
- **Giới hạn:** Không tạo số liệu mẫu. Chưa có ground truth được cung cấp và chưa đo accuracy/FPS production trong audit này.

## Trạng thái kiểm thử hiện có

`python -m unittest discover -s tests -v` chạy 15 test, tất cả PASS. Các test gồm cấu hình, ROI, lưu event/CSV, suspicion, verifier, quỹ đạo và integration test pipeline trên video sinh 36 frame với fake models. `pytest` không được cài trong `.venv`; không cài thêm vì yêu cầu khảo sát cấm thay đổi môi trường. Integration này kiểm tra glue code, không đo YOLO thật.

## Bộ dữ liệu và kịch bản

Tạo manifest video bất biến có ID, hash, resolution, FPS metadata, thời lượng, nguồn/quyền sử dụng và nhãn event. Mỗi tai nạn gán start/end time, loại/độ rõ, phương tiện liên quan; clip âm tính xác nhận không có va chạm trong toàn khoảng. Hai người gán độc lập một phần clip, thống nhất quy tắc nhãn và lưu bất đồng.

| Nhóm | Thiết kế | Kết quả cần ghi |
|---|---|---|
| Tai nạn rõ ràng | Nhiều góc/cự ly, va chạm nhìn thấy | phát hiện đúng, thời gian trigger, trạng thái, evidence |
| Xe đi sát nhưng không va chạm | cắt ngang, nhập làn, chạy sát, tránh nhau | false positive candidate và event |
| Che khuất | xe/đối tượng che một phần hoặc mất track | quality, UNCERTAIN, bỏ sót |
| Ùn tắc/dừng chờ | dừng lâu, xe san sát, đi chậm | cảnh báo giả/track fragmentation |
| Xa/chất lượng thấp | xe nhỏ, rung, nén, tối/ngược sáng | miss, class/confidence, FPS/latency |
| Video không tai nạn | đường bình thường nhiều phương tiện | số false events trên giờ-video |
| Webcam trực tiếp | webcam USB đúng thiết bị, chạy 10–30 phút | time-to-first-frame, reconnect behavior, stability, thermal/resource |
| IP camera | RTSP trên mạng ổn định, sau đó kiểm tra mất kết nối | buffering/end-to-end metrics, lỗi, recovery |

Chia tập theo video/camera, không chia frame ngẫu nhiên giữa train/test; giữ nguyên resolution/FPS và ghi mọi chỉnh sửa threshold/config. Đánh giá riêng video đã dùng để chỉnh luật và video holdout.

## Quy trình đo hiệu năng

1. Ghi commit/source hash nếu có, cấu hình, phiên bản Python/driver/CUDA/PyTorch/Ultralytics, model hash, thiết bị, độ phân giải/FPS, chế độ CPU/GPU, playback speed và ROI.
2. Khởi động backend, warm-up model 30–60 giây, chạy mỗi kịch bản tối thiểu 3 lần; mỗi lần 5–10 phút, với một lượt dài 30 phút để phát hiện tụt hiệu năng.
3. Ghi metrics mỗi giây: frame read count/timestamps, processed frame count, source FPS, throughput, model inference ms từng model, queue size/dropped verification, latency và tài nguyên GPU/CPU/RAM. Ghi event IDs và thời điểm start/end.
4. Đồng bộ đồng hồ hoặc overlay timestamp cho source; nếu đo end-to-end browser latency, quay/ghi nhận nguồn timestamp và lúc frame tương ứng hiển thị. Metric backend hiện tại không đủ cho số end-to-end.
5. Báo cáo median, p95, min/max và độ lệch chuẩn; không chỉ chọn peak FPS. Giữ riêng kết quả mỗi kịch bản và không gộp webcam với file replay.

## Định nghĩa chỉ số

| Chỉ số | Cách tính | Dữ liệu cần |
|---|---|---|
| FPS đọc nguồn | Số frame đọc / thời gian wall-clock (hoặc chênh timestamp nguồn theo cửa sổ) | frame counter và timestamp read; FPS metadata chỉ là tham chiếu |
| FPS xử lý | Số frame xử lý xong / thời gian wall-clock; báo cáo cùng drop/backlog | read/process counter, monotonic timestamps |
| FPS đầu ra hiển thị | Frame mới thực sự render trong trình duyệt / thời gian wall-clock | browser performance marks hoặc capture màn hình có frame ID |
| Độ trễ inference | Thời lượng hàm inference model từng frame | model timing, tách vehicle và accident |
| Độ trễ pipeline | Từ lúc backend bắt đầu xử lý frame đến khi frame có JPEG sẵn | monotonic start/end trong backend |
| Độ trễ đầu-cuối | Thời điểm hiển thị frame trừ thời điểm capture/source của frame đó | timestamp gắn với frame + browser presentation timestamp; đồng bộ clock |
| Tỷ lệ dropped verification | task bị bỏ khi queue quá tải / tổng task submit | accepted, dropped, queue metrics |
| Event recall | TP event / (TP + FN) | event ground truth và quy tắc matching event |
| Event precision | TP / (TP + FP) | matching theo overlap thời gian và đối tượng theo protocol đã định |
| False alarms / hour | số event FP / giờ-video hoặc giờ-camera | clip âm tính và thời lượng quan sát |
| Tỷ lệ cần duyệt | số event kết thúc SUSPECTED/UNCERTAIN cần người / tổng event | event state + quyết định manual |

Định nghĩa match event trước khi chạy (ví dụ overlap khoảng tai nạn và cùng phương tiện; công bố ngưỡng). Khi không có event labels, chỉ báo cáo operational metrics, không gọi chúng là accuracy.

## Điều kiện dừng / điều tra tụt FPS

So sánh video 720p/1080p, imgsz 640, single stream, queue stats và bật/tắt overlay trajectory ở cùng checkpoint/config. Ghi GPU utilization/memory, CPU, nhiệt độ/công suất nếu công cụ sẵn có; thử warm vs sustained để nhận biết nhiệt/clock. Kiểm tra video FPS cao hơn throughput model; kiểm tra mỗi event có accident inference theo chu kỳ; kiểm tra encoder JPEG và browser refresh. Không đổi nhiều biến trong cùng lượt. Nếu pipeline `ERROR`, lưu log, thời điểm/frame/nguồn và `last_error`; không xóa evidence.

## Bảng kết quả trống để điền sau đo

| Run ID | Clip/camera | Cấu hình/model hash | FPS nguồn | FPS xử lý median/p95 | Latency pipeline median/p95 | E2E latency median/p95 | Dropped verify | TP/FP/FN | Ghi chú |
|---|---|---|---:|---:|---:|---:|---:|---|---|
| Chưa đo | — | — | — | — | — | — | — | — | Chờ thực nghiệm có nhãn |
