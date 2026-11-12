# Resource Filter Coverage Audit

Ngày audit source/local: 2026-11-05. Không deploy, không gọi scan AWS thật, không đọc/ghi DynamoDB production, không gửi SES.

## Kết luận

Không tuyên bố **FULL PRODUCTION COVERAGE**. Source hiện có 38 resource type, 39 rule ID, 36 collector function cho resource, 40 threshold field và 12 service group selectable. Local code đã có inventory identity tách khỏi findings, pagination và filter dynamic. Deployment vẫn bị chặn bởi route CloudFormation `/inventory` và ba quyền target-role chưa được phê duyệt; production data chưa được tái xác minh.

Phân loại:

- `SUPPORTED`: có collector thực sự và reachable từ service group.
- `DETECTED`: scan hợp lệ có `counts[type] > 0`; count có thể là cận dưới nếu bị cap.
- `HAS_FINDINGS`: có ít nhất một finding đã lưu, độc lập với inventory.
- `NOT_SCANNED`: service group/region không thuộc scan.
- `SCAN_ERROR`: collector/API/permission/time/cap thất bại hoặc dữ liệu không đầy đủ.
- `NOT_SUPPORTED`: không có collector trong registry; không có type registry nào thuộc trạng thái này.

## A. Danh mục resource type từ source

| Resource Type | Collector | Rule | Inventory | Findings | Filter | Status |
|---|---|---|---|---|---|---|
| `EC2` | Có | `EC2_LOW_UTILIZATION` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `EBS` | Có | `EBS_UNATTACHED` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `EIP` | Có | `EIP_UNASSOCIATED` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `SNAPSHOT` | Có | `SNAPSHOT_OLD_UNREFERENCED` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `S3_MULTIPART` | Có | `S3_STALE_MULTIPART` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `RDS` | Có | `RDS_LOW_UTILIZATION` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `NAT_GATEWAY` | Có | `NAT_LOW_UTILIZATION` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `ALB` | Có | `ALB_LOW_UTILIZATION` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `NLB` | Có | `NLB_LOW_UTILIZATION` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `LAMBDA_FUNCTION` | Có | `LAMBDA_UNUSED` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `LOG_GROUP` | Có | `LOG_GROUP_NO_RETENTION` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `SECURITY_GROUP` | Có | `SECURITY_GROUP_UNUSED` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `RDS_SNAPSHOT` | Có | `RDS_SNAPSHOT_OLD` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `DYNAMODB_TABLE` | Có | `DYNAMODB_IDLE` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `ECR_REPOSITORY` | Có | `ECR_NO_LIFECYCLE`; `ECR_IMAGE_OLD` | Identity + count | Theo scan | Dynamic | SUPPORTED; IAM deployment blocked |
| `SQS_QUEUE` | Có | `SQS_QUEUE_IDLE` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `ELASTICACHE_CLUSTER` | Có | `ELASTICACHE_IDLE` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `EFS_FILE_SYSTEM` | Có | `EFS_NO_MOUNT_TARGET` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `ECS_CLUSTER` | Có | `ECS_CLUSTER_EMPTY` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `ECS_SERVICE` | Có | `ECS_SERVICE_IDLE` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `AUTO_SCALING_GROUP` | Có | `ASG_ZERO_CAPACITY_OLD` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `API_GATEWAY` | Có | `API_GATEWAY_UNUSED` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `SNS_TOPIC` | Có | `SNS_TOPIC_UNUSED` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `EVENTBRIDGE_RULE` | Có | `EVENTBRIDGE_RULE_UNUSED` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `STEP_FUNCTION` | Có | `STEP_FUNCTION_UNUSED` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `VPC_ENDPOINT` | Có | `VPC_ENDPOINT_UNUSED` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `SAGEMAKER_ENDPOINT` | Có | `SAGEMAKER_ENDPOINT_IDLE` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `OPENSEARCH_DOMAIN` | Có | `OPENSEARCH_IDLE` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `REDSHIFT_CLUSTER` | Có | `REDSHIFT_IDLE` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `MSK_CLUSTER` | Có | `MSK_IDLE` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `KINESIS_STREAM` | Có | `KINESIS_IDLE` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `CLOUDFRONT_DISTRIBUTION` | Có | `CLOUDFRONT_LOW_TRAFFIC` | Identity + count | Theo scan | Dynamic | SUPPORTED; one owner region |
| `BACKUP_VAULT` | Có | `BACKUP_OLD_RECOVERY_POINT` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `EKS_CLUSTER` | Có | `EKS_IDLE_CANDIDATE` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `FSX_FILE_SYSTEM` | Có | `FSX_LOW_ACTIVITY` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `MEMORYDB_CLUSTER` | Có | `MEMORYDB_IDLE` | Identity + count | Theo scan | Dynamic | SUPPORTED |
| `DOCUMENTDB_CLUSTER` | Có | `DOCUMENTDB_IDLE` | Identity + count | Theo scan | Dynamic | SUPPORTED; IAM deployment blocked |
| `NEPTUNE_CLUSTER` | Có | `NEPTUNE_IDLE` | Identity + count | Theo scan | Dynamic | SUPPORTED; IAM deployment blocked |

`Identity + count` chỉ áp dụng cho scan tạo bởi backend mới. Scan legacy vẫn chỉ có aggregate count.

## B. Resource type trong inventory

Collector ghi identity cho cả resource có và không có finding. Worker lưu page DynamoDB riêng theo tenant + connection version + scan + region + run token + type, 25 identity/page, TTL 30 ngày. RESULT giữ counts và metadata, không nhét danh sách vào item 300 KiB. API `/inventory` Query trong partition tenant, lọc type/service/region/q và trả cursor.

Danh mục type của một scan được dựng từ chính identity đã persist; legacy fallback dùng positive count và ghi rõ aggregate-only. Danh mục production từng scan: **NOT_TESTED**.

## C. Resource type có findings

Findings scope lấy union `REVIEW`, `OBSERVING`, `INSUFFICIENT_DATA`, không chỉ REVIEW. Một resource có nhiều findings vẫn giữ nhiều record nhưng KPI affected dùng identity duy nhất. History search đi hết `next_token` trước khi dựng options.

Fixture local có finding cho 37 type và một type inventory-only; history bổ sung type còn lại. Danh mục production: **NOT_TESTED**.

## D. Backend type thiếu filter

Hiện local fixture xác minh 38/38 type registry được frontend chấp nhận. Không còn static resource-type option rút gọn. Mapping frontend có fallback nên backend type mới không bị bỏ chỉ vì thiếu label.

## E. Option filter không có dữ liệu

- Inventory detail: option từ identity của scan.
- Inventory legacy: option từ count dương; không có Resource ID/name giả.
- Findings: option từ finding của scan.
- History: option từ findings của mọi page retained.
- Đổi scan giữ scope nhưng xóa filter/option không còn hợp lệ và hủy request cũ.

Service group ở màn kết nối là capability, không phải bằng chứng account có resource.

## F. Giới hạn API và completeness

1. Tối đa 100 resource/type/region. Vượt cap → `PARTIAL` + limit error; count là cận dưới.
2. Tối đa 50 finding hiển thị, 100 candidate/region, RESULT 300 KiB. Dữ liệu bị cắt không thể được search như dữ liệu chưa lưu.
3. Inventory identity page không bị giới hạn 50 findings; identity có thể có 0, 1 hoặc nhiều findings.
4. `/inventory` limit 1–500 và cursor bound tenant/scan/filter. Hiện API đọc các page của scan rồi lọc/sort trong Lambda; bounded nhưng read amplification tăng theo inventory scan.
5. `/history` limit 1–100; frontend exhaust cursor và phát hiện token lặp. History hiện lưu findings + aggregate counts, không có cross-scan inventory identity search hoàn chỉnh.
6. `PARTIAL`, `FAILED`, `TIMED_OUT`, permission, resource/finding/candidate cap và history-page error không được diễn giải thành “0 resource” hoặc complete.
7. CloudFront chỉ chạy tại owner region xác định: `us-east-1` nếu được chọn, nếu không là region được chọn đầu tiên theo thứ tự.
8. ECR image age dùng mọi page `DescribeImages` và timestamp `imagePushedAt`; AccessDenied tạo PARTIAL, không dùng age 0.
9. Lambda event-source mappings, Backup recovery points và EKS nodegroup/Fargate profile được phân trang; required subrequest AccessDenied không còn bị nuốt.
10. Production target role chưa có ba action read-only nêu ở phần A; các collector liên quan sẽ SCAN_ERROR cho đến khi duyệt IAM.

## G. Thay đổi frontend

- Ba scope: inventory, findings hiện tại, findings lịch sử.
- Inventory detail search theo ID, name, service, type, region, account, scan ID và scan time; legacy chỉ filter aggregate.
- Dynamic option/count đúng scope; resource count không dùng finding count.
- AND giữa field; select hiện single-value nên OR cùng field không áp dụng.
- Search findings gồm ID/name/finding ID/rule ID/service/type/region/reason.
- Status/rule/acknowledged/diff/sort chỉ áp dụng findings.
- Loading/empty/error/PARTIAL/aggregate-only notices; chips, clear-all và result count.
- Scan change giữ mode, reset filter stale và không nhận response request cũ.
- Type option searchable, keyboard usable; 320px fixture không overflow.
- Keep/Ignore quản lý trong feedback dataset riêng; current `/findings` cố ý ẩn active kept/ignored nên filter chính không giả vờ có dữ liệu đó.

## H. Backend/deployment còn cần

Đã implement source:

- inventory identity page model + retention;
- worker persistence retry-safe;
- `/inventory` API;
- collector identity for 38 registry types;
- completeness flags và legacy aggregate fallback.

`BLOCKED_DEPLOYMENT` cần duyệt:

1. Thêm route Cognito-authorized `GET /inventory` trong `template.yaml`.
2. Thêm `ecr:DescribeImages`, `docdb:DescribeDBClusters`, `neptune:DescribeDBClusters` vào cả hai target-role template. Không thêm quyền ghi.
3. Deploy backend trước frontend và chạy tenant/pagination/PARTIAL smoke.

Không có table schema replacement/GSI/data rewrite. Item model additive; old code bỏ qua pages, old scans vẫn aggregate-only. Cross-scan inventory identity/date search server-side vẫn **PARTIAL/MISSING**; UI nói rõ history là findings history.

## I. Kết quả test local

- `CRG_AWS_E2E=0 .venv/bin/python -m unittest discover -s tests -v`: **422 PASS, 1 SKIP** (AWS E2E gate).
- 13 local Playwright scripts, gồm resource-type coverage TC01–TC20: **13 PASS**; viewport 320/390/768/1440 tùy suite.
- `node --check web/app.js`: PASS.
- Python compile cho source và test mới: PASS.
- `cfn-lint` qua Python entrypoint cho ba template: PASS.

Local/mock/Moto/demo test không thay thế AWS E2E.

## J. Chưa xác minh production

- 38 collector/rule trên resource và CloudWatch metrics thật.
- Route `/inventory`, inventory pages và IAM mới trên stack.
- Account có hơn 100 resource/type, timeout/cap lớn và chi phí read/write thực tế.
- CloudFront dedup, ECR image age, DocumentDB/Neptune permission trên AWS.
- Cross-tenant request với hai Cognito user thật.
- SES send/delivery/Gmail, DKIM/SPF/DMARC/custom MAIL FROM.
- Frontend bytes trên CloudFront, production responsive/console/network.

Kết luận chính xác: **local/source coverage đầy đủ cho 38 type trong dataset hợp lệ; production coverage và historical full-inventory search chưa được chứng minh.**
