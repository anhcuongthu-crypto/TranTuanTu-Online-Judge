# OJ Studio — Online Judge (bản đang phát triển)

Giao diện luyện lập trình bằng tiếng Việt, Flask + SQLite, chấm qua Judge0, có lịch sử nộp bài, bảng xếp hạng, hồ sơ học sinh và module admin riêng.

## Chức năng có trong mã nguồn
- Danh sách 500 bài, tìm kiếm theo mã/tên/chủ đề; trang bài có Input/Output, ví dụ, giải thích, giới hạn và subtasks.
- Đăng ký với username duy nhất; mật khẩu được băm. Tài khoản mới ở trạng thái chờ duyệt, cần liên hệ Trần Tuấn Tú và được admin phê duyệt trước khi đăng nhập.
- Đăng nhập/đăng xuất, hồ sơ với giới thiệu và màu avatar.
- Nộp C++ qua Judge0, chấm từng test theo subtask, lưu mã nguồn/lịch sử/chi tiết verdict; cập nhật điểm tốt nhất vào bảng xếp hạng.
- Khu vực admin tại `/admin`, duyệt tài khoản; API admin thêm/sửa/xóa bài được tách trong `oj/admin.py` và các route admin của `app.py`.
- `/health` báo tình trạng tải ngân hàng đề.

## Cài đặt và chạy local
Yêu cầu Python 3.10+ và kết nối mạng để cài thư viện:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
```

Thiết lập biến môi trường trước khi chạy. Sao chép `.env.example` thành `.env` rồi nạp các giá trị bằng công cụ môi trường của bạn; Flask không tự đọc `.env` nếu chưa cài/cấu hình dotenv. Ít nhất cần:

- `SECRET_KEY`: chuỗi bí mật ngẫu nhiên, không dùng giá trị mẫu khi triển khai.
- `ADMIN_USERNAME` và `ADMIN_PASSWORD`: thông tin bootstrap admin.
- `JUDGE0_URL`: URL của instance Judge0 hoạt động; thêm `JUDGE0_API_KEY` nếu instance yêu cầu.
- `DATABASE_PATH`: đường dẫn DB SQLite có quyền ghi.

Khởi động:

```bash
python -m flask --app app run
```

Mở `http://127.0.0.1:5000`. Không chạy `--debug` trên máy chủ công khai. Khi admin đăng nhập, mở `/admin` để duyệt học sinh. Không chia sẻ mật khẩu admin hoặc `SECRET_KEY`.

## Judge0
Mặc định `JUDGE0_URL=https://ce.judge0.com` và language ID `54` (C++ GCC 9.2.0). Dịch vụ công khai có thể giới hạn tần suất, thay đổi chính sách hoặc không truy cập được từ một số mạng. Nộp bài thật chỉ hoạt động khi endpoint cấu hình đúng và có thể truy cập; test mô phỏng không thay thế kiểm thử end-to-end.

## Kiểm thử
```bash
python -m pytest -q
```

`tests/test_problem_bank_reference.py` đối chiếu 2.500 test dữ liệu với lời giải tham chiếu độc lập. Các test route cần Flask được cài từ `requirements.txt`; test kết nối Judge0 thật cần endpoint có thể truy cập.

## Lưu ý quan trọng về ngân hàng đề
500 bài hiện tại là bộ luyện tập thuật toán tổng hợp, gồm 61 dạng mô tả khác nhau được lặp theo mức độ, không phải 500 đề thi chính thức được xác minh nguồn từ các tỉnh. Các ví dụ và giải thích được sinh từ test của từng bài và lời giải tham chiếu. Mỗi bài hiện có một subtask 100 điểm với 5 test; chưa có phân chia nhiều subtask theo giới hạn dữ liệu kiểu đề HSG chính thức. Hãy xem đây là nền tảng để tiếp tục biên soạn, không phải ngân hàng đề thi chính thức đã được thẩm định.

## Database on Render (PostgreSQL)

The application supports SQLite for local development/tests and PostgreSQL for a persistent hosted database. On Render, set the environment variable `DATABASE_URL` to the PostgreSQL connection URL from your managed database provider. The application logs `Database backend: PostgreSQL` at startup when it recognizes a PostgreSQL URL; the connection URL itself is not logged.

The schema initializer creates missing tables and adds known missing columns in place. It does not drop tables or delete account/contest rows. The existing application data in a SQLite file is **not automatically copied** into PostgreSQL just by setting `DATABASE_URL`; back up and migrate any records that exist only in the old SQLite database before switching storage. Never commit the database URL, password, or API tokens to this repository.

