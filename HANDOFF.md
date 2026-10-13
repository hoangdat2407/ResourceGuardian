# Bàn giao frontend — 2026-10-12

## Trạng thái hiện tại

**Đã publish frontend mới và hậu kiểm thành công.**

- Website: https://d3qn9wabid8ws0.cloudfront.net/
- Account: 376129867108; stack cloud-resource-guardian; region ap-southeast-1.
- WebBucket: cloud-resource-guardian-webbucket-gdgpbgx4t8o5.
- CloudFront: ERUII98HKGJOG; invalidation IA4UB7G1SEGEHDP9HS1YNS9Y2E, đường dẫn /*, **Completed**.
- Invalidation tạo lúc 2026-10-12T02:29:36.183000+00:00; hậu kiểm hoàn tất 2026-10-12T02:32:52.126076+00:00.
- Không phát hiện regression trong phạm vi kiểm thử đã chạy; không cần rollback.

## Phạm vi đã giữ

Backend, API contract, Cognito/PKCE, IAM, rule phát hiện và hạ tầng không thay đổi. SES vẫn tắt. Không tạo tài nguyên thử, không sửa tài nguyên ngoài dự án. web/config.json giữ nguyên bytes/ETag, khớp Outputs thật; không upload config hoặc dữ liệu demo.

Người dùng đã cho phép aws login để xác thực lại. Lệnh thành công với arn:aws:iam::376129867108:user/datht. Sau đó mọi AWS control-plane API đi qua AWS MCP (ClientSession qua proxy stdio chính thức); không dùng AWS CLI/boto3 cục bộ để triển khai. GET/PUT nội dung S3 dùng URL ký do AWS MCP cấp, URL chỉ giữ trong bộ nhớ.

## Thay đổi frontend

- Áp dụng ./skill.md; kế hoạch và tự đánh giá trong FRONTEND-DESIGN.md. Giao diện xanh mực/xanh biển, typography tiếng Việt, điều hướng mobile, keyboard focus và reduced motion.
- Luồng AWS ba bước: hướng dẫn CloudFormation cụ thể, tải template nguyên vẹn, sao chép ApiPrincipal/ScanPrincipal/ExternalId riêng, nhập RoleArn từ Outputs, chọn 1–3 region, xác minh kết nối và quét đầu tiên.
- Dashboard phân biệt chưa đo, đang quét, rỗng thật, partial, lỗi và quá hạn; không dùng 0 cho counts rỗng do đọc thất bại. Hiển thị lỗi và phạm vi từng region.
- Danh sách giữ tìm/lọc/bằng chứng/bỏ qua 7 ngày, mobile có nhãn từng trường. Lịch sử có loading/empty/error/retry và chi tiết lỗi. Cấu hình phản hồi tại form; email vô hiệu hóa khi dịch vụ chưa bật.
- Chỉ upload app.js, styles.css, target-role.yaml, index.html (index cuối); MIME đúng, Cache-Control no-store, SSE AES256. PUT có điều kiện ETag/If-None-Match tránh ghi đè thay đổi ngoài ý muốn.

## Kiểm thử thực tế

### Local demo / fixture

- node --check web/app.js: PASS.
- tests/ui_smoke.py: PASS. Dashboard, lọc/tìm, ignore, settings/email mô phỏng, region validation, polling, history, mobile, phiên hết hạn.
- tests/ui_redesign.py: PASS. Onboarding, clipboard ba trường, template khớp byte, ARN/region sai, lỗi và phục hồi kết nối, payload API, quét đầu một request, QUEUED/RUNNING/FAILED/TIMED_OUT/PARTIAL/SUCCEEDED, counts rỗng/0 thật, 429, outage/retry, SES tắt, text an toàn, focus.
- Năm trang không tràn ngang tại 320/390/768/1440 px; đã xem ảnh desktop/mobile và các trạng thái chính. 23 PNG và acceptance-results.json tại .preflight/ui-redesign/.
- Trước upload đã xác minh gói release và web/ khớp hash bản đã kiểm thử; không sửa mã frontend sau test nên không chạy lại preflight/backend đã xong.

### Website/AWS thật trong lượt publish

- MCP STS GetCallerIdentity: đúng account; DescribeStacks: CREATE_COMPLETE, lấy Outputs mới. GetDistribution: đúng domain và origin WebBucket; ListObjectsV2/HeadObject: lưu metadata cả bốn object cũ.
- Backup trực tiếp S3 trước ghi; đối chiếu lại bytes ngay trước upload. Đọc lại origin sau upload: bốn asset đúng bytes, config nguyên vẹn.
- MCP CreateInvalidation và GetInvalidation: Completed. HeadObject sau publish: đúng kích thước/MIME/cache/encryption; config ETag không đổi.
- tests/ui_live_frontend.py: PASS. HTTPS trả 200 và đúng hash cho index.html/app.js/styles.css/target-role.yaml/config.json. Config thật, không demo.
- Đã kiểm tra và xem bốn screenshot thật: welcome/login ở 1440 và 390 px; không lỗi JavaScript hoặc tràn ngang. Cognito authorize đúng client/redirect, code flow và PKCE S256. Không nhập mật khẩu hoặc gửi form đăng nhập.
- Bằng chứng: .preflight/live-redesign/results.json và bốn PNG; .preflight/mcp-discover-result.json, mcp-inventory-result.json, mcp-invalidation-result.json, mcp-publish-verification.json, publish-state.json.
- Browser tích hợp vẫn lỗi missing field sandboxPolicy; sử dụng Chrome headless với Playwright dự án.

## Backup và rollback

- Backup S3 đã xác minh trước publish: .preflight/s3-backup-20261012T022755Z/ (index.html, app.js, styles.css, config.json, manifest SHA-256/metadata).
- Snapshot HTTPS cũ: .preflight/online-backup-20261011T153200Z/; bản local trước sửa: .preflight/frontend-before/.
- Release đã publish: .preflight/frontend-release-20261011/ và manifest PUBLISHED_VERIFIED. Manifest không upload lên website.
- Nếu sau này xác nhận regression do frontend này: qua AWS MCP kiểm tra lại account/Outputs và trạng thái website để tránh ghi đè release mới; khôi phục ba asset cũ từ backup, giữ config.json, rồi tạo invalidation mới với CallerReference riêng và kiểm tra hash/trình duyệt. target-role.yaml có thể giữ lại vì bản cũ không tham chiếu; không cần xóa object.
- Helper nội bộ .preflight/mcp_frontend_transfer.py rollback chỉ phục hồi các asset đã thay, không tự invalidate. Không chạy lại upload hoặc các script chỉnh sửa một lần.

## Phần chưa được kiểm chứng

Không có phần publish còn chặn. Chưa kiểm thử Cognito đăng nhập/logout hoàn chỉnh sau nhập mật khẩu, AssumeRole qua ứng dụng, worker scan, rule trên tài nguyên AWS thật hoặc multi-tenant thật. Không coi demo/fixture hay trang login là bằng chứng AWS end-to-end. Không bật SES hoặc tạo tài nguyên thử để bổ sung các ca này.

## Lệnh đọc/kiểm thử để tiếp tục

```powershell
$env:CHROMIUM_EXECUTABLE='C:\Program Files\Google\Chrome\Application\chrome.exe'
.\.venv-preflight\Scripts\python.exe tests/ui_live_frontend.py
# Demo local, không truy cập AWS:
.\.venv-preflight\Scripts\python.exe demo.py --port 8080
```

Lịch sử chặn đã xử lý: 2026-10-11 AWS MCP không nạp do xác thực hết hạn; 2026-10-12 người dùng duyệt aws login, đăng nhập thành công và publish hoàn tất. Không cần hỏi lại quyền cho các bước đã hoàn tất.
