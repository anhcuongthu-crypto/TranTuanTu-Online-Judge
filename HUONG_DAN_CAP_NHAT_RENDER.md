# Hướng dẫn cập nhật TranTu để lưu dữ liệu bằng PostgreSQL

## Những gì đã sửa

- Ứng dụng dùng PostgreSQL thật khi `DATABASE_URL` là URL `postgres://`, `postgresql://` hoặc `postgresql+psycopg://`.
- SQLite vẫn được hỗ trợ để chạy trên máy và chạy kiểm thử.
- Các phần khởi tạo/cập nhật bảng không còn gọi trực tiếp `sqlite3` khi dùng PostgreSQL.
- Các bảng `users`, `contests`, `contest_problems`, `submissions`, `solves`, `contest_custom_problems` và `problem_history` được tạo/di trú theo backend.
- Việc khởi tạo schema chỉ thêm bảng/cột còn thiếu; không có lệnh `DROP TABLE` hay xóa hàng loạt dữ liệu.

## Cập nhật mã nguồn

1. Giải nén ZIP này.
2. Cập nhật các file trong repo GitHub bằng phiên bản cùng đường dẫn ở ZIP (ít nhất: `app.py`, `oj/database.py`, `oj/history.py`, `oj/job_queue.py`; các thay đổi kiểm thử/tài liệu nằm trong `tests/test_database_standalone.py`, `README.md` và file này).
3. Commit các thay đổi để Render triển khai phiên bản mới.

## Kiểm tra biến môi trường trên Render

- `DATABASE_URL` phải chứa URL kết nối PostgreSQL từ nơi đang lưu database.
- Không đưa URL/mật khẩu database vào file mã nguồn hoặc GitHub.
- Không xóa biến `DATABASE_URL` hiện tại nếu nó đang trỏ tới database có tài khoản học sinh.
- Khi khởi động, log ứng dụng sẽ ghi `Database backend: PostgreSQL` nếu đã nhận diện URL PostgreSQL. Nếu thấy `Database backend: SQLite`, ứng dụng chưa nhận được `DATABASE_URL` theo định dạng PostgreSQL.

## Lưu ý về dữ liệu đang có

Đoạn code này không xóa dữ liệu đã có trong PostgreSQL. Tuy nhiên, nó **không tự sao chép dữ liệu từ một file SQLite cũ sang PostgreSQL**. Nếu tài khoản học sinh chỉ nằm trong SQLite, hãy sao lưu/chuyển dữ liệu đó trước khi chuyển nguồn database; đừng xóa database cũ trong lúc xác minh.

Sau khi deploy, đăng nhập admin, tạo một Contest thử nghiệm, mở `/api/admin/contests` để xác nhận nó xuất hiện, rồi deploy lại một thay đổi nhỏ và kiểm tra Contest vẫn còn.
