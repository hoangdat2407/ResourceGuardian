# Bắt đầu trên Windows

1. Giải nén `Cloud-Resource-Guardian-MVP.zip`.
2. Cài Python 3.12, mở PowerShell trong thư mục `Cloud-Resource-Guardian-MVP`.
3. Xem demo ngay:

```powershell
python demo.py
```

Mở http://127.0.0.1:8080 và chọn Mở dashboard demo. Dữ liệu mẫu, không dùng AWS.

4. Khi sẵn sàng triển khai thật, cài AWS CLI v2 cập nhật rồi tự đăng nhập:

```powershell
aws login --profile guardian-lab
aws configure set region ap-southeast-1 --profile guardian-lab
aws sts get-caller-identity --profile guardian-lab
```

IAM identity cần hỗ trợ đăng nhập local development. Nếu dùng Identity Center, dùng `aws configure sso` / `aws sso login`. Xem README mục 3.

5. Cài dependencies rồi tạo platform:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-deploy.txt
.\.venv\Scripts\python.exe deploy.py --profile guardian-lab --region ap-southeast-1 --domain-prefix crg-cloudt9-CHUOI-RIENG
```

Thay CHUOI-RIENG bằng chữ thường và số độc nhất. Lệnh deploy tạo tài nguyên AWS có thể tính phí; kiểm tra đúng account lab trước khi chạy. Muốn xem change set trước, thêm `--plan` (vẫn upload artifact nhưng chưa thực thi hạ tầng ứng dụng).

6. Mở WebUrl được in ra, đăng ký/xác minh email. Tạo read role bằng `target-role.yaml` theo hướng dẫn trong web và README mục 4, rồi bấm Quét ngay.

Không gửi mật khẩu, access key, secret, session token hoặc MFA vào chat. Chỉ cần chia sẻ thông báo lỗi và Account/ARN từ get-caller-identity nếu muốn được hỗ trợ; các thông tin đó không cấp quyền truy cập.
