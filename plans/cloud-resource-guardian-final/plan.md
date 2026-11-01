# Gap Analysis & Implementation Plan — Cloud Resource Guardian

**Ngày lập:** 2026-11-01  
**Mục tiêu:** Đối chiếu yêu cầu kỹ thuật ↔ Code repo hiện tại ↔ AWS live state ↔ Báo cáo nghiệm thu. Xác định rõ trạng thái từng thành phần và phương án hoàn thiện an toàn.

---

## 1. Bảng đối chiếu 22 thành phần hệ thống

| # | Thành phần | Báo cáo yêu cầu | Code hiện tại | AWS hiện tại | Trạng thái | Cách sửa | Test |
|---|---|---|---|---|---|---|---|
| 1 | **Frontend** | PKCE, Cognito login/logout, connection form (RoleArn, max 3 regions, 4 nhóm dịch vụ), dashboard, findings, evidence, filters, history, Acknowledge, Keep/Unkeep, Ignore 7 ngày, empty/partial/failed states, responsive 320px-desktop, no AWS mutations. | Có UI dashboard, history, settings, connection (RoleArn, regions), và nút "Bỏ qua 7 ngày" (/feedback). Thiếu checkboxes chọn 4 service groups và thiếu nút Acknowledge & Keep/Unkeep trên table. | Bản web tĩnh upload ngày 18/10/2026 trên S3 WebBucket và CloudFront (`d3qn9wabid8ws0.cloudfront.net`). | **PARTIAL** & **CLOUD_DRIFT** | Bổ sung checkboxes chọn 4 nhóm dịch vụ (`compute`, `storage`, `database`, `network`) trong connection form; bổ sung các nút Acknowledge, Keep/Unkeep, Ignore trên từng finding; cập nhật build và publish lên S3/CloudFront. | `node --check web/app.js`, `tests/ui_smoke.py`, Playwright responsive test 320px-1440px, live HTTPS test. |
| 2 | **Cognito** | User Pool, App Client (OAuth Code + PKCE), Hosted UI, AdminCreateUserOnly, 12+ chars password policy. | Đã định nghĩa trong `template.yaml` (UserPool, UserClient, UserDomain). | User Pool `ap-southeast-1_wKqDqfW3t`, Client `6gshdb16lafagprs48q21ifgjm`, Hosted UI domain `crg-376129867108-ap-southeast-1`. | **DONE** | Giữ nguyên cấu hình, không thay đổi hay replace User Pool. | Kiểm tra Hosted UI HTTP 200, JWT token validation. |
| 3 | **API Gateway** | HTTP API (API Gateway v2) với JWT Authorizer, CORS cho CloudFront origin, route throttling. | Đã khai báo trong `template.yaml` (`HttpApi`, CORS, JWT authorizer, routes). | API ID `l2qn7i2en9`, endpoint `https://l2qn7i2en9.execute-api.ap-southeast-1.amazonaws.com`, 10 routes bảo vệ bằng JWT. | **DONE** | Giữ nguyên, đảm bảo các endpoint bảo mật. | `tests/test_api.py`, 401 unauthorized test cho tất cả routes. |
| 4 | **Lambda API** | Router các endpoint GET/PUT, phân tách tenant qua sub JWT, validate input, invoke Worker bất đồng bộ. | Đầy đủ trong `src/app.py` (`api` handler), xử lý `/me`, `/connection`, `/settings`, `/scans`, `/findings`, `/history`, `/feedback`, `/notifications`. | Chạy trên AWS Lambda `cloud-resource-guardian-ApiFunction-b3gqpsw3XEW6` (bản ngày 19/10/2026). | **CLOUD_DRIFT** | Đóng gói source mới nhất và cập nhật qua CloudFormation change set an toàn. | `test_api.py`, `test_read_only.py`, smoke test. |
| 5 | **Scheduler** | Tự động quét theo lịch cấu hình, pagination theo tenant, cô lập tenant lỗi, invoke Worker async. | Đầy đủ trong `src/app.py` (`scheduler` handler), bảo vệ profile hỏng, atomic clock. | Lambda `cloud-resource-guardian-ScheduleFunction-LyoJCcdNDe6l`, EventBridge 1 giờ trigger. | **CLOUD_DRIFT** | Đóng gói cập nhật Lambda code cùng stack change set. | `test_task8.py`, unit test scheduler. |
| 6 | **Scan Worker** | Worker claim lease conditional write, AssumeRole target, chạy 9 collector, lưu finding/result/history nguyên tử, giải phóng lease. | Đầy đủ trong `src/app.py` (`worker` handler), deadline budget, transaction writes. | Lambda `cloud-resource-guardian-WorkerFunction-WjbONL4eaYdT` (Timeout 300s, Memory 256MB). | **CLOUD_DRIFT** | Đóng gói cập nhật Lambda code cùng stack change set. | `test_workflows.py`, `test_task8.py`. |
| 7 | **Rule Engine** | Module nội bộ trong Worker, đánh giá ngưỡng và độ phủ cho 9 loại tài nguyên, không mutation. | Triển khai hoàn chỉnh trong `src/rules.py` cho cả 9 loại tài nguyên, tính coverage >= 80%, không coi missing là 0. | Tích hợp bên trong gói ZIP WorkerFunction trên AWS. | **CLOUD_DRIFT** | Đóng gói mã nguồn mới nhất vào ZIP. | `test_rules.py` (52 test rules pass). |
| 8 | **DynamoDB** | 1 bảng vật lý duy nhất, PK=USER#sub, SK phân loại record, TTL enabled, SSE enabled, PAY_PER_REQUEST. | Khai báo trong `template.yaml`, logic lưu trữ trong `src/app.py`. | Table `cloud-resource-guardian-Data-15ID2URED2G6T`, ACTIVE, PAY_PER_REQUEST, TTL enabled (`expires`). 59 items. | **DONE** | Giữ nguyên bảng, tuyệt đối không replace hoặc xóa dữ liệu. | `test_task8.py`, DynamoDB invariant tests. |
| 9 | **EventBridge** | Lịch kích hoạt định kỳ cho Scheduler (`rate(1 hour)`), và Reconciler (`rate(5 minutes)` từ Task 8). | Đã khai báo trong `template.yaml` (`ScheduleFunctionTick`, `ReconcileFunctionTick`). | Đang có `ScheduleFunctionTick` (1 hour) kích hoạt ScheduleFunction. Chưa có `ReconcileFunctionTick`. | **CLOUD_DRIFT** | Cập nhật stack qua Change Set để bổ sung `ReconcileFunctionTick` an toàn (Add). | `test_task8_template.py`. |
| 10 | **SQS/DLQ** | DLQ cho Worker async execution failure destination, DeadLetters queue và OperationsDeadLetters queue. | Đã khai báo trong `template.yaml` (`DeadLetters`, `OperationsDeadLetters`). | Đang có `DeadLetters` URL `cloud-resource-guardian-DeadLetters-Dq7qdXMYHQ9d` với 1 tin nhắn cũ. Chưa có `OperationsDeadLetters`. | **CLOUD_DRIFT** | Bổ sung `OperationsDeadLetters` và redrive policy an toàn qua Change Set. | `test_task8.py`, SQS queue attributes check qua MCP. |
| 11 | **CloudWatch** | Logs retention 7 ngày cho mọi Lambda function, metric alarms cho failures/deadletters. | Đã khai báo trong `template.yaml` (LogGroups, Alarms). | Các log group `/aws/lambda/cloud-resource-guardian-...` đều có Retention 7 ngày. | **CLOUD_DRIFT** | Bổ sung Alarms Task 8 trong change set. | CloudWatch logs describe qua MCP. |
| 12 | **SES tùy chọn** | Gửi email digest khi có finding mới, mặc định tắt (`SenderEmail=""`). | Hỗ trợ trong `src/app.py` và điều kiện `EmailEnabled` trong `template.yaml`. | Parameter `SenderEmail=""`, `EmailEnabled=false`, SES identity không kích hoạt. | **DONE** | Tiếp tục giữ tắt SES theo yêu cầu. | `test_notifications.py`. |
| 13 | **GuardianReadRole** | Role chỉ đọc trong account được quét, trust ApiRole & ScanRole, bắt buộc ExternalId, 0 mutation. | File `target-role.yaml` và `web/target-role.yaml` khớp 100%, chỉ có Describe/List/Get/GetMetricData. | Stack `guardian-read-role-demo` đang ở `UPDATE_COMPLETE`, RoleArn `arn:aws:iam::376129867108:role/GuardianReadRole-demo`. | **DONE** | Giữ nguyên role, không thay đổi quyền. | `test_read_only.py`, IAM simulation. |
| 14 | **ApiRole** | Role cho ApiFunction, least privilege: DynamoDB CRUD, Lambda invoke Worker, STS AssumeRole GuardianReadRole. | Khai báo trong `template.yaml` (`ApiRole`). | Đã triển khai trên AWS (`cloud-resource-guardian-ApiRole-So7rB7aEKrFT`), đúng policy. | **DONE** | Giữ nguyên. | `test_read_only.py`. |
| 15 | **ScanRole** | Role cho WorkerFunction, least privilege: DynamoDB CRUD, SQS SendMessage, STS AssumeRole GuardianReadRole. | Khai báo trong `template.yaml` (`ScanRole`). | Đã triển khai trên AWS (`cloud-resource-guardian-ScanRole-oykltlddshRl`), đúng policy. | **DONE** | Giữ nguyên. | `test_read_only.py`. |
| 16 | **9 Collectors** | EC2, EBS, EIP, Snapshot, S3 Multipart, RDS, NAT Gateway, ALB, NLB. Time budget, pagination, error handling. | Hoàn thiện trong `src/collectors.py`, xử lý pagination, throttling retry, budget check. | Đã tích hợp trong mã nguồn WorkerFunction. | **DONE** | Đóng gói cùng bản release Lambda mới. | `test_collector_budget.py`, `test_workflows.py`. |
| 17 | **Feedback** | `acknowledged`, `kept`, `ignoreUntil` độc lập; không dùng `/ignore`; unkeep không xóa ignoreUntil còn hạn. | Backend `_upsert_feedback` trong `src/app.py` đã tuân thủ đúng semantics. Frontend cần bổ sung nút bấm cho cả 3 thao tác. | Đã có route `PUT /feedback` và `GET /feedback` trên API Gateway. | **PARTIAL** | Cập nhật frontend `web/app.js` để gọi đúng `/feedback` cho Acknowledge, Keep/Unkeep và Ignore. | `test_api.py`, `test_workflows.py`. |
| 18 | **Tenant Isolation** | Scoped theo JWT sub, không tin userId từ request body, conditional writes chống ghi đè tenant khác. | Tuân thủ chặt chẽ trong `src/app.py` qua `tenant_key(event)`. | Được thực thi qua JWT authorizer trên API Gateway và Lambda logic. | **DONE** | Giữ nguyên kiến trúc an toàn. | `test_api.py`, `test_task8.py`. |
| 19 | **Settings** | Ngưỡng CPU, Network, Orphan hours, Scan interval, Window hours (24-168h). | Validate đầy đủ trong `src/rules.py` (`config`) và `src/app.py`. | Đã hỗ trợ qua route `PUT /settings`. | **DONE** | Giữ nguyên. | `test_rules.py`, `ui_smoke.py`. |
| 20 | **Lịch quét** | EventBridge trigger, lease lock chống chạy trùng, cooldown 15 phút giữa 2 lần quét. | Hoàn thiện trong `src/app.py` (Task 8 lease & admission logic). | Đã chạy thực tế trên AWS mỗi giờ. | **DONE** | Giữ nguyên logic. | `test_task8.py`. |
| 21 | **Deployment Scripts** | Đóng gói artifact, an toàn bảo mật, cấm AWS CLI mutation, thực hiện qua AWS MCP. | `deploy.py` và `publish.py` có trong repo. Quy trình vận hành chính thức qua AWS MCP helpers trong `.preflight/`. | Thực hiện qua stdio MCP client (`aws___run_script`, `aws___get_presigned_url`). | **DONE** | Sử dụng MCP helper scripts an toàn không dùng AWS CLI. | Preflight probes & script validation. |
| 22 | **Documentation** | README, DEPLOYMENT, HANDOFF, PREFLIGHT, VALIDATION, plan.md, live-state.md. | Đầy đủ cấu trúc tài liệu. | Cần cập nhật sau khi triển khai và kiểm thử E2E. | **PARTIAL** | Cập nhật đầy đủ bằng chứng, outputs và hướng dẫn vận hành sau khi hoàn tất. | Rà soát tài liệu bàn giao. |

---

## 2. Kế hoạch triển khai chi tiết

### Giai đoạn 1: Hoàn thiện Frontend (Mục 1, 17)
- Cập nhật `web/index.html`: Thêm checkboxes chọn 4 nhóm dịch vụ (`compute`, `storage`, `database`, `network`) trong connection step; cập nhật giao diện bảng findings hỗ trợ Acknowledge, Keep/Unkeep, Ignore 7 ngày.
- Cập nhật `web/app.js`: Thêm event handlers và hiển thị trạng thái `acknowledged`, `kept`, `ignore_until`; gửi payload chính xác tới `PUT /feedback`; gửi `service_groups` trong `PUT /connection`.
- Kiểm tra tính tương thích responsive (320px, 390px, 768px, 1440px), keyboard focus, accessibility.

### Giai đoạn 2: Local Verification & Smoke Tests
- Chạy unit test: `.venv-preflight/Scripts/python.exe -m unittest discover -s tests -v`.
- Chạy UI smoke test: `tests/ui_smoke.py`.
- Chạy syntax & compile check: `compileall`, `node --check`.
- Chạy SAM validate & SAM build.

### Giai đoạn 3: CloudFormation Change Set qua AWS MCP (Mục 4, 5, 6, 9, 10, 11)
- Tạo ZIP package Lambda từ `src/` (loại bỏ cache, test code, không đụng tới file nhạy cảm).
- Upload ZIP lên S3 artifact bucket thông qua MCP Presigned URL.
- Tạo CloudFormation Change Set cho stack `cloud-resource-guardian` (Action: Add/Modify, 0 Remove, 0 Replacement cho DynamoDB/Cognito/S3/CloudFront).
- Phân tích Change Set an toàn trước khi thực thi ExecuteChangeSet qua AWS MCP.
- Chờ trạng thái đạt `UPDATE_COMPLETE`.

### Giai đoạn 4: Publish Frontend qua AWS MCP (Mục 1)
- Lấy Outputs mới từ stack CloudFormation.
- Cập nhật `web/config.json` với URL API, Cognito Domain, Client ID chính xác.
- Upload các file tĩnh (`index.html`, `styles.css`, `app.js`, `target-role.yaml`, `config.json`) lên S3 `WebBucket` qua MCP Presigned URL (đảm bảo bucket private, SSE AES256).
- Tạo CloudFront invalidation qua AWS MCP và kiểm tra trạng thái `Completed`.

### Giai đoạn 5: AWS End-to-End Verification (20 tiêu chí)
- Kiểm tra HTTPS 200 frontend qua CloudFront.
- Kiểm tra Cognito Hosted UI login page.
- Kiểm tra bảo vệ API (401 Unauthorized khi thiếu/sai token).
- Kiểm tra Invoke Lambda API & Scheduler qua MCP.
- Kiểm tra pipeline scan và cập nhật trạng thái QUEUED -> RUNNING -> SUCCEEDED/PARTIAL.
- Kiểm tra Feedback, History, CloudWatch logs và DLQ.

### Giai đoạn 6: Cập nhật tài liệu, Commit & Bàn giao
- Cập nhật `README.md`, `DEPLOYMENT.md`, `HANDOFF.md`, `PREFLIGHT.md`, `VALIDATION.md`.
- Commit các thay đổi theo từng nhóm có ý nghĩa.
- Tạo báo cáo nghiệm thu hoàn chỉnh.
