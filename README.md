# LC79 • DVK3010 VIP SYSTEM (24/24 Cloud Web + Telegram Admin Bot)

## Cấu trúc thư mục phẳng (1 thư mục duy nhất)
- `app.py`: Máy chủ Backend Python Flask + Proxy ẩn API + Worker chạy nền 24/24 + Telegram Admin Bot.
- `index.html`: Giao diện Quantum Glass (Xác thực Key VIP, Robot AI + Web Game, Phân Tích Trực Tiếp, Auto Phân Tích • Cược MD5).
- `app_client.js`: Mã thực thi giao diện đã được mã hóa bảo mật & ký chống soi nhật ký mạng.
- `requirements.txt`, `Procfile`, `render.yaml`, `.env.example`, `.gitignore`: Cấu hình triển khai trực tiếp lên GitHub & Render.

## Hướng dẫn đưa lên GitHub & Render
1. Tạo repository mới trên **GitHub** và tải toàn bộ các tệp trong thư mục này lên nhánh `main` (giữ nguyên chung 1 thư mục gốc).
2. Đăng nhập **Render.com** -> chọn **New +** -> **Web Service** -> kết nối repository GitHub vừa tạo:
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --workers 1 --threads 8 --bind 0.0.0.0:$PORT --timeout 120`
3. (Khuyên dùng) Thêm biến môi trường `RENDER_EXTERNAL_URL` = URL Render của bạn (VD: `https://ten-app.onrender.com`) để hệ thống tự ping giữ chạy nền 24/24.

## Hướng dẫn sử dụng Bot Telegram Admin
- Mở bot Telegram tương ứng với token đã cấu hình và gửi `/start` hoặc `/admin`.
- Người gửi `/start` đầu tiên sẽ tự động được cấp quyền Chủ Sở Hữu (Admin).
- Các chức năng điều khiển trực tiếp qua nút bấm hoặc lệnh:
  - `/khoa [lý do]` — Khóa toàn bộ Web ngay lập tức.
  - `/mo` — Mở lại Web.
  - `/baotri [nội dung]` — Bật chế độ bảo trì Web.
  - `/vohieuhoa [lý do]` — Vô hiệu hóa Web & dừng các luồng tự động.
  - `/thongbao <nội dung>` — Hiển thị thông báo nổi trực tiếp trên Web.
  - `/xoathongbao` — Xóa thông báo đang hiển thị trên Web.
  - `/status` — Xem trạng thái 24/24 của Engine MD5, TX, Auto Cược & chuỗi thắng thua cao nhất.
