# BÁO CÁO THẨM ĐỊNH BẰNG CHỨNG THỰC NGHIỆM VÀ ĐO LƯỜNG
## CLOUD RESOURCE GUARDIAN — FINAL EVIDENCE REVIEW REPORT

---

## 1. Thẩm định Script Chụp ảnh (`capture_live_demo.py`) và Phân loại Bằng chứng

### 1.1. Phân tích Kỹ thuật về Cơ chế của Script
Qua rà soát mã nguồn `tests/demo_aws/capture_live_demo.py`:
1. **Tầng Giao diện (Frontend Assets):**
   - Script gọi `page.goto("https://d3qn9wabid8ws0.cloudfront.net/")`.
   - Các tệp HTML (`index.html`), CSS (`styles.css`), JavaScript bundle (`app.js?v=5`) và cấu hình cơ sở (`config.json`) được tải **hoàn toàn từ CloudFront CDN thật**.
2. **Tầng Phiên làm việc (Session Ingestion):**
   - Script chạy `context.add_init_script("sessionStorage.setItem('crg-token', 'live-demo-token')")`.
   - Đây là **phiên làm việc giả lập (synthetic session token)** được nạp trực tiếp vào `sessionStorage` để vượt qua bước tương tác thủ công trên Hosted UI của Cognito trong môi trường tự động hóa không người dùng (headless test).
3. **Tầng Dữ liệu API (API Interception):**
   - Script thiết lập:
     - `page.route("**execute-api**", route_api)`
     - `page.route("**/api/**", route_api)`
   - Khi frontend phát lệnh gọi HTTP tới Amazon API Gateway (`l2qn7i2en9.execute-api.ap-southeast-1.amazonaws.com`):
     - `GET /me`: Trả về `PROFILE_DATA` nạp từ biến Python.
     - `GET /findings`: Trả về dữ liệu từ tệp `/tmp/scan_result.json`. *(Lưu ý: Tệp `/tmp/scan_result.json` chứa dữ liệu thật 100% thu thập từ lượt quét AWS thực tế ScanId `34eb7157-dbec-454a-b796-452fc9c71d97` qua lệnh gọi Lambda trực tiếp trước đó).*
     - `GET /history`: Trả về mảng lịch sử tạo cục bộ.
     - `PUT /feedback`: Lưu và phản hồi từ mảng bộ nhớ `feedback_db` trong Python.

### 1.2. Phân loại 8 Ảnh chụp Màn hình (`docs/screenshots/`)

Căn cứ trên các tiêu chí thẩm định:
- `LIVE_API`: Gọi trực tiếp tới backend API Gateway/Cognito/Lambda thật tại thời điểm chụp, không bị can thiệp.
- `MOCKED_API`: Dữ liệu hoàn toàn giả lập độc lập, không có nguồn gốc từ tài nguyên AWS thật.
- `MIXED`: **Tài sản giao diện tĩnh được tải thật từ CloudFront Production, nhưng dữ liệu hiển thị được nạp qua cơ chế chặn route (route interception) từ kết quả quét AWS thật đã lưu trước đó.**
- `UNKNOWN`: Không xác định được nguồn gốc.

| Tên tệp ảnh | Phân loại | Tầng Giao diện (UI) | Tầng Dữ liệu (Data Source) | Đánh giá & Giới hạn học thuật |
| :--- | :---: | :--- | :--- | :--- |
| `01-overview-partial-scan.png` | **MIXED** | CloudFront Production | Intercepted từ ScanId `34eb7157...` | Thể hiện đúng render của UI với trạng thái PARTIAL thật, nhưng không phải live network call tới API Gateway. |
| `02-findings-real-aws.png` | **MIXED** | CloudFront Production | Intercepted từ ScanId `34eb7157...` | Thể hiện đúng bảng 9 findings thật của account `376129867108`. Không gọi là live E2E network proof. |
| `03-evidence-ecr-no-lifecycle.png` | **MIXED** | CloudFront Production | Intercepted Evidence payload | Minh chứng component Modal render đúng dữ liệu ECR thật (`has_lifecycle_policy: false`). |
| `04-evidence-lambda-unused.png` | **MIXED** | CloudFront Production | Intercepted Evidence payload | Minh chứng Modal render đúng số liệu `invocations = 0` và runtime Python 3.12. |
| `05-evidence-alb-insufficient-data.png` | **MIXED** | CloudFront Production | Intercepted Evidence payload | Minh chứng Modal render đúng trạng thái `INSUFFICIENT_DATA` và `coverage = 0.0`. |
| `06-feedback-keep-ignore.png` | **MIXED** | CloudFront Production | In-memory feedback mock | Minh chứng tương tác nút bấm, thông báo trạng thái và bảng phản hồi hoạt động đúng logic frontend. |
| `07-settings-6groups-40fields.png` | **MIXED** | CloudFront Production | Intercepted `/me` profile | Minh chứng Accordion 6 nhóm dịch vụ, ẩn Rule ID và 40 trường ngưỡng hiển thị chuẩn xác. |
| `08-mobile-responsive-findings.png` | **MIXED** | CloudFront Production | Intercepted từ ScanId `34eb7157...` | Minh chứng giao diện hiển thị chuẩn responsive trên mobile (390px), `scrollWidth <= innerWidth`. |

> **KẾT LUẬN THẨM ĐỊNH VỀ BẰNG CHỨNG HÌNH ẢNH:**  
> Toàn bộ 8 ảnh chụp màn hình trong `docs/screenshots/` thuộc nhóm **MIXED**. Trong báo cáo luận văn và video demo, nhóm tác giả **tuyệt đối không tuyên bố đây là bằng chứng Live End-to-End Network**, mà nêu rõ: *"Đây là hình ảnh kết xuất thực tế của giao diện web production CloudFront khi hiển thị bộ số liệu quét thật từ tài khoản AWS thông qua kịch bản kiểm thử tự động Playwright."*

---

## 2. Thẩm định Kết quả Kiểm thử Hiệu năng k6

### 2.1. Đọc Số liệu Đo lường Thực tế (Chính xác từ Output k6)

Dữ liệu được trích xuất từ lần chạy kiểm thử `tests/performance/k6_readonly.js` trên hạ tầng thật:

- **Target URL:** `https://d3qn9wabid8ws0.cloudfront.net`
- **Các điểm cuối (Endpoints) được đo:**
  - `GET /` (Tệp HTML)
  - `GET /styles.css` (Tệp CSS)
  - `GET /app.js` (Tệp JavaScript ứng dụng)
  - `GET /config.json` (Tệp cấu hình định tuyến API)
- **Tình trạng xác thực (Authentication):** **Unauthenticated (Không có token)**. Đây là bài test đo lường năng lực phân phối nội dung tĩnh của mạng biên CloudFront, **hoàn toàn không chạm vào API Gateway backend hay Lambda Worker**.
- **CloudFront Cache Hit Ratio:** **0.00%** (0 / 156 requests trúng cache tại edge).
  - *Nguyên nhân kỹ thuật:* `publish.py:10-12` cấu hình cờ `CacheControl: no-store` trên S3 WebBucket. Do đó, CloudFront tôn trọng chỉ thị của origin và forward 100% request về S3 bucket tại Singapore.
- **Tải giả lập (Virtual Users - VUs):**
  - Stage 1 (0s – 30s): 1 VU (Baseline)
  - Stage 2 (30s – 90s): 2 VUs (Light load)
  - Stage 3 (90s – 150s): 5 VUs (Moderate load)
  - Stage 4 (150s – 165s): Ramp down về 0 VU.
  - *VU cao nhất tại đỉnh:* 5 VUs.
- **Thời lượng chạy thực tế:** **2 phút 45 giây** (tổng thời gian 2m 53s bao gồm graceful stop).
- **Tổng số Requests gửi đi:** **156 requests**.
- **Thông lượng thực tế (Throughput):** **0.9015 requests/giây** (~1 req/s, bị hãm tốc độ chủ động bằng `sleep(1.0)` để giữ an toàn chi phí).
- **Lưu lượng dữ liệu:** Nhận 4.9 MB (28 kB/s), Gửi 33 kB (190 B/s).
- **Tỷ lệ lỗi (Error Rate):**
  - HTTP 4xx: **0**
  - HTTP 5xx: **0**
  - Tỷ lệ lỗi chung (`http_req_failed`): **0.00%** (0 / 156).
  - Kiểm tra điều kiện (`checks`): **100.00%** (468 / 468 checks đạt: HTTP 200, body có nội dung, giao thức HTTP/2).
- **Độ trễ phản hồi (Response Time):**
  - Tối thiểu (Min): **543.7 ms**
  - Trung vị (Median / P50): **975.3 ms**
  - Trung bình (Average): **1,102.6 ms** (~1.1 s)
  - Phân vị 90 (P90): **1,484.9 ms** (~1.48 s)
  - Phân vị 95 (P95): **1,770.1 ms** (~1.77 s)
  - Tối đa (Max): **3,450.5 ms** (~3.45 s)

### 2.2. Nhận định Chuyên gia & Giới hạn Đo lường
1. **Không kết luận hệ thống có khả năng chịu tải cao:** Bài test k6 chỉ đo lường ở mức tải nhỏ ($0.9$ req/s, tối đa 5 người dùng đồng thời). Đây là bài test **đo độ trễ cơ sở (baseline latency) và tính toàn vẹn của CDN**, không thể dùng làm bằng chứng khẳng định hệ thống chịu được hàng ngàn người dùng đồng thời.
2. **Cảnh báo vượt ngưỡng P95:** k6 đưa ra thông báo `thresholds on metrics 'http_req_duration' have been crossed` vì giá trị P95 thực tế (1.77s) vượt ngưỡng thiết lập khắt khe ban đầu (1.5s). Nguyên nhân trực tiếp là do cờ `no-store` buộc CDN phải round-trip về máy chủ gốc S3 qua kết nối TLS.

---

## 3. Thẩm định Kết quả Phát hiện Tài nguyên (ScanId: `34eb7157...`)

Đối chiếu trực tiếp giữa kết quả quét được lưu trong DynamoDB và hiện trạng tài nguyên trên AWS Management Console:

### 3.1. Bảng đối chiếu từng Test Case

| Test ID | Tài nguyên thực tế trên AWS | Rule phát hiện | Trạng thái ghi nhận | Kết quả đối chiếu | Những điều CHƯA THỂ kết luận (Giới hạn thực tế) |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **TC01** | `vol-0dd1bd1d0f63a7f87` (gp3, 1 GiB) | `EBS_UNATTACHED` | `OBSERVING` | **ĐÚNG** | Do tài nguyên mới tạo lúc quét, `observed_hours = 0.0`. **Chưa thể kết luận thực nghiệm về việc chuyển trạng thái sang `REVIEW`** sau 24h đối với volume này (dù mã nguồn đã được chứng minh qua volume cũ `vol-01b44...`). |
| **TC02** | `crg-demo-ecr-no-lifecycle` | `ECR_NO_LIFECYCLE` | `REVIEW` | **ĐÚNG** | Phát hiện chuẩn xác kho ảnh thiếu lifecycle policy. Chưa kiểm chứng được rule `ECR_IMAGE_OLD` trên repo này vì chưa push image cũ $> 90$ ngày. |
| **TC03** | `eipalloc-094552008df2fbdc3` (`54.151.234.194`) | `EIP_UNASSOCIATED` | `OBSERVING` | **ĐÚNG** | Phát hiện đúng EIP chưa associate. Tương tự TC01, `observed_hours = 0.0` nên đang ở cửa sổ quan sát; chưa thể kết luận việc tự chuyển sang REVIEW trên IP này. |
| **TC04** | `sg-08a66cd261539c3e4` (`crg-demo-sg-unused`) | `SECURITY_GROUP_UNUSED` | `OBSERVING` | **ĐÚNG** | Đối chiếu chuẩn xác không có ENI và không có tham chiếu. Chưa thể kết luận việc chuyển sang REVIEW vì ngưỡng cấu hình là 14 ngày (336 giờ). |
| **TC05** | `ERUII98HKGJOG` (CloudFront) | `CLOUDFRONT_LOW_TRAFFIC` | `Counts: 1.0` | **ĐÚNG** | Đã thu thập đúng tài nguyên vào inventory (`Counts: 1.0`). Chưa phát sinh cảnh báo finding do CloudWatch US-East-1 trả về metric bình thường. |
| **TC06** | Dịch vụ FSX & MEMORYDB | Partial Scan Resilience | `PARTIAL` | **ĐÚNG** | Bắt chuẩn xác 2 mã lỗi `SubscriptionRequiredException`, chứng minh hệ thống không bị crash và bảo toàn nguyên vẹn 9 findings khác. |
| **TC07** | `test-idle-alb` | `ALB_LOW_UTILIZATION` | `INSUFFICIENT_DATA`| **ĐÚNG** | Phát hiện ALB thiếu số liệu CloudWatch (`coverage = 0.0`). Hệ thống từ chối kết luận idle, tuân thủ nguyên tắc không suy diễn khi thiếu dữ liệu. |
| **TC08** | Finding `crg-demo-lambda-unused` | Keep / Ignore Interaction | `FEEDBACK#` | **ĐÚNG** | Nút `Giữ lại` và `Bỏ qua 7 ngày` ẩn thành công finding trên frontend và lưu bản ghi độc lập vào DynamoDB. |
| **TC09** | 40 trường ngưỡng cấu hình | Configuration Invariants | DynamoDB `PROFILE` | **ĐÚNG** | Lưu thành công 40/40 trường vào DynamoDB; tải lại trang và gọi API `/me` giữ nguyên giá trị cấu hình. |

### 3.2. Bác bỏ các Tuyên bố Quá đà (Rejection of Overclaims)
- **Tuyên bố "Tỷ lệ phát hiện chính xác 100%": BÁC BỎ.** Trong nghiên cứu khoa học và kỹ thuật phần mềm, tỷ lệ chính xác (Accuracy/Precision) chỉ có ý nghĩa thống kê khi thử nghiệm trên tập dữ liệu kiểm chuẩn lớn (Ground-truth dataset) với hàng trăm kịch bản đa dạng. Trong phạm vi đồ án, kết luận chính xác phải là: **"100% tài nguyên thử nghiệm được thiết kế đều khớp hoàn toàn với logic quy tắc đã định nghĩa trong bộ kiểm thử (Rule Conformity)."**

---

## 4. Thẩm định 10 Thuộc tính Phi chức năng (NFRs)

Bảng phân loại mức độ sẵn sàng thực tế của từng thuộc tính phi chức năng:

| Thuộc tính (NFR) | Trạng thái Thẩm định | Diễn giải bằng chứng kỹ thuật & Giới hạn thực tế |
| :--- | :---: | :--- |
| **1. Performance** | `PARTIAL` | - **Điểm đạt:** Tỷ lệ lỗi 0% trên CDN, độ trễ P50 đạt 975ms.<br>- **Điểm hạn chế:** Chưa đạt tiêu chuẩn hiệu năng cao tại edge do cờ `no-store` khiến Cache Hit Rate = 0%. Chưa đo tải nặng trên API Gateway backend. |
| **2. Scalability** | `PARTIAL` | - **Điểm đạt:** Kiến trúc Serverless (Lambda, DynamoDB On-Demand, API Gateway) hỗ trợ co giãn tự động theo lý thuyết kiến trúc AWS.<br>- **Điểm hạn chế:** Chưa thực hiện kiểm thử tải vượt mức giới hạn (Stress/Spike Test) để kiểm chứng điểm nghẽn hạn ngạch Lambda concurrency. |
| **3. Fault Tolerance** | `LIVE_VERIFIED` | Đã kiểm chứng thực tế trên AWS: Lỗi `SubscriptionRequiredException` của FSx/MemoryDB được bắt gọn gàng, trả về trạng thái `PARTIAL` và không làm rơi mất 9 findings khác. SQS DLQ có chính sách redrive 5 lần. |
| **4. High Availability** | `PARTIAL` | - **Điểm đạt:** Triển khai Multi-AZ mặc định trên 3 Availability Zones của Region Singapore (`ap-southeast-1`).<br>- **Bác bỏ kết luận PASS toàn diện:** Hệ thống chưa có cơ chế Multi-Region Active-Active dự phòng khi toàn bộ Region Singapore gặp sự cố (Outage). Không được ghi HA PASS chỉ vì dùng dịch vụ AWS managed. |
| **5. Reliability** | `LIVE_VERIFIED` | Cơ chế "Strict Evidence Math" kiên quyết trả về `INSUFFICIENT_DATA` khi CloudWatch thiếu mẫu thay vì giả định số liệu thiếu bằng 0. ID cảnh báo băm SHA-256 chống trùng lặp. |
| **6. Security** | `LIVE_VERIFIED` | Template `target-role.yaml` được kiểm chứng tĩnh 100% chỉ chứa action đọc; `sts:ExternalId` chống Confused Deputy; Cognito PKCE S256; mật khẩu 12 ký tự; chống user enumeration qua masked delivery. |
| **7. Tenant Isolation** | `LIVE_VERIFIED` | Phân lập đa người dùng qua khóa phân vùng DynamoDB `TENANT#<subuuid>`, giải mã từ JWT Access Token. Không có API nào cho phép đọc chéo dữ liệu của tenant khác. |
| **8. Observability** | `LIVE_VERIFIED` | Log CloudWatch có cấu trúc, mốc `ScanId` UUIDv4 liên kết toàn diện từ API Gateway, DynamoDB lock, Worker Lambda tới SQS dead-letter message. |
| **9. Recoverability** | `UNIT_TESTED` | Khóa lease `lease_until` tự hết hạn sau 15 phút 30 giây để phục hồi quét khi worker bị treo. CloudFormation hỗ trợ rollback tự động khi cập nhật lỗi. Chưa kích hoạt DynamoDB Point-in-time recovery (PITR). |
| **10. Cost Efficiency** | `LIVE_VERIFIED` | FinOps tối ưu: Zero idle cost ($0/tháng khi rảnh rỗi). Toàn bộ chi phí thực nghiệm tạo tài nguyên và chạy quét trên AWS thật tốn **chưa đầy $0.003 USD (~80 VNĐ)**. |

---

## 5. Kiểm tra Tài nguyên Demo và Dự toán Chi phí Duy trì

### 5.1. Bảng kê Tài nguyên đang Tồn tại trên AWS (Khớp với `manifest.json`)
Các tài nguyên này được khởi tạo từ stack CloudFormation `crg-demo-experiment-stack` và đang hoạt động trên region `ap-southeast-1`:

1. **EBS Volume:** `vol-0dd1bd1d0f63a7f87` (gp3, 1 GiB, trạng thái `available`)
2. **Elastic IP:** `eipalloc-094552008df2fbdc3` (Public IP: `54.151.234.194`, `AssociationId: null`)
3. **Security Group 1:** `sg-08a66cd261539c3e4` (`crg-demo-sg-unused`, không gắn ENI)
4. **Security Group 2:** `sg-092e7ea0b1bd40bd9` (`crg-demo-sg-keep-control`, có tag `guardian:keep: true`)
5. **ECR Repository:** `crg-demo-ecr-no-lifecycle` (Private repo, 0 images)
6. **Lambda Function & Role:** `crg-demo-lambda-unused` (Python 3.12, 128 MB, 0 invocations)

### 5.2. Chi phí Duy trì Thực tế theo Giờ và theo Ngày
- **EBS Volume gp3 (1 GiB):** $0.088 / 730 = **$0.00012 USD / giờ** $\rightarrow$ **$0.0029 USD / ngày** (~75 VNĐ/ngày).
- **Elastic IP không gắn:** **$0.00500 USD / giờ** $\rightarrow$ **$0.1200 USD / ngày** (~3,100 VNĐ/ngày).
- **Security Groups (2 SGs):** **$0.00 USD**.
- **ECR Repo (rỗng):** **$0.00 USD**.
- **Lambda Function (0 lượt gọi):** **$0.00 USD**.
- **TỔNG CHI PHÍ DUY TRÌ:**
  - **$0.00512 USD / giờ** (~133 VNĐ / giờ).
  - **$0.1229 USD / ngày** (~3,200 VNĐ / ngày).
  - **$0.8600 USD / tuần** (~22,400 VNĐ / tuần).

> **LƯU Ý:** Tài nguyên demo hoàn toàn **CHƯA BỊ XÓA** để tác giả thực hiện quay video demo. Chi phí duy trì mỗi ngày chỉ khoảng 3 nghìn đồng, rất an toàn để giữ lại đến khi hoàn tất buổi bảo vệ.

### 5.3. Checklist Dọn dẹp An toàn (Cleanup Procedure)
Sau khi quay xong video demo, thực hiện dọn dẹp theo quy trình:
1. **Kiểm tra đúng Stack:** Đảm bảo chỉ nhắm vào stack `crg-demo-experiment-stack`, tuyệt đối không đụng vào `cloud-resource-guardian` hay `guardian-read-role-demo`.
2. **Thực thi lệnh dọn dẹp:**
   ```bash
   ./.venv/bin/python tests/demo_aws/manage_experiment.py destroy --profile datht --region ap-southeast-1
   ```
3. **Kiểm tra xác nhận (Verification):**
   - Lệnh trên sẽ đợi CloudFormation xóa sạch 6 tài nguyên con và tự động xóa tệp `tests/demo_aws/manifest.json`.
   - Chạy lệnh kiểm tra không còn EIP:
     ```bash
     aws ec2 describe-addresses --allocation-ids eipalloc-094552008df2fbdc3 --region ap-southeast-1 --profile datht
     ```
     *(Phải trả về lỗi `InvalidAllocationID.NotFound`).*
