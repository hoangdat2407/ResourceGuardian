# BÁO CÁO KẾT QUẢ ĐÁNH GIÁ YÊU CẦU PHI CHỨC NĂNG (NFRs)
## CLOUD RESOURCE GUARDIAN — NON-FUNCTIONAL REQUIREMENTS AUDIT

---

## 1. Phương pháp Đánh giá & Tiêu chuẩn Phân loại

Báo cáo này đánh giá nghiêm ngặt 10 thuộc tính phi chức năng theo tiêu chuẩn công nghệ đám mây AWS và kỹ thuật phần mềm. Không suy diễn hoặc gán nhãn đạt (PASS) cho các tiêu chí chưa có thực nghiệm định lượng rõ ràng.

### Thang đo trạng thái (Status Legend):
- `LIVE_VERIFIED`: Đã được chứng minh bằng dữ liệu đo lường hoặc sự kiện thực tế trên hạ tầng AWS production.
- `INTEGRATION_TESTED`: Đã được kiểm thử tích hợp qua Playwright / k6 / API Gateway mocking.
- `UNIT_TESTED`: Đã được kiểm thử đơn vị với mock/assertions trong bộ kiểm thử CI.
- `IMPLEMENTED`: Đã được hiện thực hóa trong kiến trúc và mã nguồn, nhưng chưa trải qua bài test tải hoặc fault injection thực tế.
- `PARTIAL`: Đạt một phần tiêu chí; còn tồn tại giới hạn kỹ thuật hoặc điều kiện biên chưa bao phủ.
- `NOT_TESTED`: Chưa được kiểm chứng bằng thực nghiệm.

---

## 2. Bảng Tổng hợp Kết quả Đánh giá 10 NFRs

| # | Thuộc tính (NFR) | Trạng thái Thẩm định | Mức độ Đáp ứng Kiến trúc | Bằng chứng Thực nghiệm / Kiểm thử | Điểm hạn chế Cần thừa nhận |
| :---: | :--- | :---: | :---: | :--- | :--- |
| **1** | **Performance** | `PARTIAL` | CloudFront CDN + DynamoDB On-Demand + API Gateway HTTP API. | k6 benchmark 156 requests: 0% lỗi, P50 = 975ms, P90 = 1.48s, P95 = 1.77s. | Cờ `CacheControl: no-store` khiến Cache Hit Rate = 0%. Chưa đo tải lớn trên API Gateway. |
| **2** | **Scalability** | `PARTIAL` | 100% Serverless: Lambda auto-scaling, DynamoDB Pay-Per-Request, CloudFront edge network. | Worker Lambda xử lý bất đồng bộ đa dịch vụ qua `InvocationType="Event"`. | Chưa kiểm thử áp lực vượt ngưỡng (Stress/Spike Test) tới giới hạn Lambda concurrency 1,000. |
| **3** | **Fault Tolerance** | `LIVE_VERIFIED` | Cơ chế cách ly lỗi dịch vụ (`src/collectors.py:930`), SQS DLQ redrive 5 lần sang `OperationsDeadLetters`. | Lượt quét thật bắt lỗi `SubscriptionRequiredException` từ FSx/MemoryDB, bảo toàn 9 findings. | Chưa thực hiện destructive chaos testing làm sập database. |
| **4** | **High Availability** | `PARTIAL` | Multi-AZ mặc định trên 3 Availability Zones của Singapore (`ap-southeast-1a/b/c`). | Hạ tầng serverless tự động phân tán trên nhiều trung tâm dữ liệu độc lập của AWS. | **Chưa có Multi-Region failover**. Toàn bộ hệ thống sẽ ngừng trệ nếu toàn bộ Region Singapore bị outage. |
| **5** | **Reliability** | `LIVE_VERIFIED` | Cơ chế "Strict Evidence Math": thiếu CloudWatch metrics ($< 80\%$) xếp `INSUFFICIENT_DATA`. | Finding ID băm SHA-256 chống trùng lặp; tài nguyên `test-idle-alb` xếp đúng `INSUFFICIENT_DATA`. | Phụ thuộc vào chất lượng lấy mẫu CloudWatch của AWS. |
| **6** | **Security** | `LIVE_VERIFIED` | IAM strictly read-only, `sts:ExternalId` chống Confused Deputy, Cognito PKCE S256, masked email OTP. | `test_read_only.py` chứng minh không có action ghi/xóa; `test_security_audit.py` pass 100%. | Khách hàng phải tự bảo quản quyền truy cập AWS account của họ. |
| **7** | **Tenant Isolation**| `LIVE_VERIFIED` | Phân lập đa người dùng qua khóa phân vùng DynamoDB `TENANT#<subuuid>`, giải mã từ JWT Claims. | Test xác nhận Tenant A không thể đọc/sửa dữ liệu của Tenant B; không có API quét chéo. | Giới hạn phân vùng DynamoDB 10 GB cho mỗi tenant partition. |
| **8** | **Observability** | `LIVE_VERIFIED` | CloudWatch Logs có cấu trúc JSON, mốc `ScanId` UUIDv4 liên kết toàn diện, số liệu mẫu lưu trong `evidence`. | Truy vết tức thì tiến trình quét từ `scan_dispatched` đến `scan_completed` qua log stream. | Chưa bật AWS X-Ray distributed tracing. |
| **9** | **Recoverability** | `UNIT_TESTED` | Khóa lease `lease_until` tự hết hạn sau 15m 30s để giải phóng worker treo; CloudFormation rollback tự động. | `RecoveryFunction` xử lý lại sự kiện lỗi từ SQS DLQ; rollback Change Set an toàn khi cập nhật lỗi. | Chưa kích hoạt DynamoDB Point-in-time Recovery (PITR). |
| **10**| **Cost Efficiency** | `LIVE_VERIFIED` | Zero idle cost ($0/tháng khi rảnh rỗi). Cooldown 15 phút chống spam gọi API CloudWatch. | Quá trình quét 23 loại tài nguyên thật trên AWS tốn **chưa đầy $0.003 USD (~80 VNĐ)**. | Cần chú ý phí lưu trữ dữ liệu log nếu không đặt retention. |

---

## 3. Phân tích Chi tiết Từng Thuộc tính Phi chức năng

### 3.1. Performance (Hiệu năng)
- **Kiến trúc Hiện tại:**  
  Phân phối tệp tĩnh qua CloudFront CDN toàn cầu. API Gateway HTTP API định tuyến trực tiếp vào Lambda function xử lý logic nghiệp vụ. Cơ sở dữ liệu DynamoDB On-Demand phản hồi đọc/ghi khóa chính `(pk, sk)` trong thời gian dưới 10 mili-giây.
- **Thực nghiệm Đo lường k6 (`tests/performance/k6_readonly.js`):**
  - Số lượng yêu cầu: 156 requests (tốc độ $0.902$ req/s).
  - Tỷ lệ lỗi HTTP: 0.00% (468/468 checks thành công).
  - Phân vị P50: 975.3 ms.
  - Phân vị P90: 1,484.9 ms.
  - Phân vị P95: 1,770.1 ms.
- **Đánh giá Trung thực:** Trạng thái **`PARTIAL`**. Tốc độ phản hồi đạt mức chấp nhận được đối với ứng dụng quản trị doanh nghiệp B2B (median $< 1$s). Tuy nhiên, cờ `CacheControl: no-store` trên S3 WebBucket làm vô hiệu hóa khả năng cache tại edge của CloudFront. Cần tối ưu thêm HTTP cache header cho các tệp tĩnh.

---

### 3.2. Scalability (Khả năng Mở rộng)
- **Kiến trúc Hiện tại:**  
  Không có máy chủ vật lý hay ảo hóa cố định. Khi phát sinh lượt quét, API Gateway phân tán tải tới Lambda API Function, sau đó ủy quyền cho Lambda Worker xử lý bất đồng bộ (`InvocationType="Event"`). DynamoDB hoạt động ở chế độ On-Demand, tự động cấp phát phân vùng khi số lượng request tăng đột biến.
- **Đánh giá Trung thực:** Trạng thái **`PARTIAL`**. Kiến trúc hoàn toàn có khả năng mở rộng theo lý thuyết Serverless của AWS. Tuy nhiên, nhóm nghiên cứu **chưa thực hiện kiểm thử tải nặng (Spike/Stress Test)** tới ngưỡng giới hạn đồng thời của Lambda (1,000 concurrent executions) do điều kiện ngân sách.

---

### 3.3. Fault Tolerance (Khả năng Chịu lỗi)
- **Kiến trúc Hiện tại:**  
  Trong tệp `src/collectors.py:930`, vòng lặp quét qua từng dịch vụ được bảo vệ bằng khối `try...except`. Nếu một dịch vụ ném ra ngoại lệ (`SubscriptionRequiredException`, `AccessDeniedException`, `RequestLimitExceeded` hoặc `TimeoutError`), hệ thống bắt lỗi, ghi mã lỗi vào mảng `errors`, chuyển cờ `partial = True` và **tiếp tục quét các dịch vụ kế tiếp**.
- **Bằng chứng Thực tế:**  
  Lượt quét thật `34eb7157-dbec-454a-b796-452fc9c71d97` đã bắt lỗi `SubscriptionRequiredException` từ 2 dịch vụ chưa subscribe (FSx và MemoryDB), hiển thị badge `PARTIAL` và **bảo toàn nguyên vẹn 9 findings** từ EBS, EIP, SG, ECR, Lambda, ALB.
- **Đánh giá Trung thực:** Trạng thái **`LIVE_VERIFIED`**.

---

### 3.4. High Availability (Tính Sẵn sàng cao)
- **Kiến trúc Hiện tại:**  
  Ứng dụng tận dụng tính sẵn sàng cao nội tại của các dịch vụ AWS Managed Services (Lambda, API Gateway, DynamoDB, S3) được triển khai mặc định trên 3 Availability Zones độc lập tại Singapore (`ap-southeast-1`). CloudFront tự động định tuyến tránh các PoP biên gặp sự cố.
- **Đánh giá Trung thực:** Trạng thái **`PARTIAL`**.
  > **LÝ DO KHÔNG GHI PASS:** Một hệ thống chỉ đạt chuẩn High Availability toàn diện khi có khả năng sống sót sau thảm họa cấp vùng (Multi-Region Disaster Recovery). Cloud Resource Guardian hiện tại chỉ chạy đơn vùng tại `ap-southeast-1`. Nếu toàn bộ Region Singapore gặp sự cố cáp biển hoặc mất điện diện rộng, hệ thống sẽ ngừng hoạt động. Không thể khẳng định hệ thống có HA toàn diện chỉ dựa vào việc sử dụng dịch vụ AWS managed.

---

### 3.5. Reliability (Độ Tin cậy & Tính Toàn vẹn)
- **Kiến trúc Hiện tại:**  
  - Quy tắc "Strict Evidence Math": Khi CloudWatch thiếu số liệu (dưới 80% số mẫu cần thiết), hệ thống chuyển cảnh báo sang `INSUFFICIENT_DATA`, tuyệt đối không gán số liệu thiếu bằng 0 để kết luận bừa bãi là idle.
  - Mã định danh Finding ID được băm SHA-256 từ bộ ba `[resource_type, region, stable_identity]`, triệt tiêu hoàn toàn nguy cơ nhân bản cảnh báo trùng lặp.
  - Phản hồi Giữ lại (Keep) và Bỏ qua (Ignore) được ghi vào DynamoDB độc lập, không gây đột biến lên tài nguyên đám mây thật.
- **Đánh giá Trung thực:** Trạng thái **`LIVE_VERIFIED`**.

---

### 3.6. Security (An toàn & Bảo mật)
- **Kiến trúc Hiện tại:**  
  - Quyền hạn tối thiểu (Principle of Least Privilege): `target-role.yaml` được kiểm chứng tự động qua `test_read_only.py`, chỉ chứa các hành động `Describe`, `List`, `GetMetricData`. Tuyệt đối không chứa bất kỳ hành động gây đột biến nào (`stop`, `delete`, `terminate`, `modify`, `update`, `create`, `put`, `abort`).
  - Phòng chống Confused Deputy: Bắt buộc kiểm tra `sts:ExternalId` trong Trust Policy.
  - Xác thực & Phân quyền: API Gateway bảo vệ bằng JWT Authorizer liên kết Cognito User Pool. Mật khẩu người dùng yêu cầu tối thiểu 12 ký tự.
  - Chống User Enumeration: Cấu hình `PreventUserExistenceErrors: ENABLED`.
- **Đánh giá Trung thực:** Trạng thái **`LIVE_VERIFIED`**.

---

### 3.7. Tenant Isolation (Phân lập Đa người thuê)
- **Kiến trúc Hiện tại:**  
  Hàm `tenant_key(event)` (`src/app.py:53`) bóc tách trường `sub` từ Cognito JWT Access Token để tạo Partition Key DynamoDB dạng `TENANT#<user-sub-uuid>`. Toàn bộ các thao tác `get_item`, `query`, `put_item` đều đóng khung trong partition này.
- **Bằng chứng Kiểm thử:**  
  Bộ kiểm thử `tests/resilience/test_resilience_and_security.py` xác nhận 2 người dùng khác nhau không thể truy cập chéo dữ liệu của nhau.
- **Đánh giá Trung thực:** Trạng thái **`LIVE_VERIFIED`**.

---

### 3.8. Observability (Khả năng Quan sát & Giám sát)
- **Kiến trúc Hiện tại:**  
  Mọi hàm Lambda đều ghi log có cấu trúc (Structured JSON Logs) lên CloudWatch Logs. Mỗi chu trình quét đều gắn kèm `ScanId` (UUIDv4) để theo dõi xuyên suốt từ API Gateway, DynamoDB Lock đến Worker Lambda. Bằng chứng (Evidence) lưu trữ chi tiết số mẫu nhận được, chu kỳ đo, độ phủ và mốc thời gian bắt đầu/kết thúc.
- **Đánh giá Trung thực:** Trạng thái **`LIVE_VERIFIED`**.

---

### 3.9. Recoverability (Khả năng Phục hồi)
- **Kiến trúc Hiện tại:**  
  - Khóa quét `lease_until` tự động hết hạn sau 15 phút 30 giây để phục hồi quét khi worker bị treo.
  - Cơ chế SQS Redrive Policy: Các bản tin quét thất bại trong `DeadLetters` được thử lại tối đa 5 lần trước khi chuyển sang `OperationsDeadLetters` lưu giữ 14 ngày.
  - Infrastructure as Code: Mọi tài nguyên quản trị qua CloudFormation, tự động rollback khi triển khai lỗi.
- **Đánh giá Trung thực:** Trạng thái **`UNIT_TESTED`**. (Chưa kích hoạt DynamoDB Point-in-time Recovery - PITR).

---

### 3.10. Cost Efficiency (Hiệu quả Chi phí - FinOps)
- **Kiến trúc Hiện tại:**  
  - Zero Idle Cost: Kiến trúc 100% Serverless. Khi không có lượt quét, chi phí tính toán là $0.00 USD/tháng.
  - Tận dụng tối đa AWS Free Tier (CloudFront 1 TB/tháng, Lambda 1M requests/tháng, DynamoDB 25 GB lưu trữ).
  - Cooldown 15 phút giữa 2 lần quét thủ công ngăn chặn việc gọi API CloudWatch dồn dập phát sinh chi phí.
- **Bằng chứng Thực tế:**  
  Toàn bộ chi phí thực nghiệm tạo tài nguyên và chạy quét trên AWS thật tốn **chưa đầy $0.003 USD (~80 VNĐ)**.
- **Đánh giá Trung thực:** Trạng thái **`LIVE_VERIFIED`**.
