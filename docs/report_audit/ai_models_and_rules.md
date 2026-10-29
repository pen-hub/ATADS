# Mô hình AI và luật cảnh báo/xác minh

- **Ngày khảo sát:** 2026-10-15 (Asia/Bangkok)
- **Phạm vi:** Đối chiếu cấu hình hiện tại với `ModelManager`, suspicion analyzer, verifier và test.
- **Giới hạn:** Xác nhận checkpoint tồn tại và CUDA nhận diện GPU; không chạy benchmark chất lượng/độ chính xác, không có ground truth và không đánh giá mAP.

## Mô hình và cấu hình

| Vai trò | Checkpoint trong config | Trạng thái |
|---|---|---|
| Phương tiện | `E:/Dung/cv/runs/detect/phuong_tien/huan_luyen/weights/best.pt` | File có tồn tại (19,185,427 byte). `ModelManager` dùng YOLO `.track(... persist=True, tracker="bytetrack.yaml")`. |
| Accident | `E:/Dung/cv/runs/detect/yolo_v11_small_accident/huan_luyen/weights/best.pt` | File có tồn tại (19,205,530 byte). `ModelManager` dùng YOLO `.predict`; kiểm tra metadata phải có class `accident`. |

Các giá trị `config/settings.json`: device `0`, confidence phương tiện `0.70`, accident `0.45`, imgsz cả hai `640`, `verification_queue_size=3`. Cấu hình có `verification_interval_frames=5` nhưng pipeline hiện tại dùng `verification_interval_seconds`; khóa giây đang thiếu nên code fallback 0.5 giây. Vì thế giá trị interval theo frame không quyết định chu kỳ hiện tại. Phần cấu hình này là CONFIG_ONLY cho hành vi đang chạy; file và khả dụng GPU đã được kiểm tra riêng.

Runtime `.venv`: Python 3.10.0, PyTorch 2.12.0+cu130, CUDA available=True, NVIDIA GeForce RTX 5060 Laptop GPU, capability 12.0; OpenCV 5.0.0, Ultralytics 8.4.160. Đây là RUNTIME_VERIFIED cho import/CUDA capability, không phải tốc độ hay độ chính xác của hai model.

## Luật candidate trong `SuspicionAnalyzer`

Giá trị hiện tại ở `config/rules.json`:

| Khóa | Giá trị | Vai trò |
|---|---:|---|
| `suspicion_iou_threshold` | 0.08 | Chỉ hỗ trợ dấu hiệu khi hai track đang tiến gần; overlap riêng lẻ không tạo candidate |
| `suspicion_distance_ratio` | 0.16 | Khoảng cách tâm chuẩn hóa trên ảnh; cần đồng thời đang tiến gần |
| `suspicion_consecutive_frames` | 3 | Candidate lặp đủ số frame để tạo trigger |
| `trajectory_min_displacement_ratio` | code fallback 0.025 | Dịch chuyển hai đoạn quỹ đạo tối thiểu trước khi xét đổi hướng |
| `trajectory_turn_threshold_degrees` | code fallback 75° | Góc đổi hướng trong mặt phẳng ảnh tạo candidate |

Phân tích cặp dùng điểm đáy giữa bbox (x giữa, y2), chuẩn hóa theo chiều rộng/cao; chỉ tạo candidate khi khoảng cách không quá ngưỡng và đang giảm. IoU bbox chỉ bổ sung ngữ cảnh khi điều kiện tiến gần đã đạt, không tự kích hoạt. Phân tích đổi hướng lấy điểm đáy giữa của track qua ba quan sát gần nhất và góc giữa hai đoạn. Tín hiệu được đếm theo cặp track (hoặc track đơn); các frame không có candidate giảm count một đơn vị. Đủ 3 lần thì emit candidate cho verifier. Đây là heuristic trên ảnh, không suy ra vận tốc vật lý, va chạm hay quan hệ nhân quả.

## Xác minh và vòng đời trạng thái

`EventVerifier.add` lấy mẫu tối thiểu mỗi 0.5 giây, cửa sổ `verifier_window_seconds=3`, confidence hỗ trợ `0.55`, số mẫu positive để sẵn sàng cho người duyệt là `2`, timeout `accident_verification_timeout_seconds=3.0`.

Một mẫu positive cần: đúng thời điểm lấy mẫu; class tên `accident`; confidence đạt 0.55; nếu danh sách xe trong event có dữ liệu thì bbox accident phải overlap ít nhất 1% diện tích bbox tai nạn với một xe liên quan. Nếu không có vehicle track, điều kiện association được nới thành true nhưng observation quality vẫn `poor`. Vì vậy association là heuristic đơn giản.

Trong khoảng quan sát, trạng thái kỹ thuật là `SUSPECTED`; đủ mẫu với các track liên quan được quan sát làm technical status thành `READY_FOR_REVIEW`, không xác nhận. Sau 3 giây tính từ mẫu đầu, nếu chưa đủ bằng chứng/tracks thì technical status chuyển `UNCERTAIN` và cần người duyệt. Quyết định reviewer (`PENDING`, `CONFIRMED`, `REJECTED`, `UNCERTAIN`) được lưu riêng; event field `status` vẫn giữ giá trị legacy để tương thích API/UI.

## Kiểm thử liên quan

Các test pass trong `tests/test_core.py`: không tự CONFIRMED; mẫu lặp quá gần không được lấy; track xe không liên quan không tính positive; kết thúc theo tổng thời gian event; xe đứng gần ổn định không kích hoạt; hai xe tiến gần tạo trigger; hai tương tác độc lập có thể tạo hai candidate. Integration test chạy video synthetic 36 frame với fake models/storage temp và xác nhận event SUSPECTED/UNCERTAIN cùng trajectory.

**Không kiểm thử** detector thật trên bộ video gán nhãn; không xác minh class mapping ngoài startup check; không thể kết luận precision/recall, tỷ lệ báo giả, khả năng phân biệt ùn tắc với tai nạn hoặc hiệu quả trong che khuất.

## Cảnh báo khi trích tài liệu cũ

Một số tài liệu hiện có (`docs/DETECTION_RULES.md`, `docs/ARCHITECTURE.md`, `docs/TEST_REPORT.md`) mô tả biến thể trước đây, bao gồm tự động CONFIRMED hoặc thông số theo frame. Mã đang có và test hiện tại cho thấy hệ thống không tự xác nhận: tự động chỉ để SUSPECTED/UNCERTAIN, quyết định cuối do người dùng. Không dùng tài liệu cũ làm bằng chứng cho trạng thái hiện tại nếu chưa rà lại.
