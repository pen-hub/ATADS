# Luật phát hiện và xác minh

1. YOLO phương tiện + ByteTrack chạy theo frame. Detection có bbox, class ID/name, confidence và track ID.
2. `SuspicionAnalyzer` tạo dấu hiệu tiến gần/đổi hướng từ detection quan sát thật. Bbox overlap một frame không mở event.
3. `Pipeline._advance_pair_candidates` quản lý từng cặp ID ổn định. Cặp phải được quan sát đủ 3 lần qua ít nhất 0.6 giây, hai track có ít nhất 3 vị trí quan sát lịch sử và observation còn mới; gate cần motion closing/suspicion hoặc overlap mạnh (>= 2× IoU threshold). Tham số nằm trong `config/rules.json`.
4. Chỉ khi cặp qua gate, pipeline tạo event và đưa crop chứa hai xe cùng vùng đệm vào queue xác minh. Các frame sau lấy mẫu mỗi `verification_interval_seconds`; candidate/event được cooldown để tránh gọi lặp. Queue đầy được ghi thành thiếu bằng chứng.
5. `EventVerifier` lấy mẫu theo `verifier_sample_interval_seconds`, đếm output class `accident` vượt `verifier_min_confidence` trong cửa sổ 3 giây. Đủ `verifier_min_positive_frames` với các track liên quan được quan sát sẽ thành `READY_FOR_REVIEW`; chỉ reviewer mới quyết định `CONFIRMED`/`REJECTED`. Timeout 3 giây chuyển `UNCERTAIN`.
6. Thiếu detection của bất kỳ track liên quan nào được ghi thành observation quality kém; không tính như bằng chứng âm. Mẫu, crop, timestamp/frame, detections, queue drop và inference error được lưu cho truy vết.

## ROI

ROI là polygon tọa độ chuẩn hóa `[0,1]` được lưu trong `config/roi.json` theo SHA-256 nội dung video, có thể dùng lại khi tải lại cùng video. Video đổi độ phân giải vẫn giữ vị trí tương đối. Detector và ByteTrack vẫn xử lý toàn frame để không mất xe ở biên; sau đó chỉ detection có tâm bbox trong polygon được hiển thị và chuyển cho suspicion analyzer. YOLO accident tiếp tục nhận toàn frame. ROI chỉ giới hạn vùng phân tích phương tiện, không phải bằng chứng tai nạn.

Không suy ra km/h từ pixel/giây. Cần hiệu chuẩn camera/mặt phẳng đường. Giá trị mặc định chưa được tối ưu trên ground truth.
