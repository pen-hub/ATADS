# API cục bộ

Base URL `http://127.0.0.1:8765`; Swagger tại `/docs`.

| Method | Path | Mục đích |
|---|---|---|
| GET | `/api/health`, `/api/status` | Backend, model, GPU, metrics |
| POST | `/api/videos/upload` | Multipart upload và kiểm tra decode |
| GET | `/api/videos/{upload_id}/preview` | Frame đầu để đặt polygon ROI |
| GET/PUT | `/api/roi/{source_key}` | Đọc/lưu ROI theo SHA-256 nội dung video; dùng lại khi tải lại cùng video |
| POST | `/api/pipeline/start` | Video: `{ "source_type": "video", "upload_id": "<id upload>", "roi_key": "<SHA-256 trả về khi upload>" }`; webcam: `{ "source_type": "camera", "camera_source": "0" }`; camera IP: `{ "source_type": "camera", "camera_source": "rtsp://..." }` |
| POST | `/api/pipeline/pause`, `/resume`, `/stop` | Điều khiển nguồn |
| GET | `/api/pipeline/status`, `/frame` | Trạng thái/ảnh mới nhất đã phân tích |
| GET | `/api/pipeline/stream` | MJPEG stream frame mới theo thời gian thực |
| WS | `/api/ws` | Metrics, event, verification, lỗi |
| GET | `/api/events` | Tìm kiếm, lọc, phân trang |
| GET/PATCH | `/api/events/{id}` | Chi tiết; `{status, notes}` |
| GET | `/api/events/{id}/evidence/{image|video}` | Bằng chứng trong data root |
| GET | `/api/export/{csv|json}` | Xuất sự kiện |
| GET/PUT | `/api/config` | Đọc/cập nhật cấu hình đã validate |
| GET | `/api/logs`, `/api/reports` | Log và thống kê |

Frontend cùng origin nên không dùng CORS wildcard. Upload tối đa mặc định 1 GB. BAT bind `127.0.0.1`.
