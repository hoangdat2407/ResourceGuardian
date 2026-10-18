# Kiểm tra MVP

## Mục 7 — luật đánh giá và bằng chứng, 18/10/2026

Kiểm tra trên nhánh `duc`, Python 3.12.14 trong `.venv`. Phạm vi mới là bốn rule EC2/EBS/EIP/snapshot, bằng chứng, API giữ lại nội bộ và cửa sổ EC2 24–168 giờ. Dữ liệu AWS đọc và SES được mock; DynamoDB được mô phỏng bằng Moto. Không gọi AWS thật, không triển khai hoặc thay đổi tài nguyên cloud.

| Kiểm tra | Kết quả thực tế |
|---|---|
| Toàn bộ backend | **71/71 unittest PASS** sau sửa lỗi audit: 32 rule, 13 API, 26 workflow; giữ các ca hồi quy và bổ sung 45 test so với bộ 26 test cũ |
| Rule EC2 | Mốc 80% tại 24/168 giờ, zero thật, thiếu metric, NaN/inf/âm/boolean/kiểu sai, spike và bằng ngưỡng; network tính trên số giờ thực đo từng chiều khi số mẫu bằng/khác nhau; instance mới không bị kết luận ít hoạt động; bằng chứng không chứa tuổi âm hoặc số không hữu hạn |
| EBS/EIP và ngoại lệ | Trước/đúng ngưỡng giờ, dùng lại, gap đúng/trên 48 giờ; tag/keep/ignore chặn finding nhưng vẫn theo dõi trạng thái sử dụng; ignore hết hạn đúng timestamp |
| API keep và lưu trữ | Bật/tắt idempotent, từ chối body/kết nối sai, tenant từ JWT sub, ngoại lệ tách tenant/connection; bỏ keep không vô hiệu hóa tag/ignore |
| Snapshot và finding | AMI bị cắt/AccessDenied tạo PARTIAL; IncludeDisabled=True bảo vệ snapshot được AMI bị vô hiệu hóa tham chiếu, snapshot không tham chiếu vẫn được xét; cả bốn loại finding giữ trường cũ cùng rule_id/recommendation qua DynamoDB, findings, scan cũ và history |
| Cấu hình số nguyên cực lớn | Cả sáu trường nhận ±10**400 đều bị từ chối bằng ValueError/HTTP 400, không ghi DynamoDB và không còn OverflowError |
| UI smoke | **PASS** với demo cục bộ: mặc định 24 giờ, lưu/tải lại 168 giờ, chặn 23/169 giờ; dashboard, lọc, ignore, email demo, polling, lịch sử, mobile và phiên hết hạn |
| UI acceptance | **PASS** với fixture cục bộ: finding có trường bổ sung; onboarding/download, trạng thái quét, lỗi/retry, SES tắt; năm trang không tràn ngang ở 320/390/768/1440 px, không pageerror |
| Cú pháp | AST parse cả 12 file Python; `node --check web/app.js`: PASS |
| Template | cfn-lint 1.57.2 cho template.yaml và target-role.yaml tại ap-southeast-1: PASS, không lỗi/cảnh báo; route PUT /keep dùng authorizer mặc định |
| Dependencies và diff | uv pip check: 35 package tương thích; git diff --check: PASS |

Dependencies chính: boto3 1.43.111, botocore 1.43.114, Moto 5.1.17, Playwright 1.63.0, PyYAML 6.0.3. Browser test dùng Chrome cài trên máy. Lượt acceptance đầu bị `Download.path: canceled`; đã đặt downloads_path trong thư mục QA và chạy lại toàn bộ acceptance thành công. Không thay frontend để xử lý lỗi tải file của môi trường test.

Sau audit, đã bổ sung năm test hồi quy cho ba lỗi: AMI bị vô hiệu hóa, network bị giảm trung bình do giờ thiếu và số nguyên cấu hình quá lớn. Test mới tái hiện FAIL/OverflowError trên mã trước sửa, rồi PASS sau sửa. Lượt kiểm tra cuối chạy lại toàn bộ 71 backend test, UI smoke, cú pháp Python/JavaScript và diff check. UI acceptance, lint template và dependency check ở bảng trên là kết quả lượt trước với các phần tương ứng giữ nguyên. Log backend cuối ở `.preflight/rules-fixes/backend-tests.log`, ảnh smoke ở `.preflight/rules-fixes/ui-smoke/`.

Artifacts cục bộ, đã được .gitignore loại trừ: `.preflight/rules-ui-smoke/`, `.preflight/rules-ui-redesign/acceptance-results.json` và ảnh QA. Đã xem ảnh trang cấu hình ở desktop 1440 và mobile 390 px. Traceback Throttling trong unittest là lỗi được chủ động mô phỏng để xác minh retry, test tương ứng PASS.

Lệnh chạy lại sau khi cài requirements-dev.txt:

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s tests -v
$env:CHROMIUM_EXECUTABLE='C:\Program Files\Google\Chrome\Application\chrome.exe'
$env:UI_QA_DIR=Join-Path (Get-Location) '.preflight\rules-ui-smoke'
.\.venv\Scripts\python.exe -X utf8 -B tests/ui_smoke.py
$env:UI_QA_DIR=Join-Path (Get-Location) '.preflight\rules-ui-redesign'
.\.venv\Scripts\python.exe -X utf8 -B tests/ui_redesign.py
.\.venv\Scripts\cfn-lint.exe template.yaml target-role.yaml --regions ap-southeast-1
node --check web/app.js
git diff --check
```

Chưa kiểm chứng route keep được triển khai trên API Gateway thật, Cognito/JWT thật, STS/IAM, metric thật trong 168 giờ, lịch quét hoặc SES thật. Không coi unit/Moto/UI fixture là AWS end-to-end. Nút giữ lại trên dashboard và collector/rule cho các nhóm dịch vụ khác thuộc các giai đoạn tiếp theo; hợp đồng bàn giao ở RULES.md.

## Kết quả lịch sử — 11/10/2026

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
