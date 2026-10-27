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

## Triển khai và Cập nhật Toàn diện — 2026-10-19 (Đã hoàn thành)

Ngày: 2026-10-19. Account `376129867108`, region `ap-southeast-1`.

### Kết quả triển khai

- Stack `cloud-resource-guardian`: **UPDATE_COMPLETE**
  - Stack ARN: `arn:aws:cloudformation:ap-southeast-1:376129867108:stack/cloud-resource-guardian/81f52de0-c53a-11f1-8a39-02ffd9f7b9e9`
  - Change Set: `guardian-update-1792342627` (ARN: `arn:aws:cloudformation:ap-southeast-1:376129867108:changeSet/guardian-update-1792342627/681651f2-b35d-40a8-aaf3-3e1669f5f9b1`)
  - Lambda Bundle Key: `cloud-resource-guardian/4be15583dbd3478716c1839a79e8d831e497a5ec8d327aae6805353578502851/lambda.zip` (16.715.151 bytes, SHA-256: `4be15583dbd3478716c1839a79e8d831e497a5ec8d327aae6805353578502851`)
  - Thay đổi CloudFormation: 16 resources (2 Add, 1 Remove quyền cũ `/ignore`, 13 Modify, **0 Replacement**, DynamoDB `Data` và SQS `DeadLetters` giữ nguyên không sửa đổi).
- Stack `guardian-read-role-demo`: **UPDATE_COMPLETE**
  - Stack ARN: `arn:aws:cloudformation:ap-southeast-1:376129867108:stack/guardian-read-role-demo/4b1fba80-c542-11f1-a054-0affe454644b`
  - Change Set: `guardian-role-update-1792342684` (ARN: `arn:aws:cloudformation:ap-southeast-1:376129867108:changeSet/guardian-role-update-1792342684/94482ecd-05d7-4985-afdc-a7fd62e5e515`)
  - Role ARN: `arn:aws:iam::376129867108:role/GuardianReadRole-demo`
  - Thay đổi: Cập nhật inline policy `guardian-read-only` bổ sung quyền đọc: `ec2:DescribeNatGateways`, `rds:DescribeDBInstances`, `elasticloadbalancing:DescribeLoadBalancers`, `s3:ListAllMyBuckets`, `s3:ListBucketMultipartUploads`. **0 Replacement, tuyệt đối không có quyền stop, modify hoặc delete**.
- Website: https://d3qn9wabid8ws0.cloudfront.net/
  - WebBucket: `cloud-resource-guardian-webbucket-gdgpbgx4t8o5`
  - CloudFront Distribution: `ERUII98HKGJOG`
  - Invalidation: `I51MCIJRTDV31DM63RY9R0AMSB` (**Completed**)
  - Đã upload đủ 5 file (`index.html`, `styles.css`, `app.js`, `target-role.yaml`, `config.json`), khớp byte 100% với nguồn.

### Kiểm tra thực tế sau triển khai

| Hạng mục | Kết quả | Chi tiết / Bằng chứng |
|---|---|---|
| CloudFormation Stacks | PASS | Cả hai stack `cloud-resource-guardian` và `guardian-read-role-demo` đạt `UPDATE_COMPLETE` |
| Frontend Website | PASS | 5 file trả HTTP 200, khớp SHA-256 nguồn; CloudFront Invalidation `I51MCIJRTDV31DM63RY9R0AMSB` Completed |
| Cognito Authentication | PASS | Hosted UI hiển thị form login cho user `b98a55fc-e061-70f4-04e4-f8298bc94e69`; flow PKCE S256 chuẩn |
| API Protection | PASS | Toàn bộ 10 route API trả `401 {"message":"Unauthorized"}` khi không có token Bearer |
| API `/feedback` | PASS | `GET /feedback` trả 200 `{"results":[],"next_token":null}`; `PUT /feedback` thẩm định đúng schema |
| STS AssumeRole | PASS | `PUT /connection` với `RoleArn` và `ExternalId` gọi `sts:AssumeRole` thành công, xác nhận account `376129867108` |
| Quét thực tế (Real Scan) | PASS | Lượt quét ID `86219e63-6f56-49b6-9398-0447f53f7809` bao gồm cả 4 nhóm (`compute`, `storage`, `database`, `network`) hoàn tất với status `SUCCEEDED`. Toàn bộ 9 loại tài nguyên (EC2, EBS, SNAPSHOT, S3_MULTIPART, RDS, EIP, NAT_GATEWAY, ALB, NLB) đều được kiểm tra thành công, không có lỗi (`errors: []`). |
| Scheduler Lambda | PASS | Invoke `ScheduleFunction` trả status 200, `queued_tenants: 0`, không có `FunctionError` |
| SQS / DLQ | PASS | DeadLetters queue hoạt động đúng chuẩn; không nhận thêm message lỗi sau khi sửa `eip_addresses()` |
| CloudWatch Logs | PASS | Log stream mới `2026/10/19/[$LATEST]a8391534a3bb460b86aac28fd2bb2358` ghi nhận worker thực thi thành công trong 4019ms, không còn bất kỳ ngoại lệ `ParamValidationError` nào. |

### Giới hạn và các tính năng chưa thể kiểm chứng trên tài nguyên thật

1. **Tài nguyên tài khoản trống:** Region `ap-southeast-1` hiện có 0 EC2 instances, 0 EBS volumes, 0 EIPs, 0 Snapshots, 0 RDS instances. Lượt quét trả về `counts: 0` và `findings: []`, chứng minh luồng end-to-end hoàn tất thành công (`SUCCEEDED`) nhưng chưa chứng minh các quy tắc phát hiện ngưỡng (CPU p95 < 5%, unattached volume age > 24h, snapshot age > 30d) trên dữ liệu thực.
2. **Đã khắc phục lỗi EIP Collector:** Đã loại bỏ tham số `MaxResults` và vòng lặp phân trang không phù hợp trong `eip_addresses()` (`src/collectors.py`). DescribeAddresses được gọi trực tiếp và giới hạn an toàn theo `RESOURCE_LIMIT`. Bổ sung xử lý `BotoCoreError` trong `collect_region`. Change Set `guardian-codefix-1792380950` đã triển khai thành công lên Lambda. Lượt quét thật với đầy đủ nhóm `network` đã chạy và đạt `SUCCEEDED`.
3. **SES:** Giữ tắt theo đúng yêu cầu; email delivery chưa gửi tới hộp thư thật.
4. **Multi-tenant isolation:** Chưa kiểm thử đồng thời 2 tài khoản người dùng thật khác nhau.

## Runbook vận hành, giám sát và chi phí — task 12 (thay đổi mã nguồn, chưa triển khai)

Phần này mô tả `template.yaml` trong repository, **không phải bằng chứng đã cập nhật stack AWS**. Không chạy lệnh AWS, tạo tài nguyên tính phí hoặc gửi SES trong đợt bổ sung runbook này. Các kết quả AWS ngày 11–19/10 ở trên là bằng chứng lịch sử, không xác nhận trạng thái hiện tại hay alarm mới. Giữ kiến trúc DynamoDB single-table, Cognito, Lambda async worker, EventBridge và SQS failure destination; không thêm SNS, consumer hoặc cơ chế tự động khôi phục.

### Alarm và cách xử lý

Template bổ sung **12 CloudWatch metric alarms**, không có `AlarmActions`, `OKActions` hay `InsufficientDataActions`: cần người vận hành xem CloudWatch/CLI, **không tự gửi thông báo/email hay tự sửa tài nguyên**. Tất cả dùng một kỳ đánh giá 300 giây, `TreatMissingData: notBreaching`; dữ liệu thiếu/`OK` không chứng minh ứng dụng đang khỏe. SQS là số liệu xấp xỉ và có thể chậm; Lambda có thể trả lỗi nghiệp vụ trong payload mà không tăng `Errors`.

| Logical ID | Metric / ngưỡng trong 5 phút | Xử lý ban đầu |
|---|---|---|
| `ApiErrorsAlarm`, `WorkerErrorsAlarm`, `ScheduleErrorsAlarm` | `AWS/Lambda`, `Errors`, `Sum >= 1`, theo `FunctionName` | Đọc log tương ứng, thời điểm/request ID, scan ID và trạng thái tenant. Phân biệt timeout/lỗi thực thi với `PARTIAL`/`FAILED` hoặc HTTP lỗi được handler trả về bình thường. |
| `ApiThrottlesAlarm`, `WorkerThrottlesAlarm`, `ScheduleThrottlesAlarm` | `AWS/Lambda`, `Throttles`, `Sum >= 1` | Xem concurrency toàn account/region, `ConcurrentExecutions`, `Duration` và tần suất gọi. Không tăng quota/concurrency hoặc bắn lại hàng loạt như bước đầu tiên; API Gateway throttling không nằm trong metric Lambda này. |
| `WorkerAsyncDroppedAlarm` | `AWS/Lambda`, `AsyncEventsDropped`, `Sum >= 1` | Kiểm tra event quá tuổi/hết retry, marker scan và failure queue. Worker hiện có tuổi event tối đa 600 giây, tối đa 2 retry cho function error; throttling/system errors có hành vi retry khác và vẫn bị giới hạn tuổi event. |
| `WorkerDestinationFailuresAlarm` | `AWS/Lambda`, `DestinationDeliveryFailures`, `Sum >= 1` | Kiểm tra queue tồn tại, quyền `sqs:SendMessage` của `ScanRole`, kích thước bản ghi failure và lỗi dịch vụ. **Queue rỗng không chứng minh không mất failure record.** |
| `ScheduleAsyncDroppedAlarm` | `AWS/Lambda`, `AsyncEventsDropped`, `Sum >= 1` | Scheduler được EventBridge gọi async nhưng không có failure destination riêng. Đối chiếu log scheduler, giờ chạy rule và lịch sử tenant; không giả định lỗi scheduler sẽ vào `DeadLetters`. |
| `ScheduleDeliveryFailuresAlarm` | `AWS/Events`, `FailedInvocations`, `Sum >= 1`, `RuleName` của `ScheduleFunctionTick` do SAM sinh | Kiểm tra rule enabled, target đúng và Lambda resource policy. Metric này theo dõi giao event từ EventBridge, không thay thế alarm lỗi thực thi Lambda và không báo mọi lần retry tạm thời. |
| `DeadLettersBacklogAlarm` | `AWS/SQS`, `ApproximateNumberOfMessagesVisible`, `Maximum >= 1` | Queue này chứa bản ghi invocation thất bại của worker, không phải queue công việc có consumer. Chỉ xem metadata trước; không receive/delete/purge/redrive. |
| `DeadLettersAgeAlarm` | `AWS/SQS`, `ApproximateAgeOfOldestMessage`, `Maximum >= 300` giây | Ưu tiên điều tra và lưu bằng chứng phù hợp trước khi message hết hạn. SQS retention hiện là 14 ngày; log Lambda chỉ 7 ngày nên không chờ sát hạn queue mới điều tra. |

Không đổi retention: `ApiLogs`, `WorkerLogs`, `ScheduleLogs` đều **7 ngày**, queue **14 ngày**. DynamoDB bật TTL ở thuộc tính `expires`; TTL xóa bất đồng bộ, không phải lịch xóa chính xác hay backup. Alarm không giám sát được mọi lỗi nghiệp vụ, trạng thái scan bị treo hoặc SES delivery/bounce; cần đối chiếu API/history và log. Không tự ghi token, ExternalId, email hoặc dữ liệu tenant đầy đủ vào hồ sơ sự cố.

### Chuẩn bị và đọc trạng thái (chỉ đọc AWS)

Các lệnh dưới đây là **hướng dẫn chưa chạy**. Dùng profile read-only được chủ account cấp, xác nhận account/region trước; không dùng quyền write hoặc assume target role để vận hành platform. Nếu thiếu quyền, yêu cầu quyền đọc đúng phạm vi, không mở rộng role quét.

```bash
export AWS_PROFILE='<approved-read-only-profile>'
export AWS_REGION='ap-southeast-1'
STACK='cloud-resource-guardian'
aws sts get-caller-identity
aws cloudformation describe-stacks --stack-name "$STACK" \
  --query 'Stacks[0].{Status:StackStatus,Outputs:Outputs}'
aws cloudformation list-stack-resources --stack-name "$STACK" \
  --query "StackResourceSummaries[?ResourceType=='AWS::CloudWatch::Alarm'].[LogicalResourceId,PhysicalResourceId]"
# Chọn PhysicalResourceId từ kết quả trên, không đoán tên alarm:
ALARM='<physical-alarm-name>'
aws cloudwatch describe-alarms --alarm-names "$ALARM"
aws cloudwatch describe-alarm-history --alarm-name "$ALARM" \
  --history-item-type StateUpdate --max-records 20
API_FN=$(aws cloudformation describe-stack-resource --stack-name "$STACK" \
  --logical-resource-id ApiFunction --query 'StackResourceDetail.PhysicalResourceId' --output text)
WORKER_FN=$(aws cloudformation describe-stack-resource --stack-name "$STACK" \
  --logical-resource-id WorkerFunction --query 'StackResourceDetail.PhysicalResourceId' --output text)
SCHEDULE_FN=$(aws cloudformation describe-stack-resource --stack-name "$STACK" \
  --logical-resource-id ScheduleFunction --query 'StackResourceDetail.PhysicalResourceId' --output text)
aws logs tail "/aws/lambda/$API_FN" --since 1h
aws logs tail "/aws/lambda/$WORKER_FN" --since 1h
aws logs tail "/aws/lambda/$SCHEDULE_FN" --since 2h
aws lambda get-function-event-invoke-config --function-name "$WORKER_FN"
RULE=$(aws cloudformation describe-stack-resource --stack-name "$STACK" \
  --logical-resource-id ScheduleFunctionTick --query 'StackResourceDetail.PhysicalResourceId' --output text)
aws events describe-rule --name "$RULE"
aws events list-targets-by-rule --rule "$RULE"
aws lambda get-policy --function-name "$SCHEDULE_FN"
```

Nếu alarm chưa tồn tại trên stack, ghi “chưa triển khai”, không tạo alarm thủ công để biến kiểm tra thành PASS. Khi xem CloudWatch Metrics, dùng đúng `FunctionName`, `QueueName`, `RuleName`, đúng region và khoảng UTC của sự cố; xem cả `AsyncEventAge` của worker để đánh giá áp lực trước ngưỡng tuổi event.

### Đọc lịch sử scan và failure queue an toàn

Ưu tiên đăng nhập bằng tenant được phép và dùng trang **Lịch sử**. API chỉ đọc tương ứng là `GET /history?limit=20` (1–100), phân trang bằng `next_token` do server trả về, và `GET /scans/{scanId}`. Dùng access token Cognito của chính tenant, không chia sẻ/lưu token vào báo cáo. Đối chiếu từng region, `scan_id`, `status`, `connection_version`, `started_at`/`completed_at`, `errors` và `notification` nếu có. History chỉ hiện connection version hiện tại và bản ghi chưa hết TTL; `404` không tự chứng minh scan chưa từng tồn tại. Latest result và history có thể không đầy đủ khi invocation thất bại giữa chừng; không coi history là audit ledger bất biến.

Khi cần support-level DynamoDB inspection, chỉ dùng tenant đã được ủy quyền và `Query` đúng partition, không scan toàn bảng. Lệnh sau đọc raw records, có thể thấy dữ liệu đã hết TTL chờ xóa hoặc connection version cũ; không sửa chúng:

```bash
TABLE=$(aws cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='TableName'].OutputValue | [0]" --output text)
aws dynamodb query --table-name "$TABLE" --consistent-read \
  --key-condition-expression 'pk = :tenant AND begins_with(sk, :prefix)' \
  --expression-attribute-values '{":tenant":{"S":"TENANT#<approved-cognito-sub>"},":prefix":{"S":"HISTORY#"}}' \
  --no-scan-index-forward --limit 20 --no-paginate
# Để đọc marker hiện tại, dùng cùng Query với prefix RESULT# thay cho HISTORY#.
QUEUE_URL=$(aws cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='DeadLetterQueueUrl'].OutputValue | [0]" --output text)
aws sqs get-queue-attributes --queue-url "$QUEUE_URL" --attribute-names \
  QueueArn MessageRetentionPeriod ApproximateNumberOfMessages \
  ApproximateNumberOfMessagesNotVisible ApproximateNumberOfMessagesDelayed
```

`GetQueueAttributes` và CloudWatch chỉ đọc metadata, **không đọc body**. SQS không có API “peek body” không tác dụng phụ: `ReceiveMessage` (kể cả visibility timeout bằng 0) vẫn thay đổi receive count và có thể ảnh hưởng xử lý; nút “Poll for messages” trong console cũng receive. Vì vậy runbook read-only **không** dùng `receive-message`, `delete-message`, `purge-queue`, `change-message-visibility` hay `start-message-move-task`. Nếu cần body để điều tra, phải có phê duyệt riêng và người sở hữu queue đánh giá tác dụng phụ/bảo mật. Lambda OnFailure gửi **invocation envelope** (`requestPayload`, response/context), không phải raw worker job để gửi lại nguyên body vào Lambda.

### Phục hồi có kiểm soát, không tự redrive

1. Ghi nhận UTC, account/region, alarm/log request ID, scan ID và region bị ảnh hưởng; xác định lỗi dispatch, worker, target-role read access hay failure-destination delivery. Đọc status hiện tại trước khi đưa ra kết luận. Không tắt alarm/đổi status để “làm sạch” sự cố.
2. Khắc phục nguyên nhân qua quy trình thay đổi được phê duyệt. Không thêm quyền stop/modify/delete tài nguyên target; lỗi assume-role cần người sở hữu kiểm tra trust/ExternalId/read policy, không cấp AdministratorAccess.
3. Đợi invocation/retry đang chạy kết thúc và tôn trọng lease/cooldown. Hiện manual scan cách nhau ít nhất 15 phút, tenant lease 600 giây, worker run lease 330 giây và timeout 300 giây. Các thời gian này không phải cam kết chính xác mọi retry đã kết thúc; kiểm tra log/metric/status trước, đặc biệt khi account bị throttle. Không xóa `LOCK`, `run_until`, dedup marker hoặc viết trực tiếp DynamoDB.
4. Sau khi nguyên nhân được sửa, cách phục hồi mặc định là người dùng có thẩm quyền chủ động tạo **scan mới qua UI/API hiện có**, chấp nhận lease/cooldown và scan ID mới. Đây là thao tác có ghi và có thể tính phí, **không thuộc các bước inspection read-only và không được chạy trong audit này**. Không invoke worker/scheduler thủ công, không replay job cũ hàng loạt: `connection_version`, marker scan ID, region và terminal status được kiểm tra nên job cũ có thể bị skip; replay cũng có thể lặp side effect/thông báo.
5. Xác nhận scan mới ở từng region, đối chiếu `SUCCEEDED`/`PARTIAL`/`FAILED`, lỗi và trạng thái notification. Giữ bằng chứng failure queue; chỉ xóa message sau phê duyệt và xác minh phục hồi, không purge queue để hết alarm. Không có auto-consumer/redrive/reconciler trong kiến trúc hiện tại, nên scan cũ có thể vẫn `QUEUED`/`RUNNING` khi event hết tuổi hoặc thất bại trước khi ghi terminal status.

### Inventory thử nghiệm và kiểm tra chi phí platform

**Không tạo tài nguyên trial trong audit này.** Các ID/tình trạng triển khai ở phần lịch sử chỉ là dữ liệu bàn giao; không suy ra chúng vẫn tồn tại hoặc còn trống. Trước/sau một trial được phê duyệt sau này, lưu inventory bằng read-only `DescribeStacks`, `ListStackResources`, `DescribeStackResources` trong đúng account/region, kèm UTC, chủ sở hữu, mục đích và nguồn bằng chứng:

| Phạm vi cần ghi vào inventory | Thành phần / điểm cần kiểm tra |
|---|---|
| Platform stack | 3 Lambda và 3 log groups/retention, DynamoDB `Data`/billing mode/TTL, SQS `DeadLetters`/retention/backlog, 12 alarms nếu đã deploy, HTTP API, EventBridge rule/targets, Cognito pool/client/domain và IAM roles/policies. |
| Website | S3 `WebBucket`, CloudFront distribution/OAC/bucket policy; dung lượng/object count, request/transfer, invalidation và asset/artifact còn lưu. |
| Email | `SenderEmail` mặc định rỗng, `SenderIdentity` và quyền SES chỉ có khi bật có chủ đích; giữ tắt. Không gửi mail để “test chi phí”. |
| Ngoài stack / account target | Read-role stack, SAM/deployment artifact buckets hoặc bản backup do công cụ triển khai tạo không nhất thiết thuộc stack chính. Tài nguyên target hiện có hoặc trial phải có inventory riêng: account/region, resource ID/ARN, owner, giờ tạo, giờ dự kiến dừng/xóa và bằng chứng dọn dẹp được phê duyệt. Không tự xóa trong audit. |

Các findings/ước lượng tiết kiệm của ứng dụng **không phải hóa đơn platform**. Dùng Billing / Cost Explorer của payer hoặc account được cấp quyền; nếu chưa bật Cost Explorer thì ghi hạn chế, không bật dịch vụ/tạo budget/CUR như một phần inspection. Không giả định Free Tier hoặc credit làm chi phí bằng 0.

1. Chọn kỳ UTC rõ ràng (ngày bắt đầu bao gồm, ngày kết thúc **không** bao gồm), account/linked account và currency hiển thị. Trong Cost Explorer, xem tổng rồi nhóm theo **Service**, sau đó lọc đúng linked account và xem theo **Region/Usage type**. Kiểm tra Lambda requests/duration, DynamoDB requests/storage, API Gateway requests, EventBridge, SQS, CloudWatch Logs ingest/storage và **alarm charges**, S3 requests/storage, CloudFront transfer/requests/invalidation, Cognito và SES nếu từng bật. Một số mục global không có region như workload; không lọc region quá sớm làm mất chi phí.
2. CLI chỉ đọc tương đương (thay ngày bằng kỳ đã được chủ account chấp thuận; Cost Explorer API cũng có thể phát sinh phí request theo chính sách hiện hành, không chạy lặp/poll). Console/Billing cũng có độ trễ; ghi thời điểm đọc, `Estimated`, metric và phạm vi:

   ```bash
   aws ce get-cost-and-usage --region us-east-1 \
     --time-period Start='<YYYY-MM-DD>',End='<YYYY-MM-DD>' \
     --granularity DAILY --metrics UnblendedCost UsageQuantity \
     --group-by Type=DIMENSION,Key=SERVICE Type=DIMENSION,Key=LINKED_ACCOUNT
   ```

3. Cost Explorer theo service/account có thể chứa workload khác. Dùng cost-allocation tag **đã được bật từ trước**, resource-level report/CUR **đã có** hoặc đối chiếu inventory/usage để phân bổ; không tuyên bố chính xác “chi phí ResourceGuardian” chỉ từ tổng account. Nếu chưa có tag/report phù hợp, ghi rõ chưa phân bổ được. Không cộng `UsageQuantity` của các đơn vị khác nhau thành một con số.
4. Đối chiếu Bills cho kỳ đã chốt, credits/tax và estimated/unblended khác nhau; lưu bản export đã loại dữ liệu nhạy cảm. Tra [AWS Pricing Calculator](https://calculator.aws/) và bảng giá chính thức theo region/usage thực tế nếu cần dự báo, ghi giả định; **không ghi giá hay số tiền đo được khi chưa có bằng chứng**. Inventory này không chứng minh resource trial đã được dọn dẹp hoặc platform miễn phí.

### Kiểm tra local và giới hạn bằng chứng

Lệnh validation được đề nghị cho người tích hợp sau khi tất cả thay đổi hoàn tất:

```bash
sam validate --lint --template-file template.yaml
```

Lệnh trên kiểm tra SAM/CloudFormation local (cần SAM CLI/cfn-lint tương thích), không deploy hoặc tạo change set; kết quả chưa được chạy/xác nhận trong phần runbook này. Phần bổ sung template chỉ thêm alarm resources, không đổi logical ID/properties tài nguyên hiện có, IAM permissions, retention hoặc mặc định SES. Không yêu cầu replacement từ thay đổi này; việc xác nhận thay đổi thực tế của một stack có drift cần người triển khai xem change set sau phê duyệt, **không phải bằng chứng đã có trong audit local**.

Chưa xác minh runtime AWS cho alarm state transition/metric delivery, EventBridge failed delivery, SQS message age/drop, worker async retry/destination failure, SES delivery hoặc chi phí thực tế trong lần thay đổi này. Không cố tình tạo lỗi hay tạo tài nguyên trả phí để chứng minh alarm. Tài liệu AWS tham chiếu: [SAM generated schedule rule](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-specification-generated-resources-function.html), [Lambda metrics](https://docs.aws.amazon.com/lambda/latest/dg/monitoring-metrics-types.html), [SQS metrics](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-available-cloudwatch-metrics.html), [EventBridge metrics](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-monitoring.html).
