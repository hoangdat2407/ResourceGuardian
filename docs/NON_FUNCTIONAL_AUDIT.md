# BÁO CÁO ĐÁNH GIÁ YÊU CẦU PHI CHỨC NĂNG (NFRs AUDIT)
## CLOUD RESOURCE GUARDIAN — NON-FUNCTIONAL REQUIREMENTS AUDIT

---

## 1. Phương pháp Đánh giá Phi chức năng

Báo cáo này phân tích 10 thuộc tính phi chức năng cốt lõi dựa trên:
- **Kiến trúc Serverless AWS:** AWS Lambda, Amazon API Gateway HTTP API, Amazon DynamoDB, Amazon S3, Amazon CloudFront, Amazon Cognito, AWS Step Functions/SQS.
- **Dữ liệu thực nghiệm đo lường:** Kết quả kiểm thử hiệu năng k6 thực tế (`tests/performance/k6_readonly.js`) trên CDN production và lượt quét thật `34eb7157-dbec-454a-b796-452fc9c71d97`.
- **Kiểm thử tự động độ bền bỉ & bảo mật:** Bộ test `tests/resilience/test_resilience_and_security.py`.

---

## 2. Chi tiết Đánh giá 10 Thuộc tính Phi chức năng

### 2.1. Performance (Hiệu năng)
- **Kiến trúc & Cơ chế code:**
  - **Mạng biên (Edge CDN):** CloudFront phân phối tài sản tĩnh qua HTTP/2, TLS 1.3 tại hơn 600 điểm PoP trên toàn cầu.
  - **Cơ sở dữ liệu:** DynamoDB On-Demand hỗ trợ truy vấn khóa chính `(pk, sk)` với độ trễ một chữ số mili-giây (single-digit millisecond latency).
  - **Giới hạn thời gian xử lý:** Lambda Worker có cơ chế `time_check()` (`src/collectors.py:65`) theo dõi thời gian thực thi còn lại qua `context.get_remaining_time_in_millis()`, chủ động dừng quét nếu sắp vượt giới hạn 330 giây thay vì bị kill đột ngột.
- **Số liệu đo lường thực tế từ k6 Benchmark (156 requests):**
  - Tỷ lệ lỗi HTTP: **0.00%** (0 / 156 requests).
  - Tốc độ trung bình: **0.902 requests/giây** (tuân thủ giới hạn an toàn $\le 2$ req/s).
  - Độ trễ tối thiểu (Min): **543.7 ms**.
  - Độ trễ trung vị (Median): **975.3 ms**.
  - Độ trễ phân vị 90 (P90): **1,484.9 ms**.
  - Độ trễ phân vị 95 (P95): **1,770.1 ms**.
- **Phát hiện & Khuyến nghị tối ưu:**
  - Hiện tại tệp tĩnh trên S3 WebBucket được tải lên kèm cờ `CacheControl: no-store` trong `publish.py:10-12`. Điều này đảm bảo bản build mới cập nhật ngay lập tức nhưng khiến CloudFront Cache Hit Ratio = 0% (mọi request đều round-trip về origin S3).
  - *Khuyến nghị:* Với các tệp có versioning/hashing (ví dụ `app.js?v=5`), có thể bật `Cache-Control: public, max-age=86400` để giảm độ trễ xuống $< 50$ ms tại edge.
- **Tiêu chuẩn PASS/FAIL:** PASS (0% lỗi HTTP, không có hiện tượng timeout, P95 $< 2$ giây).

---

### 2.2. Scalability (Khả năng Mở rộng)
- **Kiến trúc & Cơ chế code:**
  - **Compute:** AWS Lambda tự động co giãn theo số lượng sự kiện quét mà không cần quản lý cụm máy chủ EC2 hay container cluster.
  - **API Gateway:** HTTP API tự động mở rộng xử lý hàng nghìn request/giây với cấu hình throttling mặc định `ThrottlingBurstLimit: 10`, `ThrottlingRateLimit: 5` (`template.yaml:239`).
  - **Database:** DynamoDB cấu hình `BillingMode: PAY_PER_REQUEST` (`template.yaml:25`), tự động điều chỉnh throughput đọc/ghi tức thì theo tải thực tế mà không cần cấu hình Auto-Scaling hay tính toán Provisioned IOPS.
  - **Xử lý bất đồng bộ:** Lượt quét thủ công kích hoạt Worker Function theo cơ chế bất đồng bộ (`InvocationType="Event"`), tách biệt hoàn toàn luồng phản hồi API với tiến trình quét kéo dài.
- **Rủi ro & Giới hạn:**
  - Hạn ngạch đồng thời của Lambda (Account Concurrency Limit: mặc định 1,000).
  - Giới hạn gọi API đọc của AWS (Throttling từ `DescribeInstances`, `DescribeVolumes`...): Hệ thống đã bọc xử lý `RequestLimitExceeded` và sử dụng `SDK_CONFIG` với cơ chế adaptive retry của botocore.
- **Tiêu chuẩn PASS/FAIL:** PASS.

---

### 2.3. Fault Tolerance (Khả năng Chịu lỗi)
- **Kiến trúc & Cơ chế code:**
  - **Graceful Error Degradation (Xuống cấp an toàn):** Trong `collect_region` (`src/collectors.py:930`), khi một dịch vụ AWS gặp lỗi (như `SubscriptionRequiredException`, `AccessDenied`), hệ thống ghi nhận mã lỗi vào mảng `errors`, chuyển trạng thái sang `PARTIAL` và **không làm mất** các findings đã thu thập thành công từ các dịch vụ khác.
  - **Dead Letter Queue (DLQ):** Toàn bộ sự kiện Lambda thất bại được chuyển hướng tự động vào `DeadLetters` SQS queue (`template.yaml:81`), sau đó `RecoveryFunction` xử lý lại tối đa 5 lần trước khi chuyển sang `OperationsDeadLetters` (`template.yaml:104`).
  - **Idempotency (Tính bất biến):** Cơ chế atomic DynamoDB transaction (`src/app.py:421`) khóa lease `LOCK` với điều kiện `attribute_not_exists(lease_until) OR lease_until <= :now`, ngăn chặn hoàn toàn việc chạy 2 lần quét trùng lặp gây xung đột dữ liệu.
- **Kiểm chứng thực tế:**
  - Lượt quét `34eb7157-dbec-454a-b796-452fc9c71d97` bắt chính xác lỗi `SubscriptionRequiredException` từ 2 dịch vụ chưa đăng ký gói cước (FSX, MemoryDB), bảo toàn đầy đủ 9 findings thực tế.
  - Bộ test `test_resilience_and_security.py` mô phỏng AccessDenied, Timeout, Throttling: 100% PASS.
- **Tiêu chuẩn PASS/FAIL:** PASS.

---

### 2.4. High Availability (Tính Sẵn sàng cao)
- **Kiến trúc & Cơ chế code:**
  - **Hạ tầng Multi-AZ:** Toàn bộ dịch vụ serverless được sử dụng (Lambda, API Gateway, DynamoDB, S3) đều mặc định phân tán trên tối thiểu 3 Availability Zones độc lập tại Region Singapore (`ap-southeast-1a`, `ap-southeast-1b`, `ap-southeast-1c`).
  - **Mạng phân phối CloudFront:** Phân phối lưu lượng qua mạng lưới toàn cầu, tự động định tuyến tránh các nút mạng gặp sự cố.
  - **Scheduled Execution:** EventBridge Rule phân tán theo thời gian, đảm bảo lịch quét định kỳ không bị phụ thuộc vào một máy chủ đơn lẻ.
- **Phân biệt ranh giới kỹ thuật:**
  - High Availability (HA) là đặc tính sẵn sàng của hạ tầng phân tán; hệ thống đạt HA ở tầng ứng dụng và dữ liệu.
  - Tuy nhiên, tính sẵn sàng phụ thuộc vào tình trạng uptime của chính Region AWS `ap-southeast-1`. Hệ thống hiện tại chưa thiết lập Multi-Region Active-Active (đây là đánh giá trung thực, phù hợp phạm vi dự án MVP/Capstone).
- **Tiêu chuẩn PASS/FAIL:** PASS trong phạm vi Single-Region Multi-AZ.

---

### 2.5. Reliability (Độ Tin cậy)
- **Kiến trúc & Cơ chế code:**
  - **Nguyên tắc "Không suy diễn số liệu" (Strict Evidence Math):** Trong `evaluate_ec2`, `evaluate_rds`, `evaluate_load_balancer`, nếu CloudWatch metrics có số mẫu $< 80\%$ cửa sổ quan sát (`coverage < 0.8`), hệ thống **bắt buộc xếp vào `INSUFFICIENT_DATA`** với lý do *"Missing CloudWatch metrics; not classified as idle"*. Tuyệt đối không gán `missing = 0` để báo động giả.
  - **Deduplication:** Finding ID được băm SHA-256 duy nhất từ `[resource_type, region, stable_identity]`. Một tài nguyên không bao giờ bị nhân bản thành 2 cảnh báo trùng nhau trong cùng một lượt quét.
  - **Quản lý phản hồi bền vững:** Thao tác `Giữ lại` (Keep) hoặc `Bỏ qua` (Ignore) được ghi nhận độc lập vào DynamoDB, không làm thay đổi hay ghi đè lên tài nguyên AWS thật.
- **Tiêu chuẩn PASS/FAIL:** PASS.

---

### 2.6. Security (An ninh & An toàn Thông tin)
- **Kiến trúc & Cơ chế code:**
  - **Strictly Read-Only Access:** Template `target-role.yaml` và `test_read_only.py` kiểm tra tĩnh 100% action: tuyệt đối không chứa bất kỳ hành động gây đột biến nào (`stop`, `delete`, `terminate`, `modify`, `update`, `create`, `put`, `abort`).
  - **Phòng chống Confused Deputy:** `GuardianReadRole` bắt buộc kiểm tra điều kiện `sts:ExternalId` khớp với UUID riêng biệt của từng tenant (`target-role.yaml:19`).
  - **Xác thực Token:** API Gateway HTTP API sử dụng JWT Authorizer xác thực chữ ký số từ Cognito User Pool Issuer (`https://cognito-idp.ap-southeast-1.amazonaws.com/${UserPool}`).
  - **Phòng chống User Enumeration:** App Client cấu hình `PreventUserExistenceErrors: ENABLED`. Khi quên mật khẩu, Cognito trả về masked email thành công giả lập kể cả khi tài khoản không tồn tại.
  - **Chính sách mật khẩu nghiêm ngặt:** Bắt buộc 12 ký tự, đủ hoa/thường/số/ký tự đặc biệt.
  - **Không lưu mật khẩu trên client:** Giá trị trường mật khẩu bị xóa khỏi DOM ngay sau khi submit; không lưu trữ vào Web Storage.
- **Tiêu chuẩn PASS/FAIL:** PASS.

---

### 2.7. Tenant Isolation (Phân lập Đa người dùng)
- **Kiến trúc & Cơ chế code:**
  - **Khóa phân vùng DynamoDB:** Hàm `tenant_key(event)` (`src/app.py:53`) giải mã trường `sub` từ JWT Claims để tạo Partition Key dạng `TENANT#<user-sub-uuid>`.
  - **Không có rò rỉ dữ liệu:** Mọi truy vấn `get_item`, `query`, `put_item` đều đóng khung trong `pk = TENANT#<subuuid>`. Người dùng A không có cách nào truy xuất cảnh báo, lịch sử hay cấu hình của người dùng B.
  - **Kiểm chứng tự động:** Bài kiểm thử `test_tenant_isolation_partition_keys_distinct` trong `test_resilience_and_security.py` xác nhận 2 người dùng khác nhau luôn tạo ra 2 partition keys độc lập.
- **Tiêu chuẩn PASS/FAIL:** PASS.

---

### 2.8. Observability (Khả năng Quan sát & Giám sát)
- **Kiến trúc & Cơ chế code:**
  - **CloudWatch Logs:** Toàn bộ 5 hàm Lambda đều ghi log có cấu trúc (structured JSON/format logs), bao gồm `scan_dispatched`, `scan_completed`, `scan_failed`, `worker_event`.
  - **Metric Series Logging:** Ghi nhận chi tiết số mẫu CloudWatch nhận được, số mẫu hợp lệ, số mẫu lỗi và độ phủ trong `evidence`.
  - **Traceability:** Mỗi lượt quét được định danh bằng một `ScanId` (UUIDv4) xuyên suốt từ API Gateway, DynamoDB lock, Worker Lambda tới SQS dead-letter message.
  - **Trực quan hóa trên UI:** Bảng điều khiển phân loại trực quan các trạng thái `Hoàn tất` (xanh), `Chưa đầy đủ` (cam), `Lỗi` (đỏ), kèm footnote mô tả chi tiết nguyên nhân kỹ thuật.
- **Tiêu chuẩn PASS/FAIL:** PASS.

---

### 2.9. Recoverability (Khả năng Phục hồi)
- **Kiến trúc & Cơ chế code:**
  - **Tự động phục hồi Lease:** Khi một worker gặp sự cố chết giữa chừng, khóa `lease_until` trong DynamoDB sẽ tự hết hạn sau 15 phút 30 giây (`JOB_SECONDS + 30`). Lượt quét tiếp theo sẽ tự động dọn dẹp marker treo và đánh dấu `TIMED_OUT` (`src/app.py:414`) để giải phóng hệ thống.
  - **Redrive Policy:** Hàng đợi `DeadLetters` chuyển tiếp các bản tin lỗi sang `OperationsDeadLetters` sau 5 lần thử lại (`maxReceiveCount: 5`), lưu giữ bản tin tối đa 14 ngày (`MessageRetentionPeriod: 1209600`) phục vụ điều tra nguyên nhân gốc.
  - **Phục hồi Triển khai (IaC Rollback):** Toàn bộ hạ tầng được định nghĩa bằng CloudFormation. Khi một lệnh cập nhật thất bại, CloudFormation tự động rollback về trạng thái trước đó mà không làm gián đoạn hệ thống.
- **Tiêu chuẩn PASS/FAIL:** PASS.

---

### 2.10. Cost Efficiency (Hiệu quả Chi phí - FinOps)
- **Kiến trúc & Cơ chế code:**
  - **Zero Idle Cost (Chi phí bằng 0 khi rảnh rỗi):** Kiến trúc 100% Serverless. Không có máy chủ EC2 hay container chạy ngầm tốn tiền theo giờ. Khi không có lượt quét, chi phí tính toán là $0.00.
  - **Free Tier Tối ưu:**
    - CloudFront: Miễn phí 1 TB truyền dữ liệu mỗi tháng.
    - Lambda: Miễn phí 1,000,000 lượt gọi và 400,000 GB-giây tính toán mỗi tháng.
    - DynamoDB: Miễn phí 25 GB lưu trữ và 25 WCU / 25 RCU On-Demand tier.
  - **Bảo vệ Ngân sách Quét:** Cooldown 15 phút giữa 2 lần quét thủ công ngăn chặn việc bấm nút liên tục làm phát sinh chi phí gọi API CloudWatch.
  - **Chi phí Thử nghiệm Thực tế:** Toàn bộ quá trình tạo 6 tài nguyên AWS thật và chạy quét tốn chưa đầy $0.003 USD (~80 VNĐ).
- **Tiêu chuẩn PASS/FAIL:** PASS.
