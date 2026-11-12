# MA TRẬN ĐÁNH GIÁ CHỨC NĂNG HỆ THỐNG
## CLOUD RESOURCE GUARDIAN — FINAL FUNCTIONAL MATRIX

> **Historical snapshot, không phải trạng thái nghiệm thu hiện tại.** Các nhãn `LIVE_VERIFIED` bên dưới chỉ phản ánh evidence cũ và có thể vượt quá bằng chứng còn kiểm tra được. Dùng [FINAL_ACCEPTANCE_AUDIT.md](FINAL_ACCEPTANCE_AUDIT.md) làm ma trận hiện hành.

---

## 1. Phương pháp & Tiêu chí phân loại

Mỗi chức năng được đối chiếu trực tiếp qua 5 tầng:
1. **Mã nguồn (Source Code):** Repository commit `6bff2dd` (Frontend `web/`, Backend `src/`, IaC `template.yaml`).
2. **Hạ tầng AWS (CloudFormation):** Stack `cloud-resource-guardian` và `guardian-read-role-demo` tại `ap-southeast-1`.
3. **Môi trường chạy thực tế (Runtime):** 5 hàm AWS Lambda, API Gateway HTTP API, Cognito User Pool `ap-southeast-1_NwY3bQKBQ`, S3/CloudFront `d3qn9wabid8ws0.cloudfront.net`.
4. **Kiểm thử tự động:** Unit tests (`tests/test_*.py`), UI smoke (`tests/ui_smoke.py`), UI auth & minimalist (`tests/test_ui_auth_and_minimalist.py`), Resilience (`tests/resilience/`).
5. **Thực nghiệm AWS thật:** Lượt quét `34eb7157-dbec-454a-b796-452fc9c71d97` trên tài khoản `376129867108`.

### Bảng ký hiệu trạng thái:
- `LIVE_VERIFIED`: Đã kiểm chứng end-to-end trên môi trường AWS thật và giao diện production.
- `INTEGRATION_TESTED`: Đã kiểm thử tích hợp qua Playwright / HTTP request mô phỏng hoặc cục bộ.
- `UNIT_TESTED`: Đã kiểm thử đơn vị qua mock / assertions tự động trong CI.
- `IMPLEMENTED`: Đã lập trình hoàn chỉnh trong mã nguồn.
- `PARTIAL`: Hoạt động một phần hoặc có điều kiện hạn chế.
- `BROKEN`: Có lỗi logic hoặc không thể vận hành.
- `NOT_TESTED`: Chưa có kịch bản kiểm thử.

---

## 2. Ma trận chức năng Hệ thống Quản trị & Xác thực

| Nhóm chức năng | Tên tính năng | Endpoint / API | Tệp mã nguồn liên quan | Trạng thái | Bằng chứng kiểm chứng | Tồn tại & Lưu ý kỹ thuật |
| :--- | :--- | :--- | :--- | :---: | :--- | :--- |
| **Xác thực** | Đăng ký tài khoản | Cognito `SignUp` | `web/app.js:963`, `web/index.html:52` | `LIVE_VERIFIED` | Gọi thành công tới AWS Cognito IDP `ap-southeast-1_NwY3bQKBQ`, trả về `UserSub` và mã OTP qua email. | Mật khẩu bắt buộc $\ge 12$ ký tự, đủ hoa/thường/số/ký tự đặc biệt. |
| **Xác thực** | Xác minh email | Cognito `ConfirmSignUp` | `web/app.js:1009`, `web/index.html:78` | `LIVE_VERIFIED` | Nhập OTP 6 số kích hoạt tài khoản từ `UNCONFIRMED` sang `CONFIRMED`. | Mã hết hạn hoặc sai được thông báo tiếng Việt tức thì. |
| **Xác thực** | Gửi lại mã OTP | Cognito `ResendConfirmationCode` | `web/app.js:1044`, `web/index.html:85` | `LIVE_VERIFIED` | Gửi lại mã thành công, có rate limiting chống spam. | Không cho phép gửi lại liên tục vượt quota SES. |
| **Xác thực** | Đăng nhập OAuth PKCE | `/oauth2/authorize`, `/oauth2/token` | `web/app.js:332`, `web/index.html:36` | `LIVE_VERIFIED` | Sinh cryptographic verifier, SHA-256 challenge, đổi Authorization Code lấy JWT. | Token lưu trong `sessionStorage`, xóa sạch khi đóng tab. |
| **Xác thực** | Đăng xuất | `/oauth2/logout` | `web/app.js:353`, `web/index.html:27` | `LIVE_VERIFIED` | Xóa token khỏi `sessionStorage`, chuyển hướng Hosted UI logout và dọn sạch state. | Trở về màn hình đăng nhập sạch. |
| **Xác thực** | Quên mật khẩu | Cognito `ForgotPassword` | `web/app.js:1062`, `web/index.html:96` | `LIVE_VERIFIED` | Trả về masked delivery email, chuyển sang màn hình reset. | Cấu hình `PreventUserExistenceErrors` chống user enumeration. |
| **Xác thực** | Đặt lại mật khẩu | Cognito `ConfirmForgotPassword` | `web/app.js:1092`, `web/index.html:110` | `LIVE_VERIFIED` | Đặt mật khẩu mới thành công qua OTP và chuyển về Đăng nhập. | Yêu cầu khớp 5 tiêu chuẩn mật khẩu Cognito. |
| **Kết nối AWS** | Kết nối GuardianReadRole | `PUT /connection` | `src/app.py:676`, `web/app.js:901` | `LIVE_VERIFIED` | `GuardianReadRole-demo` kiểm tra hợp lệ với ExternalId `d31fae05-6d60-4f49-9631-ef06d084280f`. | Chỉ cho phép role prefix `GuardianReadRole-` không có path. |
| **Kết nối AWS** | STS AssumeRole | `sts:AssumeRole` | `src/app.py:118` | `LIVE_VERIFIED` | `ScanRole` assume thành công role chỉ đọc của tài khoản `376129867108`. | Chống Confused Deputy Attack qua `sts:ExternalId`. |
| **Kết nối AWS** | Chọn Region & Service Groups | `PUT /connection` | `src/app.py:680`, `web/index.html:184` | `LIVE_VERIFIED` | Chọn 1–3 region (`ap-southeast-1`), chọn 1–11 nhóm dịch vụ. | Bắt buộc kiểm tra độ dài và whitelist. |
| **Cấu hình** | 40 Ngưỡng phát hiện | `PUT /settings`, `GET /me` | `src/rules.py:7`, `web/app.js:806` | `LIVE_VERIFIED` | Hiển thị 6 nhóm dịch vụ dạng Accordion, lưu và tải lại thành công từ DynamoDB. | Ẩn Rule ID trên UI; không lặp text trợ giúp; chỉ báo lỗi khi ngoài min/max. |
| **Quét** | Quét ngay (Manual) | `POST /scans` | `src/app.py:726`, `web/app.js:949` | `LIVE_VERIFIED` | ScanId `34eb7157-dbec-454a-b796-452fc9c71d97` thực thi trên AWS Lambda Worker. | Cooldown 15 phút giữa 2 lần quét thủ công chống lạm dụng. |
| **Quét** | Quét định kỳ (Scheduled) | EventBridge Rule `rate(1 hour)` | `src/app.py:488`, `template.yaml:140` | `INTEGRATION_TESTED` | `ScheduleFunction` kích hoạt theo lịch `interval_hours` (mặc định 6h) qua SQS DLQ. | Bỏ qua người dùng chưa kết nối role hoặc đang có lease active. |
| **Cảnh báo** | Danh sách Findings | `GET /findings` | `src/app.py:741`, `web/app.js:630` | `LIVE_VERIFIED` | Thu thập 9 findings thực tế (EBS, EIP, SG, ECR, Lambda, ALB). | Phân loại đúng 3 mức: `REVIEW`, `OBSERVING`, `INSUFFICIENT_DATA`. |
| **Bằng chứng** | Chi tiết Evidence | Modal `#finding-dialog` | `web/app.js:464`, `web/index.html:276` | `LIVE_VERIFIED` | Hiển thị bảng thuộc tính kỹ thuật, mốc first/last seen, độ phủ CloudWatch metrics. | Định dạng thời gian RFC3339 UTC, số liệu tabular-nums. |
| **Phản hồi** | Giữ lại (Keep) | `PUT /feedback` (`kept: true`) | `src/app.py:612`, `web/app.js:583` | `LIVE_VERIFIED` | Finding được ẩn khỏi danh sách chính, lưu vào DynamoDB `FEEDBACK#`. | Có thể bấm `Bỏ giữ lại` bất kỳ lúc nào để phục hồi. |
| **Phản hồi** | Bỏ qua (Ignore) | `PUT /feedback` (`ignoreUntil`) | `src/app.py:614`, `web/app.js:588` | `LIVE_VERIFIED` | Ẩn finding trong 1–30 ngày (mặc định 7 ngày), tự hiện lại khi hết hạn. | Hạn bỏ qua tính theo UTC timestamp. |
| **Lịch sử** | Tra cứu Lịch sử quét | `GET /history`, `GET /scans/{id}` | `src/app.py:750`, `web/app.js:732` | `LIVE_VERIFIED` | Phân trang cursor-based 20 bản ghi/trang, drill-down snapshot từng region. | Snapshot lịch sử bất biến, lưu tối đa 30 ngày. |
| **Thông báo** | Cảnh báo qua Email (SES) | Amazon SES `SendEmail` | `src/app.py:1088`, `template.yaml:16` | `UNIT_TESTED` | Kiểm tra SES sandbox, claim token nguyên tử, retry qua SQS DLQ. | Cần kích hoạt SES production nếu gửi ngoài danh sách verified email. |
| **Phân lập** | Multi-tenant Isolation | JWT Authorizer + DynamoDB PK | `src/app.py:53`, `template.yaml:231` | `LIVE_VERIFIED` | Khóa `TENANT#<sub>`, không có API nào cho phép đọc chéo dữ liệu người dùng khác. | Đã kiểm chứng qua bộ kiểm thử `test_resilience_and_security.py`. |

---

## 3. Ma trận 38 Bộ Thu thập Tài nguyên (Collectors) & 39 Detection Rules

| Dịch vụ AWS | Loại tài nguyên (Resource Type) | Detection Rule ID | Collector Function | Ngưỡng cấu hình liên quan | Trạng thái kiểm chứng | Ghi chú kỹ thuật |
| :--- | :--- | :--- | :--- | :--- | :---: | :--- |
| **EC2** | `EC2` | `EC2_LOW_UTILIZATION` | `ec2_instances()` | `cpu_percent`, `network_mib_hour`, `window_hours` | `LIVE_VERIFIED` | Đọc p95 CPU và network trung bình. Cần ít nhất 80% mẫu CloudWatch. |
| **EBS** | `EBS` | `EBS_UNATTACHED` | `ebs_volumes()` | `orphan_hours` (24h) | `LIVE_VERIFIED` | Đã kiểm chứng với `vol-0dd1bd1d0f63a7f87` (trạng thái `OBSERVING`). |
| **VPC** | `EIP` | `EIP_UNASSOCIATED` | `eip_addresses()` | `orphan_hours` (24h) | `LIVE_VERIFIED` | Đã kiểm chứng với `eipalloc-094552008df2fbdc3` (trạng thái `OBSERVING`). |
| **EC2** | `SNAPSHOT` | `SNAPSHOT_OLD_UNREFERENCED` | `snapshots()` | `snapshot_days` (30d) | `INTEGRATION_TESTED` | Đối chiếu BlockDeviceMapping của toàn bộ AMI trước khi kết luận unreferenced. |
| **S3** | `S3_MULTIPART` | `S3_STALE_MULTIPART` | `s3_multipart()` | `multipart_days` (7d) | `INTEGRATION_TESTED` | Rà soát upload parts quá 7 ngày chưa hoàn tất (abort). |
| **RDS** | `RDS` | `RDS_LOW_UTILIZATION` | `rds_instances()` | `rds_cpu_percent`, `rds_connections` | `INTEGRATION_TESTED` | Đọc p95 CPU RDS và số kết nối client. |
| **RDS** | `RDS_SNAPSHOT` | `RDS_SNAPSHOT_OLD` | `rds_snapshots()` | `rds_snapshot_days` (90d) | `INTEGRATION_TESTED` | Chỉ rà soát snapshot thủ công (`manual`), bỏ qua automated backup. |
| **VPC** | `NAT_GATEWAY` | `NAT_LOW_UTILIZATION` | `nat_gateways()` | `nat_mib_hour` (1 MiB/h) | `INTEGRATION_TESTED` | Đo lưu lượng qua cổng NAT trong cửa sổ metrics. |
| **ELB** | `ALB` | `ALB_LOW_UTILIZATION` | `load_balancers()` | `alb_requests_hour` (1 req/h) | `LIVE_VERIFIED` | Đã kiểm chứng với `test-idle-alb` (phân loại chuẩn `INSUFFICIENT_DATA`). |
| **ELB** | `NLB` | `NLB_LOW_UTILIZATION` | `load_balancers()` | `nlb_new_flows_hour` (1 flow/h)| `INTEGRATION_TESTED` | Đo lưu lượng NewFlowCount trên Network Load Balancer. |
| **Lambda** | `LAMBDA_FUNCTION` | `LAMBDA_UNUSED` | `lambda_functions()` | `lambda_unused_days`, `lambda_max_invocations` | `LIVE_VERIFIED` | Đã kiểm chứng với `crg-demo-lambda-unused` (0 invocations, `REVIEW`). |
| **Logs** | `LOG_GROUP` | `LOG_GROUP_NO_RETENTION` | `log_groups()` | `log_group_retention_days` (30d)| `LIVE_VERIFIED` | Phát hiện nhóm log để chế độ `Never Expire`. |
| **VPC** | `SECURITY_GROUP` | `SECURITY_GROUP_UNUSED` | `security_groups()` | `sg_unused_days` (7-14d) | `LIVE_VERIFIED` | Đã kiểm chứng với `sg-08a66cd261539c3e4` (`OBSERVING`), bỏ qua default SG. |
| **DynamoDB**| `DYNAMODB_TABLE` | `DYNAMODB_IDLE` | `dynamodb_tables()` | `dynamodb_idle_days` (14d) | `LIVE_VERIFIED` | Đo ConsumedReadCapacityUnits và ConsumedWriteCapacityUnits. |
| **ECR** | `ECR_REPOSITORY` | `ECR_NO_LIFECYCLE` | `ecr_repositories()` | `ecr_image_days` (90d) | `LIVE_VERIFIED` | Đã kiểm chứng với `crg-demo-ecr-no-lifecycle` (`REVIEW`). |
| **ECR** | `ECR_REPOSITORY` | `ECR_IMAGE_OLD` | `ecr_repositories()` | `ecr_image_days` (90d) | `INTEGRATION_TESTED` | Chỉ cảnh báo khi có image vượt quá số ngày quy định. |
| **SQS** | `SQS_QUEUE` | `SQS_QUEUE_IDLE` | `sqs_queues()` | `sqs_idle_days` (14d) | `LIVE_VERIFIED` | Bỏ qua các hàng đợi Dead Letter Queue (DLQ) theo thiết kế. |
| **ElastiCache**|`ELASTICACHE_CLUSTER`| `ELASTICACHE_IDLE` | `elasticache_clusters()`| `elasticache_idle_days` (7d) | `INTEGRATION_TESTED` | Kiểm tra kết nối CurrConnections tới cụm Redis/Memcached. |
| **EFS** | `EFS_FILE_SYSTEM` | `EFS_NO_MOUNT_TARGET` | `efs_filesystems()` | `efs_no_mount_days` (7d) | `INTEGRATION_TESTED` | Phát hiện EFS không có mount target nào (`NumberOfMountTargets = 0`). |
| **ECS** | `ECS_CLUSTER` | `ECS_CLUSTER_EMPTY` | `ecs_resources()` | `ecs_empty_days` (7d) | `INTEGRATION_TESTED` | Phát hiện Cluster không có running task hay container instance nào. |
| **ECS** | `ECS_SERVICE` | `ECS_SERVICE_IDLE` | `ecs_resources()` | N/A | `INTEGRATION_TESTED` | Cảnh báo service có `desiredCount = 0`. |
| **EC2** | `AUTO_SCALING_GROUP`| `ASG_ZERO_CAPACITY_OLD` | `auto_scaling_groups()`| `asg_zero_days` (7d) | `INTEGRATION_TESTED` | Cảnh báo ASG có desired và min capacity = 0 liên tục. |
| **API GW** | `API_GATEWAY` | `API_GATEWAY_UNUSED` | `api_gateways()` | `apigateway_unused_days` (14d)| `LIVE_VERIFIED` | Đo tổng số request qua CloudWatch `Count`. |
| **SNS** | `SNS_TOPIC` | `SNS_TOPIC_UNUSED` | `sns_topics()` | `sns_unused_days` (30d) | `INTEGRATION_TESTED` | Kiểm tra SubscriptionsConfirmed = 0 và không có tin nhắn publish. |
| **Events** | `EVENTBRIDGE_RULE` | `EVENTBRIDGE_RULE_UNUSED` | `eventbridge_rules()` | `eventbridge_unused_days` (30d)| `LIVE_VERIFIED` | Phát hiện rule ở trạng thái `DISABLED` hoặc thiếu target xử lý. |
| **Step Fn** | `STEP_FUNCTION` | `STEP_FUNCTION_UNUSED` | `step_functions()` | `stepfunctions_unused_days` (30d)| `INTEGRATION_TESTED` | Đo số lượt thực thi `ExecutionsStarted = 0`. |
| **VPC** | `VPC_ENDPOINT` | `VPC_ENDPOINT_UNUSED` | `vpc_endpoints()` | `vpc_endpoint_unused_days` (14d)| `INTEGRATION_TESTED` | Đo lưu lượng truyền tải trên Interface VPC Endpoint. |
| **SageMaker**|`SAGEMAKER_ENDPOINT`| `SAGEMAKER_ENDPOINT_IDLE`| `sagemaker_endpoints()`| `sagemaker_idle_days` (7d) | `INTEGRATION_TESTED` | Đo `Invocations` trên inference endpoint. |
| **OpenSearch**|`OPENSEARCH_DOMAIN`| `OPENSEARCH_IDLE` | `opensearch_domains()` | `opensearch_idle_days` (7d) | `INTEGRATION_TESTED` | Đo SearchRate và IndexingRate. |
| **Redshift**| `REDSHIFT_CLUSTER` | `REDSHIFT_IDLE` | `redshift_clusters()` | `redshift_idle_days` (7d) | `INTEGRATION_TESTED` | Đo DatabaseConnections trên cụm kho dữ liệu. |
| **MSK** | `MSK_CLUSTER` | `MSK_IDLE` | `msk_clusters()` | `msk_idle_days` (7d) | `INTEGRATION_TESTED` | Đo lưu lượng BytesInPerSec / BytesOutPerSec. |
| **Kinesis** | `KINESIS_STREAM` | `KINESIS_IDLE` | `kinesis_streams()` | `kinesis_idle_days` (7d) | `INTEGRATION_TESTED` | Đo PutRecords.Records nạp vào stream. |
| **CloudFront**|`CLOUDFRONT_DISTRIBUTION`|`CLOUDFRONT_LOW_TRAFFIC`| `cloudfront_distributions()`| `cloudfront_requests_day` (100)| `LIVE_VERIFIED` | Đo tổng số request hàng ngày từ CloudWatch US-East-1. |
| **Backup** | `BACKUP_VAULT` | `BACKUP_OLD_RECOVERY_POINT`| `backup_vaults()` | `backup_point_days` (180d) | `INTEGRATION_TESTED` | Kiểm tra các recovery point hết hạn chưa dọn dẹp. |
| **EKS** | `EKS_CLUSTER` | `EKS_IDLE_CANDIDATE` | `eks_clusters()` | `eks_idle_days` (14d) | `INTEGRATION_TESTED` | Cảnh báo cụm EKS control plane có 0 Nodegroup và 0 Fargate profile. |
| **FSx** | `FSX_FILE_SYSTEM` | `FSX_LOW_ACTIVITY` | `fsx_filesystems()` | `fsx_idle_days` (14d) | `LIVE_VERIFIED` | Xử lý an toàn khi account chưa subscribe FSx (`SubscriptionRequiredException`). |
| **MemoryDB**| `MEMORYDB_CLUSTER` | `MEMORYDB_IDLE` | `memorydb_clusters()` | `memorydb_idle_days` (7d) | `LIVE_VERIFIED` | Xử lý an toàn khi account chưa subscribe MemoryDB. |
| **DocDB** | `DOCUMENTDB_CLUSTER`| `DOCUMENTDB_IDLE` | `docdb_neptune_clusters()`| `documentdb_idle_days` (7d) | `INTEGRATION_TESTED` | Kiểm tra kết nối client tới cụm DocumentDB. |
| **Neptune** | `NEPTUNE_CLUSTER` | `NEPTUNE_IDLE` | `docdb_neptune_clusters()`| `neptune_idle_days` (14d) | `INTEGRATION_TESTED` | Kiểm tra kết nối client tới cụm Graph DB Neptune. |
