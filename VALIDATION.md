# Kiểm tra MVP — 11/10/2026

## Đã thực hiện tại môi trường phát triển

| Kiểm tra | Kết quả và phạm vi |
|---|---|
| Backend | 26 tests pass: rules, API contract, DynamoDB workflows qua Moto; các API AWS đọc và SES được mock |
| Tách người dùng | JWT sub quyết định tenant; body không chọn được tenant; scan_id của tenant khác trả 404 |
| Phát hiện | Thiếu metrics không phải 0; GetMetricData phân trang và dedup; EBS theo cửa sổ quan sát; kết nối mới không nhận cửa sổ cũ; snapshot được AMI tham chiếu được bỏ qua |
| Quét và email | Invoke Event; tránh quét lại marker hoàn tất; nhả lease khi lỗi transient; email nhận từ Cognito verified attribute; dedup danh sách REVIEW |
| UI Playwright | Demo: đăng nhập mẫu, dashboard, lọc/tìm, bỏ qua, cấu hình, chọn email, giới hạn region, tự cập nhật quét, lịch sử, session hết hạn |
| Layout | Đã xem hình desktop 1440px và mobile 390px; không tràn viewport; bảng mobile kéo ngang |
| JavaScript / Python | node --check app.js; compileall src, demo.py, deploy.py, publish.py pass |
| SAM | sam validate --lint tại ap-southeast-1 pass; sam build thành công cho 3 Lambda Python 3.12 |
| Cấu hình read role | cfn-lint template.yaml và target-role.yaml pass |

Công cụ: Python 3.12, boto3 1.43.111 được pin cho Lambda; botocore 1.43.111; Moto 5.1.17; Playwright 1.63.0; SAM CLI 1.168.0. cfn-lint 1.57.2 dùng cho lượt kiểm tra cuối. SAM CLI có ràng buộc dependencies riêng; đã xử lý xung đột công cụ trong môi trường kiểm tra.

Mock/Moto và UI demo không chứng minh hệ thống đã chạy trên AWS. Chưa có account AWS được kết nối trong phiên này; không tạo tài nguyên cloud và không đo chi phí thực tế. Bản demo hiển thị nhãn dữ liệu mẫu.

## Cần kiểm tra sau deploy AWS thật

1. Cognito đăng ký/xác minh email/PKCE/logout, API Gateway signature/issuer/audience/scope; API chưa đăng nhập phải 401/403, ID token không dùng được.
2. Hai người dùng: cấu hình, kết quả, history, ngoại lệ và scan_id tách biệt; không đọc được dữ liệu người khác.
3. STS: ExternalId sai không kết nối được; đúng role kết nối được; thu hồi role hiển thị FAILED/PARTIAL tùy API thất bại.
4. EC2 thực: CPU/network thấp, có spike, instance mới, thiếu metric; kiểm tra cửa sổ đã chọn và độ phủ.
5. EBS/EIP: lần đầu OBSERVING, đủ thời gian REVIEW, dùng lại sẽ reset, tag giữ lại và ignore được áp dụng.
6. Snapshot tham chiếu AMI/tag/backup không được đánh dấu theo rule; snapshot cũ không tự xóa.
7. Scheduler mỗi giờ chọn tenant đến hạn; quét liên tục bị 429/409; async retry và failure destination nhận đúng sự kiện.
8. SES: sender/recipient verified theo trạng thái account; bật/tắt; thay đổi danh sách REVIEW gửi email; cùng danh sách không gửi lại; lỗi gửi không mất kết quả quét.
9. IAM/CloudFormation quota, CloudFront HTTPS và CORS đúng domain. Kiểm tra tài nguyên/chi phí sau demo và dọn tài nguyên lab.

Chỉ ghi kiểm thử AWS pass vào báo cáo khi đã thực hiện và có bằng chứng thật.
