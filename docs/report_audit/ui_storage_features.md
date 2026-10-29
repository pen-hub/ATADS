# Giao diện, lưu trữ và chức năng

- **Ngày khảo sát:** 2026-10-15 (Asia/Bangkok)
- **Phạm vi:** Kiểm tra HTML/JS/CSS, route API, persistence và evidence code.
- **Giới hạn:** UI/route được xác minh tĩnh. Chưa có browser end-to-end hoặc kiểm thử camera/video thật trong ứng dụng của audit này; ghi `CODE_VERIFIED` riêng với `RUNTIME_VERIFIED`.

## Kiến trúc giao diện và kết nối

Frontend là HTML/CSS/JavaScript thuần trong `frontend/`, không thấy framework SPA. `frontend/js/app.js` dùng `fetch` REST, WebSocket `/api/ws` và `img` MJPEG stream. Backend FastAPI phục vụ static assets và API; BAT dùng Uvicorn loopback 127.0.0.1.

## Ma trận chức năng

| Chức năng | Có trong code | Đã chạy thực tế trong audit | Kết quả / bằng chứng |
|---|---|---|---|
| Tổng quan/status/model | Có | Chưa qua browser; runtime import/CUDA có kiểm tra | `/api/status`, `/api/health`; HTML dashboard |
| Tải video | Có | Chưa thử endpoint/browser; pipeline synthetic integration test | `/api/videos/upload`, `uploadVideo`; size/extension/decode checks |
| Webcam | Có | Probe OpenCV độc lập trong phiên trước đọc được webcam index 1; app đầy đủ chưa | UI webcam indexes; `Pipeline._read_camera` mở CAP_DSHOW |
| Camera IP RTSP/HTTP(S) | Có | Chưa | UI URL + validation/backend FFmpeg source |
| Start/pause/resume/stop | Có | Pipeline synthetic start/stop đã TEST_VERIFIED; API/browser chưa | `/api/pipeline/start`, action route, state machine |
| Detection bbox/track ID | Có | Test integration fake-model; model thật chưa benchmark ở đây | `ModelManager`, `_draw`, stream |
| ROI | Có | Unit test filter center and config ROI persistence | UI ROI vẽ video; `/api/roi/{source_key}`; filter tâm bbox |
| Quỹ đạo/hướng | Có | Unit tests trajectory bounds/gap/reset/direction | `TrajectoryTracker`, visualization API/UI |
| Cảnh báo và duyệt | Có | Unit + synthetic pipeline tests | SUSPECTED/UNCERTAIN; manual CONFIRMED/REJECTED |
| Ảnh/clip bằng chứng | Có | Code path đã đọc; clip thật/codec chưa thử | JPEG và `EvidenceBuffer` MP4V trước/sau |
| Sự kiện/lịch sử/tìm kiếm | Có | Lưu/đọc/review test; browser chưa | event JSON, pagination/filter endpoints |
| Xuất CSV/JSON | Có | CSV header test; JSON route/code | `LocalStorageService.export_events`, `/api/export/{kind}` |
| Cấu hình model/rules/device | Có | Logic validate/persist một phần test; chưa thay cấu hình app thật | GET/PUT config; đổi model/device yêu cầu restart |
| Thông số hệ thống | Có | Chưa UI | CPU/RAM/GPU, source/process FPS, latency, model inference, queue |
| Log/vận hành | Có | Chưa UI | file `data/logs/atads.log`, logs endpoint |

## Lưu trữ và dữ liệu

`LocalStorageService` dùng thư mục local `data/` (theo `data_dir` tương đối trong config) gồm `events/` JSON mỗi event, `evidence/images/` JPEG, `evidence/videos/` MP4, `exports/` CSV/JSON, `logs/` log text; uploads vào `data/uploads/`. Không thấy SQLite/ORM trong luồng được kiểm tra. Event JSON ghi atomic bằng file tạm và `os.replace`; lock đồng bộ trong process.

Video evidence buffer mặc định giữ 5 giây trước + 5 giây sau, sample tối đa 12fps. Nếu nguồn kết thúc sớm thì ghi clip một phần và thêm mã `post_event_window_incomplete`; nếu không đủ frame/codec thì ghi lý do.

## Bảo mật và vận hành — những gì mã thể hiện

- BAT bind Uvicorn vào `127.0.0.1`, phù hợp chạy cục bộ theo mặc định; chưa khảo sát triển khai LAN/Internet.
- Upload dùng ID tạo bởi server và giới hạn extension/size; đường dẫn upload được kiểm tra nằm dưới thư mục uploads.
- API cấu hình, event review và dữ liệu cục bộ không có xác thực người dùng/role trong route được đọc; nếu bind ra mạng thì cần đánh giá bảo vệ bổ sung.
- Không đọc `.env`; `.env.example` chỉ là mẫu cấu hình không bí mật nếu cần xem.
- File event/image/video/export có thể chứa dữ liệu nhạy cảm về camera; chính sách retention/xóa không được chứng minh từ các route được kiểm tra.

## Những gì phải kiểm tra sau

1. Khởi động BAT, chờ `/api/health`, xác nhận hai checkpoint nạp và giao diện có model class/device đúng.
2. Chạy clip cục bộ đã biết codec; theo dõi hết nguồn, kiểm tra event/image/clip và không có traceback.
3. Chạy webcam đúng index, tối thiểu 10 phút; rút/cắm lại để xác nhận hành vi lỗi/reconnect hiện tại.
4. Chạy RTSP hợp lệ trên cùng mạng; đo time-to-first-frame, drop, latency và hành vi ngắt kết nối.
5. Thử review event, restart backend rồi đối chiếu trạng thái; thử CSV/JSON với dữ liệu test đã ẩn thông tin nhạy cảm.
