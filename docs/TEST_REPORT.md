# Báo cáo kiểm tra

Ngày khảo sát: 2026-10-14, Asia/Bangkok.

- Đọc metadata checkpoint bằng Ultralytics, không sửa trọng số.
- Kiểm tra version runtime, CUDA và GPU NVIDIA GeForce RTX 5060.
- Kiểm tra API `YOLO.track`, persistence và cấu hình `bytetrack.yaml`.
- Nạp được cả hai checkpoint ở CPU; trên một ảnh test 640×640 của dataset, model xe phát hiện `xe_tai` với confidence `0.87044` (một sample chẩn đoán, không phải metric chất lượng). Model accident không phát hiện class `accident` trên ảnh này.
- Ảnh trống trả 0 detections cho cả hai model.
- 5/5 unit test qua; `compileall` và `node --check` qua.
- Localhost smoke check dùng `ATADS_DEVICE=cpu`: health/status/events/config/reports trả dữ liệu và dashboard trả HTTP 200.
- `FastAPI TestClient` không dùng được do môi trường không cài package `httpx2`; endpoint đã được smoke check qua server Uvicorn thật.
- Không có video MP4/AVI/MOV trong workspace để benchmark pipeline end-to-end trên video.
- PyTorch 2.7.1+cu118 cảnh báo RTX 5060 Laptop `sm_120` không tương thích; khởi động bằng device mặc định `0` chủ động dừng với lỗi cấu hình trước inference. CPU diagnostic không sửa config đã lưu.
- PyTorch chính thức hiện liệt kê Windows wheel `torch==2.12.0`, `torchvision==0.27.0` cho CUDA 13.0; `install_cuda_pytorch.bat` yêu cầu xác nhận trực tiếp và kiểm tra `sm_120` sau khi cài.
- FPS và latency thực sẽ hiển thị khi pipeline video chạy; chưa thể báo cáo con số benchmark ở môi trường này.
- Chưa có ground truth nên không đo precision/recall/độ chính xác. Nạp checkpoint không được xem là kiểm thử chất lượng detector.
