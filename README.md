# ATADS — Hệ thống phát hiện tai nạn giao thông tự động

Ứng dụng web cục bộ cho Windows, dùng YOLO phương tiện đã huấn luyện, ByteTrack và YOLO `accident` để sàng lọc video. Video, log, metadata JSON, ảnh và clip bằng chứng nằm trên máy. Ứng dụng không sử dụng database hoặc dịch vụ cloud.

## Trạng thái triển khai

- Upload, giải mã video cục bộ; pipeline có tạm dừng/tiếp tục/dừng.
- Model phương tiện thật với confidence mặc định `0.5` và `YOLO.track(..., tracker="bytetrack.yaml")`; class đọc từ checkpoint.
- Model tai nạn thật, yêu cầu đúng class `accident`; startup lỗi nếu checkpoint/class/CUDA không hợp lệ.
- Phân tích tương tác bbox/quỹ đạo ảnh tạo candidate; cặp track phải đủ quan sát theo thời gian trước khi gọi model accident. Overlap bbox đơn frame không gọi model.
- Xác minh thời gian trên output frame-wise; tín hiệu đủ mẫu chuyển `READY_FOR_REVIEW`, chỉ người duyệt mới đặt `CONFIRMED` hoặc `REJECTED`.
- Queue xác minh giới hạn, ghi nhận mẫu bị bỏ khi quá tải/lỗi inference; crop bao vùng các track liên quan và ghi confidence, frame, timestamp vào event.
- JSON sự kiện bền vững, ảnh JPEG, MP4 nếu codec hỗ trợ; metadata ghi rõ lỗi/thiếu frame.
- Dashboard, track, cảnh báo, thao tác review, tìm kiếm/phân trang, báo cáo, xuất, cấu hình và log gọi API thật.
- Vẽ polygon ROI trên frame xem trước, lưu riêng theo video; áp dụng ROI cho track và trigger nghi ngờ.
- Không có database và không tạo sự kiện demo.

## Khảo sát workspace

- Windows x64, Python 3.10.0; virtualenv `.venv`.
- `.venv`: PyTorch 2.7.1+cu118, CUDA khả dụng, Ultralytics 8.4.160, OpenCV 5.0.0, FastAPI 0.143.0, Uvicorn 0.54.0.
- GPU NVIDIA GeForce RTX 5060, 8,151 MiB VRAM theo `nvidia-smi`.
- Checkpoint xe: `runs/detect/phuong_tien/huan_luyen/weights/best.pt`, class `{0:o_to, 1:xe_bus, 2:xe_khach, 3:xe_may, 4:xe_tai}`.
- Checkpoint tai nạn: `runs/detect/yolo_v11_small_accident/huan_luyen/weights/best.pt`, class `{0:accident}`.
- Ultralytics `YOLO.track` hỗ trợ `persist`; cấu hình `bytetrack.yaml` có trong package. Không dùng API tracker nội bộ.
- Workspace không có video kiểm thử nên chưa benchmark trên cảnh giao thông thực.

## Khởi chạy

1. Nhấp đúp `start_atads.bat`.
2. Chờ hai checkpoint nạp; BAT mở `http://127.0.0.1:8765` khi health endpoint sẵn sàng.
3. Tải MP4/AVI/MOV/MKV/M4V, rồi chọn **Bắt đầu**.
4. Dùng Tạm dừng/Tiếp tục/Dừng. Video được xử lý nhanh nhất theo khả năng phần cứng, không giới hạn để khớp FPS phát lại; camera xử lý theo tốc độ frame camera cung cấp. Đóng cửa sổ terminal để dừng backend.

Để vẽ ROI: tại **Giám sát video**, tải video trước để hiện frame xem trước. Bấm **Vẽ vùng ROI**, bấm ít nhất 3 điểm quanh khu vực cần theo dõi, rồi chọn **Hoàn tất**. Bật **Áp dụng vùng** để lưu và dùng ROI; **Bỏ điểm**, **Hủy vẽ** và **Xóa** dùng để chỉnh sửa. Hãy làm việc này trước khi bấm **Bắt đầu**. ROI theo video được lưu trong `config/roi.json` bằng dấu vân tay nội dung nên tải lại cùng video sẽ lấy lại vùng đã vẽ.

Mặc định chỉ bind localhost. `start_atads.bat` kiểm tra kiến trúc GPU trước khi nạp model. Nếu bạn chấp nhận thay PyTorch hiện tại, chạy riêng `install_cuda_pytorch.bat` và nhập `INSTALL`; script dùng wheel Windows chính thức PyTorch 2.12.0 / CUDA 13.0 rồi xác minh architecture. Hoặc chạy `start_atads_cpu_diagnostic.bat` để chủ động mở dashboard bằng CPU; tốc độ inference có thể rất thấp. Dependency web/runtime còn thiếu được cài bằng `install_dependencies.bat`.

## Model và cấu hình

Đường dẫn mặc định trong `config/settings.json`; có thể sửa từ Cấu hình. GPU mặc định `0`. CUDA không khả dụng sẽ làm backend báo lỗi khởi động; không tự lùi về CPU. Ngưỡng inference, lịch xác minh, luật và giới hạn upload trong `settings.json`/`rules.json`. Đổi model/device khi pipeline chạy bị từ chối. Thay model cần khởi động lại backend.

## Dữ liệu

- Sự kiện: `data/events/AT-*.json`
- Ảnh/clip: `data/evidence/images/`, `data/evidence/videos/`
- Video tải lên: `data/uploads/`
- Camera realtime: webcam USB theo chỉ số thiết bị hoặc URL RTSP/HTTP(S), được mở trên máy chạy backend.
- Xuất: `data/exports/`
- Log: `data/logs/atads.log`

Video upload được giữ để truy vết; có thể dọn thủ công sau khi sao lưu. Không có tự động xóa sự kiện hoặc bằng chứng.

Xem [kiến trúc](docs/ARCHITECTURE.md), [API](docs/API.md), [luật phát hiện](docs/DETECTION_RULES.md), [báo cáo kiểm tra](docs/TEST_REPORT.md).

## Chưa hoàn thành / giới hạn

- Camera realtime dùng thiết bị của máy chạy backend; khi mở giao diện từ máy khác, backend cần truy cập được webcam hoặc camera IP qua mạng.
- Tua video, hồ sơ ROI dùng chung theo tên file, mở thư mục qua Explorer chưa triển khai.
- Chưa benchmark trên video thực hoặc đo precision/recall với ground truth; không tuyên bố FPS/độ chính xác.
- Verifier là luật theo thời gian trên các ảnh YOLO độc lập, không phải model video.
- Timeout xác minh mặc định 3 giây, lấy mẫu mỗi 0.5 giây; không đủ bằng chứng hoặc quan sát kém chuyển `UNCERTAIN`, không tự loại bỏ event.
- Heuristic che khuất cần đánh giá trên clip thực.
- GPU RTX 5060 hiện không chạy với bản PyTorch CUDA 11.8 đang cài (`sm_120` không được hỗ trợ). Dùng CPU chẩn đoán thì hoạt động nhưng chậm; chưa có FPS thực trên video.
