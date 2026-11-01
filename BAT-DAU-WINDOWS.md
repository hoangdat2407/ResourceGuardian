# Bắt đầu trên Windows

1. Clone repository hoặc giải nén source, rồi mở PowerShell tại thư mục chứa `demo.py`, `src/` và `web/`.
2. Cài Python 3.12, kiểm tra `python --version`. Nếu có nhiều phiên bản, dùng đúng executable 3.12 hoặc `py -3.12` khi đã đăng ký với Python Launcher.
3. Xem demo ngay, không cần AWS hoặc dependencies bên ngoài:

```powershell
python demo.py
```

Mở http://127.0.0.1:8080 và chọn Mở dashboard demo. Dữ liệu mẫu nằm trong RAM; Ctrl+C để dừng. Kiểm tra local bằng venv, backend suite và browser theo [README mục 7](README.md#7-kiểm-thử); đặt `CRG_AWS_E2E=0` trong phiên local.

4. Khi sẵn sàng triển khai thật, cài AWS CLI v2 cập nhật rồi tự đăng nhập:

```powershell
aws login --profile guardian-lab
aws configure set region ap-southeast-1 --profile guardian-lab
aws sts get-caller-identity --profile guardian-lab
```

IAM identity cần `SignInLocalDevelopmentAccess` cho cách đăng nhập này; phiên đăng nhập vẫn cần quyền triển khai riêng. Nếu nhóm dùng Identity Center, thay bước `aws login` bằng `aws configure sso --profile guardian-lab` rồi `aws sso login --profile guardian-lab`. Xem [README mục 3](README.md#3-triển-khai-trên-aws--windows--powershell), xác nhận cách truy cập với người quản lý AWS nếu chưa rõ.

5. Tạo venv Python 3.12 nếu chưa có, hoặc dùng lại môi trường đúng phiên bản; cài dependencies triển khai:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-deploy.txt
```

Nếu venv báo thiếu pip, chạy `.\.venv\Scripts\python.exe -m ensurepip --upgrade` trước lệnh cài dependencies. Làm theo [DEPLOYMENT.md](DEPLOYMENT.md): đóng gói offline → review/pin ZIP → tạo change set bằng `--artifact ... --plan` trên đúng stack thử → reviewer duyệt → executor thực thi → upload template read role và publish web. `--plan` vẫn ghi AWS; `deploy.py` không có cờ này sẽ tự execute và publish.

6. Admin tạo user Cognito trong đúng UserPool của stack, tối đa 5 user nội bộ. Mở WebUrl được in ra, đăng nhập bằng tài khoản được cấp và đổi mật khẩu tạm nếu được yêu cầu; ứng dụng tắt tự đăng ký. Tạo read role bằng `target-role.yaml` theo hướng dẫn trong web và [README mục 4](README.md#4-kết-nối-aws-account-cần-quét), rồi bấm Quét ngay. SES giữ tắt trong nghiệm thu hiện tại.

Không gửi mật khẩu, access key, secret, session token hoặc MFA vào chat. Chỉ cần chia sẻ thông báo lỗi và Account/ARN từ get-caller-identity nếu muốn được hỗ trợ; các thông tin đó không cấp quyền truy cập.
