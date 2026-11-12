# Cloud Resource Guardian — Final Acceptance Audit

Ngày release production: 2026-11-12. Revision `e53f46ce23bd4406525657f04f87a35791744713` đã deploy backend/IAM/frontend; không push GitHub, không migration dữ liệu, không chạy scan mới và không gửi email thật.

## Kết luận

**Production infrastructure release đã hoàn tất; route, JWT gate, Lambda artifact, CloudFront bytes, PKCE redirect và mobile surface đã smoke. Authenticated business E2E, tenant isolation thật, scan mới và SES delivery vẫn `BLOCKED/NOT_TESTED`, nên chưa tuyên bố production acceptance đầy đủ.** Trạng thái: `IMPLEMENTED`, `VERIFIED`, `PARTIAL`, `MISSING`, `BUG`, `NOT_TESTED`, `BLOCKED`.

## A. Architecture

Luồng source:

CloudFront + private S3 → Cognito Authorization Code/PKCE → API Gateway JWT → API Lambda → DynamoDB. API enqueue worker Lambda; worker STS AssumeRole với ExternalId để đọc target account. EventBridge scheduler, reconciler, Lambda async retry, SQS failure destination/recovery/DLQ, CloudWatch logs/alarms và SES notification bổ sung quanh data path.

Đã kiểm tra source/local:

- tenant partition từ Cognito `sub`; Lambda yêu cầu `token_use=access`;
- connection version, lease, run token, 15-minute deadline/cooldown, terminal CAS và immutable history;
- worker 300 giây, collector reserve 60 giây, persistence reserve 10 giây;
- async retry tối đa 2, SQS recovery, reconcile expired markers;
- API/history/feedback/inventory pagination và tenant-bound cursor;
- inventory API dùng DynamoDB Query trong tenant partition, không table Scan;
- scheduler/reconciler vẫn dùng table Scan, chỉ phù hợp giả định tối đa 5 user nội bộ.

Source/local `VERIFIED`; năm Lambda production cùng CodeSha256 release và stack `UPDATE_COMPLETE`. Retry/DLQ tick thật, authenticated API và scan mới `NOT_TESTED`.

## B. Backend

Source count trực tiếp:

| Hạng mục | Số |
|---|---:|
| Resource type registry | 38 |
| Distinct rule ID | 39 |
| Collector function cho resource | 36 |
| Threshold field | 40 |
| Service group selectable | 12 |
| UI high-level category trong registry | 6 |

Thay đổi backend:

- collector trả inventory identity cho cả resource 0 finding;
- ECR image age lấy mọi page `DescribeImages.imagePushedAt`, không dùng age 0;
- DocumentDB dùng `docdb`, Neptune dùng `neptune`;
- CloudFront chỉ chạy ở một owner region xác định;
- EIP, Lambda event-source mappings, Backup recovery points, EKS nodegroup/Fargate profiles được phân trang;
- required subrequest AccessDenied không bị nuốt thành dữ liệu rỗng;
- metric rỗng của extended evaluator trả `INSUFFICIENT_DATA`, không REVIEW từ zero giả;
- VPC Endpoint, MemoryDB, DocumentDB, Neptune và các rule multi-metric lấy đúng series cần thiết.

`IMPLEMENTED`, `VERIFIED` local; 38-type AWS correctness `NOT_TESTED`.

## C. Inventory

Inventory và findings là hai tập riêng:

- page key: `TENANT#sub` / `INVENTORY#connection_version#scan_id#region#run_token#type#page`;
- 25 identity/page, TTL 30 ngày, transaction tối đa 98 Put + 2 ownership checks;
- identity gồm `resource_id`, optional `resource_name`; page/API gắn service/type/region/account/scan/time;
- RESULT giữ counts, `inventory_count`, `inventory_persisted`, `inventory_run_token`, status/errors;
- retry cũ không trộn vì API chỉ nhận page có run token của row terminal;
- old scan không có page trả `aggregate_only`, không tạo ID giả;
- không table replacement, GSI hoặc rewrite dữ liệu cũ.

API source tìm theo ID, name, type, service, region, account, scan ID và scan time; limit 1–500, cursor bound tenant/scan/filter.

Trạng thái: `IMPLEMENTED`, local Moto `VERIFIED`; route production `/inventory` đã deploy với Cognito JWT và unauthenticated request trả 401. Authenticated inventory từ scan mới `NOT_TESTED`.

## D. Search & Filter

### Inventory scope

- lấy type/service/region từ identity của scan mới;
- giữ resource 0 finding;
- join finding count theo type + region + resource ID;
- legacy dùng count aggregate và ghi rõ không có danh tính.

### Findings scope

- search ID, name, finding ID, rule ID, service, type, region, reason;
- filter REVIEW/OBSERVING/INSUFFICIENT_DATA, rule, acknowledged, diff previous scan, service/type/group/region;
- sort hợp lệ; filter field khác AND; mỗi select single-value;
- multiple findings trên một resource không mất record; unique affected count không dùng finding count.

Keep/Ignore active bị API `/findings` ẩn theo nghiệp vụ; quản lý nằm ở feedback tab. Vì current result không chứa những item đó, filter chính không giả vờ filter Keep/Ignore.

### History scope

- exhaust mọi `/history` cursor retained;
- filter scan status/date/service/type/region/rule/resource ID; date hiển thị `Asia/Ho_Chi_Minh`;
- phân biệt finding occurrence và unique resource trong dataset findings;
- connection version filter ở backend.

Giới hạn: history hiện lưu findings + aggregate inventory counts. Cross-scan full inventory identity search và distinct unique/appearance metrics cho mọi resource là `MISSING`; UI công bố rõ, không giả full inventory history.

TC01–TC20 fixture `VERIFIED` local. Production data `NOT_TESTED`.

## E. UI/UX

- dashboard có connection, last scan, KPI, status và quick actions;
- resource page có compact scan selector, KPI, filters, service chart, grouped list và side panel;
- main card chỉ hiển thị identity/service/status/reason/evidence chính; kỹ thuật ở panel;
- partial/failed/timed-out dùng thông báo dễ hiểu; error code/service trong dialog;
- loading, no connection, no scan, no finding, no search result, API/network/session error có state riêng;
- feedback Acknowledge/Keep/Ignore/undo/expiry không gọi API phá hủy AWS;
- applied chips, clear-all, result count, searchable type option, keyboard navigation;
- scan/scope request generation ngăn response cũ ghi đè;
- local viewport 320/390/768/1440 không overflow trong suite tương ứng.

`VERIFIED` local; deployed CloudFront bytes và browser production `NOT_TESTED`.

## F. Email

`src/email_report.py` tạo multipart content:

- subject `[Cloud Resource Guardian] X tài nguyên cần kiểm tra`;
- HTML responsive + text/plain;
- scan time Việt Nam, account, region, status, summary, service counts, tối đa 5 resource, CTA;
- không raw evidence JSON, không secret, escape toàn bộ dynamic HTML;
- REVIEW là candidate cần xem, không severity giả;
- PARTIAL/FAILED không tuyên bố an toàn.

Notification giữ verified Cognito recipient, tenant/connection/region/recipient dedup key, cooldown, conditional claim và các trạng thái `SENT`, `FAILED`, `UNKNOWN`, `STATE_FAILED`, `SENT_UNRECORDED`. SES và DynamoDB không atomic nên không hứa exactly-once.

Template/logic `VERIFIED` local. SES identity email `SUCCESS` và sending enabled, nhưng account còn sandbox, DKIM `NOT_STARTED`, không custom MAIL FROM và chưa đạt domain alignment; không gửi email thật. Delivery event/Gmail desktop/mobile `BLOCKED/NOT_TESTED`.

## G. Security

Đã xác minh source/local:

- PKCE S256, OAuth state, verifier bắt buộc và authorization code được xóa khỏi URL trước token exchange;
- access token chỉ ở sessionStorage; 401 trả UI về login;
- API Gateway issuer/audience + Lambda `token_use=access`;
- STS ExternalId và Role ARN allowlist;
- tenant/connection keys, cursor binding và cross-tenant 404/400;
- API body/field/enum/range/UUID validation, 10 KiB body cap;
- CORS single CloudFront origin, API throttling 5 rps/10 burst;
- frontend không dùng `innerHTML`/`eval`; email escape;
- browser không giữ AWS credentials; target role chỉ đọc.

Chưa harden trong IaC vì ngoài blocker release đã phê duyệt:

- CloudFront ResponseHeadersPolicy/CSP/HSTS/nosniff/frame/referrer;
- Cognito MFA/deletion protection policy;
- DynamoDB PITR/deletion protection;
- SES domain authentication.

Target role đã thêm `ecr:DescribeImages`. DocumentDB và Neptune dùng boto3 clients `docdb`/`neptune`, nhưng AWS IAM management action chính xác vẫn là `rds:DescribeDBClusters`, đã có từ trước. Không thêm hai action prefix không tồn tại. IAM Policy Autopilot đã chạy trên `src/*.py`; dynamic paginator/client resolution chưa đầy đủ nên kết quả được đối chiếu với tài liệu AWS và `cfn-lint`.

## H. Tests

| Check | Kết quả |
|---|---|
| `CRG_AWS_E2E=0 .venv/bin/python -m unittest discover -s tests -v` | **422 PASS, 1 SKIP** |
| AWS E2E | **1 SKIP có chủ đích**, cần manual release gate |
| Local Playwright | **13/13 scripts PASS**; không chạy `ui_live_frontend.py` |
| Resource filter TC01–TC20 | PASS |
| Email render + notification state (`tests.test_email_report`, `tests.test_notifications`) | **30 PASS** |
| `node --check web/app.js` | PASS |
| Python compile source/tests mới | PASS |
| `cfn-lint --regions ap-southeast-1 -t template.yaml target-role.yaml web/target-role.yaml` | PASS |
| `git diff --check` | PASS |
| SAM CLI / cfn-guard | **NOT_RUN** — hai executable không có trên workstation; không tự cài tool ngoài gate |

Suite bao phủ rule/collector, pagination, timeout, retry, PARTIAL, tenant isolation, feedback, notifications, inventory identity/count separation, multi-finding, long/Unicode ID, global owner, ECR age, permission failure, responsive/accessibility. Không có test bị sửa để che lỗi nghiệp vụ; fixture smoke được cập nhật theo yêu cầu option dynamic sau khi finding duy nhất bị Ignore.

## I. Deployment

### Change classes

| Class | Nội dung |
|---|---|
| A. Frontend | inventory detail/fallback, dynamic filters, scope/history notices, PKCE hardening |
| B. Backend/Lambda | collector/rules, inventory writer/API, email subject |
| C. IAM/CloudFormation | Thêm route `GET /inventory`; thêm duy nhất `ecr:DescribeImages` vào hai target-role template |
| D. DynamoDB | logical item additive; không physical schema migration/GSI/rewrite |
| E. SES/DNS | **Không sửa**; production verification plan only |
| F. Docs/tests | coverage report, acceptance, deployment, regression fixtures |

### Dependency order

1. Review/commit revision và pin artifacts.
2. Backup template/config/web assets hiện hành và review target-role change set.
3. Deploy target-role stack với đúng một action mới `ecr:DescribeImages`; `rds:DescribeDBClusters` hiện hữu phục vụ RDS/DocumentDB/Neptune management APIs.
4. Review platform change set thêm `GET /inventory`; xác nhận không replacement bảng/UserPool/bucket hoặc resource stateful.
5. Deploy backend + route bằng ZIP đã pin.
6. Smoke auth, tenant boundary, findings/history/inventory/PARTIAL.
7. Chạy approved scan và validate inventory pages/IAM.
8. Publish frontend cùng revision, upload target-role template và invalidate CloudFront.
9. Run desktop/mobile/live console/network smoke. SES/DNS là gate riêng; chỉ test send sau approval.

Frontend fallback aggregate với API 404/405 nên backward compatible. Release revision `e53f46ce23bd4406525657f04f87a35791744713` dùng artifact SHA-256 `8cc193fd376076c977fe1eca72e2dbd9aea4449f5d740423cd4f40dce270cb14`; cả năm Lambda production khớp CodeSha256. Target-role change set chỉ thêm `ecr:DescribeImages`; platform change set thêm route/permission và cập nhật code in-place. CloudFront invalidation `ICV0X7DG9HXWT8IR5BRXYTML6Y` hoàn tất; bốn release assets và target-role template khớp byte revision.

Không có Delete hoặc thay đổi stateful trong hai change set. Backup processed templates, Lambda cũ SHA-256 `944bca591d6456b4019a66660ce6754b7ff7d98b9dd827ed194d98f7f725f4f8` và năm web objects nằm tại `.preflight/releases/e53f46ce23bd4406525657f04f87a35791744713/rollback/`. Inventory pages additive được code cũ bỏ qua và TTL dọn; không xóa/migrate data.

## J. Remaining Issues

### BLOCKER

1. Không có access token production trong release environment; chưa kiểm tra login hoàn tất, `/me`, connection, scan, authenticated inventory, findings/history/feedback và tenant isolation với hai Cognito tenant thật.
2. Chưa chạy scan production mới sau release; ECR/DocumentDB/Neptune và 38 loại chưa có evidence AWS của revision này.
3. SES còn sandbox, DKIM chưa bật, không custom MAIL FROM/domain alignment và chưa được phê duyệt gửi test.

### HIGH

1. Full historical inventory identity search chưa có; history chỉ findings + counts.
2. Giới hạn 100 resource/type/region, 50 displayed findings, 100 candidates có thể cắt dữ liệu; không được quảng bá full-account coverage.
3. 38 collector/rule chưa có AWS fixture/evidence đồng đều.
4. CloudFront security headers, Cognito MFA/deletion protection và DynamoDB PITR chưa harden.

### MEDIUM

1. `/inventory` Query đọc mọi page của scan rồi filter/sort trong Lambda; bounded nhưng read amplification tăng theo scan.
2. Scheduler/reconciler table Scan chỉ phù hợp quy mô nội bộ hiện tại.
3. Keep/Ignore không filter trong main findings vì active records bị ẩn; feedback tab là nguồn quản lý.
4. SES exactly-once không khả thi với API hiện tại; `SENT_UNRECORDED` có rủi ro duplicate sau cooldown.

### LOW

1. Cần đo chi phí Dynamo read/write và latency trên account inventory lớn sau deploy.
2. Cần screenshot/live accessibility evidence trên browser production, không chỉ fixture.

## K. Final Acceptance

| Capability | Status |
|---|---|
| Serverless architecture/source contracts | VERIFIED local; production stack UPDATE_COMPLETE |
| Auth/tenant/STS security logic | VERIFIED local; JWT route/401 VERIFIED; authenticated AWS E2E NOT_TESTED |
| 38-type collector registry | IMPLEMENTED; AWS PARTIAL/NOT_TESTED |
| Inventory identity current scan | DEPLOYED; local VERIFIED; authenticated production NOT_TESTED |
| Findings search/filter | VERIFIED local; production authenticated NOT_TESTED |
| History findings search | VERIFIED local; production authenticated NOT_TESTED |
| Full historical inventory search | MISSING |
| UI/UX responsive/accessibility | VERIFIED local; production login/mobile surface VERIFIED |
| Email HTML/text + notification state | VERIFIED local |
| SES/DNS/delivery | Identity VERIFIED; delivery BLOCKED |
| IAM/CloudFormation release | DEPLOYED; no stateful replacement |
| Production release | PARTIAL — infrastructure/frontend deployed, business E2E pending |

### Production E2E

| Scenario | Local evidence | Production |
|---|---|---|
| Cognito login/logout | PKCE/unit/UI fixture PASS | PKCE S256 redirect PASS; completed login/logout BLOCKED |
| AWS connection | validation/unit/UI fixture PASS | BLOCKED — no production access token |
| Scan Now + progress | orchestration/unit/demo PASS | BLOCKED — no approved authenticated scan run |
| Resource inventory | API/Moto/UI PASS | Route/JWT/401 PASS; authenticated data BLOCKED |
| REVIEW/OBSERVING/INSUFFICIENT_DATA | collector/API/UI PASS | BLOCKED |
| Search/filter | TC01–TC20 + UI PASS | Frontend bytes deployed; authenticated data BLOCKED |
| Scan history | pagination/unit/UI PASS | BLOCKED |
| Keep/Ignore | API/UI PASS | BLOCKED |
| Settings | validation/UI PASS | BLOCKED |
| Tenant isolation | API/cursor tests PASS | BLOCKED — chưa có hai access token production |
| Responsive mobile | 320/390/768/1440 fixture PASS | 390 px production PASS, không overflow/console error |
| SES/Gmail | render/state tests PASS | Identity PASS; sandbox/DKIM/delivery BLOCKED |

Chấp nhận hiện tại: **release hạ tầng và frontend đã hoạt động ở bề mặt public; chưa đủ bằng chứng để chấp nhận toàn bộ nghiệp vụ production hoặc tuyên bố 38/38 AWS verified.**
