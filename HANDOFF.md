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

# Bàn giao Triển khai Nâng cấp Toàn diện — 2026-10-19

## Trạng thái Hiện tại

**Đã hoàn thành triển khai phiên bản mới từ branch `main` lên AWS và thực hiện hậu kiểm thành công.**

- **Website:** https://d3qn9wabid8ws0.cloudfront.net/
- **AWS Account:** `376129867108`, Region `ap-southeast-1`.
- **Hạ tầng chính (`cloud-resource-guardian`):** **UPDATE_COMPLETE**
  - Stack ARN: `arn:aws:cloudformation:ap-southeast-1:376129867108:stack/cloud-resource-guardian/81f52de0-c53a-11f1-8a39-02ffd9f7b9e9`
  - Change Set đã thực thi: `guardian-update-1792342627` (ARN: `arn:aws:cloudformation:ap-southeast-1:376129867108:changeSet/guardian-update-1792342627/681651f2-b35d-40a8-aaf3-3e1669f5f9b1`)
  - Lambda ZIP: `crg-artifacts-376129867108-ap-southeast-1/cloud-resource-guardian/4be15583dbd3478716c1839a79e8d831e497a5ec8d327aae6805353578502851/lambda.zip` (16.715.151 bytes, SHA-256: `4be15583dbd3478716c1839a79e8d831e497a5ec8d327aae6805353578502851`)
  - Bảng DynamoDB: `cloud-resource-guardian-Data-15ID2URED2G6T` (**giữ nguyên 100%, không bị thay thế**)
  - Cognito User Pool: `ap-southeast-1_NwY3bQKBQ` (**in-place update, không thay thế, dữ liệu user giữ nguyên**)
- **Quyền đọc (`guardian-read-role-demo`):** **UPDATE_COMPLETE**
  - Stack ARN: `arn:aws:cloudformation:ap-southeast-1:376129867108:stack/guardian-read-role-demo/4b1fba80-c542-11f1-a054-0affe454644b`
  - Change Set đã thực thi: `guardian-role-update-1792342684` (ARN: `arn:aws:cloudformation:ap-southeast-1:376129867108:changeSet/guardian-role-update-1792342684/94482ecd-05d7-4985-afdc-a7fd62e5e515`)
  - Role ARN: `arn:aws:iam::376129867108:role/GuardianReadRole-demo`
  - ExternalId: `d31fae05-6d60-4f49-9631-ef06d084280f`
  - Chính sách chỉ đọc: Bổ sung quyền đọc `ec2:DescribeNatGateways`, `rds:DescribeDBInstances`, `elasticloadbalancing:DescribeLoadBalancers`, `s3:ListAllMyBuckets`, `s3:ListBucketMultipartUploads`. Tuyệt đối không có quyền stop/terminate/delete/modify.
- **CloudFront & Web Assets:**
  - Distribution ID: `ERUII98HKGJOG`
  - Invalidation: `I51MCIJRTDV31DM63RY9R0AMSB` (**Completed**)
  - Toàn bộ 5 file tĩnh (`index.html`, `styles.css`, `app.js`, `target-role.yaml`, `config.json`) đã upload qua presigned URL ký bởi AWS MCP, khớp byte 100% với nguồn.

## Kiểm thử Thực tế Sau Triển khai

1. **Trạng thái CloudFormation:** Cả 2 stack đạt `UPDATE_COMPLETE` qua kiểm tra AWS MCP `DescribeStacks`.
2. **Frontend Website:** Trả HTTP 200 cho toàn bộ 5 tài nguyên; giao diện mở bình thường, không có lỗi JavaScript console hay tràn ngang tại 1440px và 390px (`tests/ui_live_frontend.py` PASS).
3. **Xác thực Cognito:** Hosted UI mở chính xác với `client_id=6gshdb16lafagprs48q21ifgjm`, scope `openid email aws.cognito.signin.user.admin`, PKCE S256. User `b98a55fc-e061-70f4-04e4-f8298bc94e69` (email `hoangdat2407@gmail.com`) được giữ nguyên trạng thái `CONFIRMED`.
4. **Bảo vệ API (401 Unauthorized):** Toàn bộ 10 route API của API Gateway đều trả HTTP 401 khi không có token Authorization Bearer.
5. **API Feedback:** `GET /feedback` trả HTTP 200 `{"results":[],"next_token":null}`; `PUT /feedback` trả 404 hợp lệ khi finding chưa xuất hiện.
6. **STS AssumeRole:** `PUT /connection` với `RoleArn` và `ExternalId` gọi `sts:AssumeRole` thành công và xác nhận account `376129867108`.
7. **Quét thực tế (Real Scan):**
   - Scan ID: `86219e63-6f56-49b6-9398-0447f53f7809` tại region `ap-southeast-1` bao gồm cả 4 nhóm (`compute`, `storage`, `database`, `network`).
   - Trạng thái kết thúc: `SUCCEEDED`.
   - Kiểm tra đầy đủ 9 dịch vụ: EC2, EBS, SNAPSHOT, S3_MULTIPART, RDS, EIP, NAT_GATEWAY, ALB, NLB.
   - Đã lưu vào DynamoDB tại `RESULT#ap-southeast-1` và lịch sử `HISTORY#...`.
   - API `/findings` và `/history` trả đúng kết quả `SUCCEEDED` với `errors: []`.
8. **Hạ tầng bổ trợ:**
   - **Scheduler:** Lambda `ScheduleFunction` khởi động thành công, trả `queued_tenants: 0`.
   - **SQS DeadLetters:** Hoạt động đúng chuẩn (đã chứng minh bắt message dead-letter khi retry cạn kiệt; không có lỗi mới).
   - **CloudWatch Logs:** Log stream mới `2026/10/19/[$LATEST]a8391534a3bb460b86aac28fd2bb2358` ghi nhận thực thi 4019ms thành công, 0 lỗi, ParamValidationError được giải quyết dứt điểm.
## Giới hạn và các Mục Chưa Kiểm chứng trên Dữ liệu Thật

- **Dữ liệu tài nguyên rỗng:** Region `ap-southeast-1` không có EC2, RDS, EBS, Snapshot thật. Lượt quét trả về `0` cho tất cả các loại tài nguyên. Các rule phát hiện ngưỡng (CPU < 5%, Snapshot > 30 ngày, Volume không gắn > 24 giờ) chưa được kích hoạt trên tài nguyên thực tế.
- **Đã khắc phục lỗi EIP Collector:** Trong `src/collectors.py`, đã bỏ tham số `MaxResults` và vòng lặp NextToken giả trong `eip_addresses()`. Bổ sung xử lý ngoại lệ `BotoCoreError` vào `collect_region`. Đã thêm 2 test mới: unit test xác nhận DescribeAddresses không truyền MaxResults và regression test quét toàn bộ nhóm network (EIP, NAT, ALB, NLB). Change Set `guardian-codefix-1792380950` đã được tạo và thực thi an toàn qua AWS MCP. Quét thực tế trên AWS đạt `SUCCEEDED`.
- **SES:** SES tiếp tục giữ tắt theo yêu cầu.
- **Multi-tenant isolation:** Chưa kiểm thử đồng thời hai người dùng thật có role riêng biệt.
