# Cloud Resource Guardian — triển khai AWS

> **Frontend mới đã publish 2026-10-12:** hậu kiểm PASS, CloudFront invalidation `IA4UB7G1SEGEHDP9HS1YNS9Y2E` Completed. Website https://d3qn9wabid8ws0.cloudfront.net/. Thông tin triển khai 2026-10-11 bên dưới là lịch sử; xem mục release frontend cuối file.

Ngày: 2026-10-11. Account `376129867108`, region `ap-southeast-1`.

## Kết quả

- Stack `cloud-resource-guardian`: **CREATE_COMPLETE**.
- WebUrl: https://d3qn9wabid8ws0.cloudfront.net/
- API: https://l2qn7i2en9.execute-api.ap-southeast-1.amazonaws.com
- CloudFront `ERUII98HKGJOG`: **Deployed**.
- Invalidation `ICO1D944JV9LKPSTZHTX1WTZ72`: **Completed**.
- SES tắt, `SenderEmail` và Lambda `SES_SENDER` rỗng.
- Worker không đặt ReservedConcurrentExecutions; ba Lambda chia sẻ quota account 10.

Stack ARN: `arn:aws:cloudformation:ap-southeast-1:376129867108:stack/cloud-resource-guardian/81f52de0-c53a-11f1-8a39-02ffd9f7b9e9`.

Change set `guardian-mcp-20261011-initial`: 32 thay đổi **Add**, không Modify/Remove, không SES/EC2/EBS/EIP/snapshot. DescribeEvents không trả VALIDATION_ERROR; kiểm tra đúng phạm vi trước ExecuteChangeSet. Không thay đổi tài nguyên có sẵn ngoài dự án. Artifact bucket được tạo mới ngoài stack.

Mọi AWS control-plane API đi qua AWS MCP. Upload ZIP và frontend bằng HTTPS PUT vào URL ký do AWS MCP cấp. Không dùng AWS CLI hoặc chạy deploy.py/publish.py. Không lưu presigned URLs/credentials.

## Tài nguyên bàn giao

| Thành phần | ID/ARN |
|---|---|
| Artifact bucket | crg-artifacts-376129867108-ap-southeast-1 |
| Web bucket | cloud-resource-guardian-webbucket-gdgpbgx4t8o5 |
| DynamoDB | cloud-resource-guardian-Data-15ID2URED2G6T |
| Cognito user pool | ap-southeast-1_NwY3bQKBQ |
| Cognito client | 6gshdb16lafagprs48q21ifgjm |
| Cognito domain | https://crg-376129867108-ap-southeast-1.auth.ap-southeast-1.amazoncognito.com |
| API principal | arn:aws:iam::376129867108:role/cloud-resource-guardian-ApiRole-So7rB7aEKrFT |
| Scan principal | arn:aws:iam::376129867108:role/cloud-resource-guardian-ScanRole-oykltlddshRl |
| API Lambda | cloud-resource-guardian-ApiFunction-b3gqpsw3XEW6 |
| Worker Lambda | cloud-resource-guardian-WorkerFunction-WjbONL4eaYdT |
| Scheduler Lambda | cloud-resource-guardian-ScheduleFunction-LyoJCcdNDe6l |
| EventBridge rule | cloud-resource-guardian-ScheduleFunctionTick-6DUukkwRN7Mw |
| Failure queue | https://sqs.ap-southeast-1.amazonaws.com/376129867108/cloud-resource-guardian-DeadLetters-Dq7qdXMYHQ9d |

Lambda ZIP key: `cloud-resource-guardian/a5cae9d7368234308e4ef7078cd3ad0e79b2c208739cff84843c0c7f744c2db5/lambda.zip`. SHA-256 như key; Lambda CodeSha256 khớp. ZIP 16.656.699 byte, S3 HeadObject xác nhận AES256 và đúng kích thước.

## Kiểm tra đã chạy

| Kiểm tra | Bằng chứng/kết quả |
|---|---|
| Local template sau sửa | cfn-lint: 0 lỗi/cảnh báo |
| HTTPS frontend | config.json/index.html/app.js/styles.css HTTP 200; ba static file khớp bytes với nguồn |
| Cấu hình web | Dùng endpoint thật, không demo; redirect đúng WebUrl |
| Giao diện | Trang chào và form Cognito hiển thị; không có pageerror |
| OAuth request | response_type=code, PKCE S256, client_id/redirect_uri đúng |
| API protection | GET /me không token và token giả đều 401 |
| CORS | Origin WebUrl được phép, preflight 204; origin khác không được trả Allow-Origin |
| S3 privacy | Bốn PublicAccessBlock=true; GET index.html trực tiếp không ký trả 403 |
| API routes | Cả 9 route dùng JWT authorizer và scope openid |
| Worker | Active, Python 3.12/x86_64, 256 MB, 300s; không reserved concurrency; SES tắt |
| Async config | 2 retries, max event age 600s, SQS OnFailure đúng queue dự án |
| Lambda API khởi động | Invoke qua MCP với request không identity trả payload statusCode=401, không FunctionError |
| Scheduler khởi động | Invoke qua MCP với dữ liệu chưa có tenant trả queued_tenants=0, không FunctionError |
| EventBridge | ENABLED, rate(1 hour); chưa chờ chứng minh tick định kỳ thực tế |

Ảnh cục bộ: `.preflight/live-welcome.png`, `.preflight/live-login.png`. Script kiểm tra: `.preflight/check_live.py`. Browser tích hợp lỗi môi trường `missing field sandboxPolicy`; đã dùng Chrome headless cục bộ để kiểm tra. Lượt browser test đầu chọn nhầm password input ẩn của Cognito; sửa selector test sang input hiển thị, chạy lại pass; không sửa frontend vì lỗi test đó.

Kiểm thử preflight 26/26 backend và UI demo đã pass trước triển khai (xem PREFLIGHT.md). Không coi mock/demo là bằng chứng AWS end-to-end.

## Bước người dùng cần làm

1. Mở WebUrl, chọn đăng nhập. Nếu chưa có tài khoản, dùng Sign up của Cognito và xác minh email trực tiếp trên Cognito. Không gửi mật khẩu, mã xác minh, access key hoặc token vào cuộc trò chuyện.
2. Sau đăng nhập, mở Kết nối AWS. Với role đã tạo riêng cho người dùng này, dùng RoleArn từ Outputs của stack read-role đã ghi bên dưới; không tạo lại stack đang có.
3. Với account/người dùng mới, dùng target-role.yaml, ApiPrincipal, ScanPrincipal và ExternalId của chính người dùng đó để tạo read role bằng CloudFormation. Hướng dẫn chi tiết và nút tải/sao chép đã có trên website từ bản frontend ngày 2026-10-12.
4. Nhập RoleArn, chọn region có tài nguyên (ví dụ ap-southeast-1), chọn Kiểm tra và lưu kết nối, rồi Quét ngay. Kết quả rỗng chỉ chứng minh luồng nếu thật sự hoàn tất; không xác minh rule trên tài nguyên thật.

Không cần gửi ExternalId lại cho agent để dùng luồng tự kết nối. Nếu dùng GuardianReadRole-demo đã có, trust policy phải khớp ExternalId của người dùng đang đăng nhập.

## Chưa thực hiện / không tuyên bố pass

- Read-role stack đã tạo ở bước tiếp theo bên dưới; kết nối/quét qua ứng dụng chưa được kiểm chứng trong phiên tạo role.
- Chưa đăng ký/xác minh email, đổi authorization code lấy token, login/logout hoàn chỉnh hoặc kiểm tra hai tenant thật.
- Chưa kết nối account bằng read role, chưa chạy worker scan account (kể cả inventory rỗng), chưa kiểm tra wrong ExternalId/revoked role.
- Scheduler empty-tenant chỉ chứng minh khởi động và đọc bảng; không phải kiểm tra quét account.
- Không tạo EC2/EBS/EIP/snapshot thử. Sau này scan account rỗng pass chỉ chứng minh luồng xử lý, không xác minh rule trên tài nguyên thật.
- Chưa kiểm chứng retry/failure destination bằng fault injection, tick lịch thật, metrics/time window, SES, tải hoặc compliance cfn-guard.

Chi phí dịch vụ bắt đầu có thể phát sinh từ tài nguyên đã tạo và các kiểm tra. Giới hạn bảo vệ dữ liệu/chi phí và phạm vi MVP giữ như PREFLIGHT.md đã duyệt. Skill aws-cloudformation được dùng để rà soát change set/validation và ghi lý do bỏ reserved concurrency trong template/README; không đổi kiến trúc.

## Hoàn tất read role — 2026-10-11

Theo yêu cầu tiếp theo của người dùng, đã triển khai nguyên bản `target-role.yaml` qua AWS MCP, RoleSuffix=demo, với hai principal và ExternalId do người dùng cung cấp. STS xác nhận đúng account. Trước khi tạo, DescribeStacks trả stack không tồn tại và GetRole trả NoSuchEntity; không cập nhật role có sẵn.

- Stack `guardian-read-role-demo`: **CREATE_COMPLETE**.
- Stack ARN: `arn:aws:cloudformation:ap-southeast-1:376129867108:stack/guardian-read-role-demo/4b1fba80-c542-11f1-a054-0affe454644b`.
- RoleArn chính xác từ Outputs: `arn:aws:iam::376129867108:role/GuardianReadRole-demo`.
- Change set `guardian-read-role-approved-20261011`: chỉ Add `ReadRole`, AWS::IAM::Role; DescribeEvents không có VALIDATION_ERROR; đã kiểm tra rồi thực thi theo quyền được duyệt.
- Lint template pass. GetRole xác nhận trust đúng ApiPrincipal và ScanPrincipal ở trên, điều kiện StringEquals sts:ExternalId khớp giá trị người dùng gửi.
- GetRolePolicy/ListRolePolicies: chỉ inline policy `guardian-read-only` với ec2:DescribeInstances, ec2:DescribeVolumes, ec2:DescribeAddresses, ec2:DescribeSnapshots, ec2:DescribeImages, cloudwatch:GetMetricData; Resource `*`.
- ListAttachedRolePolicies rỗng. Không có quyền stop/delete/terminate hoặc policy bổ sung.
- Không sửa template quyền, không tạo tài nguyên thử nghiệm, không publish frontend.

Người dùng dán RoleArn trên vào **Kết nối AWS**, chọn ap-southeast-1, bấm **Kiểm tra và lưu kết nối** rồi **Quét ngay**. Chưa ghi nhận scan pass; inventory rỗng nếu chạy thành công chỉ là kiểm tra luồng, không xác minh rule trên tài nguyên thật.

Ghi chú lịch sử: lần trước thiếu skill frontend-design. Ở lượt tiếp theo, người dùng đã cung cấp ./skill.md; thiết kế local đã hoàn tất như mục bên dưới.


## Frontend cải tiến — 2026-10-12 (đã publish)

Đã xác thực lại bằng aws login theo quyền người dùng cấp. MCP xác nhận account 376129867108 và đọc Outputs mới của cloud-resource-guardian tại ap-southeast-1; stack vẫn CREATE_COMPLETE. Mọi AWS API sau đăng nhập qua AWS MCP; S3 data transfer qua presigned URLs do MCP cấp. Không dùng AWS CLI để triển khai.

| Hạng mục | Kết quả |
|---|---|
| Website | https://d3qn9wabid8ws0.cloudfront.net/ |
| Bucket từ Outputs | cloud-resource-guardian-webbucket-gdgpbgx4t8o5 |
| Distribution từ Outputs | ERUII98HKGJOG; origin khớp WebBucket |
| Asset đã upload | app.js, styles.css, target-role.yaml, index.html; index upload cuối |
| Upload | HTTP 200 qua URL MCP ký; conditional PUT theo ETag/If-None-Match |
| Metadata | MIME đúng; Cache-Control no-store; AES256 |
| Cấu hình thật | config.json không upload, bytes và ETag giữ nguyên; đối chiếu Outputs pass |
| Backup trước ghi | .preflight/s3-backup-20261012T022755Z/; bốn object cũ và manifest hashes/metadata |
| Invalidation | IA4UB7G1SEGEHDP9HS1YNS9Y2E; /*; **Completed** |
| Thời gian tạo invalidation | 2026-10-12T02:29:36.183000+00:00 |
| Hậu kiểm hoàn tất | 2026-10-12T02:32:52.126076+00:00 |
| Rollback | Không cần; không phát hiện regression trong phạm vi đã kiểm tra |

Thiết kế áp dụng ./skill.md: hướng dẫn role ba bước, tải template nguyên vẹn, copy từng principal/ExternalId, nhập RoleArn và chọn region, xác minh kết nối, quét lần đầu. Dashboard/cảnh báo/lịch sử/cấu hình có trạng thái empty/loading/scanning/partial/error; mobile không ép cuộn ngang bảng. Không đổi backend/API/auth/IAM/rule/hạ tầng, không bật SES, không tạo tài nguyên thử.

### Kiểm thử phân biệt local và thật

- **Local demo/fixture đã pass:** node syntax check, tests/ui_smoke.py và tests/ui_redesign.py. Kiểm tra năm trang ở 320/390/768/1440 px, onboarding, download/copy, validation, polling, lịch sử, cấu hình, phiên hết hạn, các trạng thái scan và phục hồi lỗi. 23 PNG ở .preflight/ui-redesign/. Release khớp byte bản đã test; không chạy lại preflight/backend đã xong.
- **AWS thật:** MCP STS/DescribeStacks/GetDistribution/ListObjectsV2/HeadObject; backup S3, conditional upload, đọc lại origin, CreateInvalidation/GetInvalidation Completed. Kết quả API trong các file .preflight/mcp-*-result.json và mcp-publish-verification.json có api_calls success.
- **Website thật:** tests/ui_live_frontend.py PASS; năm file HTTP 200, đúng hash; config không demo; welcome và Cognito login ở 1440/390 px, PKCE S256, client/redirect đúng, không JavaScript error hoặc tràn ngang. Đã xem bốn screenshot ở .preflight/live-redesign/.
- **Chưa chứng minh:** đăng nhập/logout hoàn chỉnh qua mật khẩu, AssumeRole trong ứng dụng, worker scan, rule trên tài nguyên AWS thật, SES và multi-tenant. Không suy diễn từ UI demo hoặc trang Cognito login.

Browser tích hợp lỗi môi trường missing field sandboxPolicy; hậu kiểm dùng Playwright dự án với Chrome headless. Không thay đổi website để vượt lỗi môi trường.

### Khôi phục nếu phát hiện regression về sau

Lấy lại identity và Outputs bằng AWS MCP, kiểm tra release hiện tại chưa bị thay bởi người khác. Khôi phục index.html/app.js/styles.css từ .preflight/s3-backup-20261012T022755Z/, giữ config.json; tạo invalidation mới đúng distribution với CallerReference riêng, chờ Completed rồi kiểm tra bytes và giao diện. Không cần xóa target-role.yaml. Quy trình và helper trong HANDOFF.md; không tự chạy lại publish.py/deploy.py.

Trạng thái xác thực hết hạn ngày 2026-10-11 đã xử lý ngày 2026-10-12 bằng aws login được người dùng duyệt. Không còn blocker publish. Gói release và manifest PUBLISHED_VERIFIED nằm tại .preflight/frontend-release-20261011/; journal .preflight/publish-state.json.
