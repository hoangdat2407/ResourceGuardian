# KẾ HOẠCH THỰC NGHIỆM PHÁT HIỆN TÀI NGUYÊN AWS THỰC TẾ
## CLOUD RESOURCE GUARDIAN — REAL AWS DETECTION EXPERIMENT

---

## 1. Mục tiêu và phạm vi thực nghiệm

Thực nghiệm được thiết kế nhằm kiểm chứng khả năng giám sát, phát hiện và đưa ra bằng chứng thực tế của hệ thống **Cloud Resource Guardian** đối với các tài nguyên AWS bị lãng phí hoặc cấu hình chưa tối ưu có chủ đích.

### Mục đích sử dụng:
1. **Phần thực nghiệm Chương 3:** Đưa số liệu đo lường, ảnh chụp bằng chứng AWS CloudWatch/Inventory và bảng đối chiếu vào báo cáo kỹ thuật/luận văn tốt nghiệp.
2. **Kịch bản quay video demo (7–9 phút):** Minh họa trực tiếp luồng quét thật, phát hiện thật, hiển thị bằng chứng và các thao tác tương tác (Keep/Ignore).
3. **Đánh giá định lượng:**
   - True Positive (TP): Phát hiện đúng tài nguyên lãng phí.
   - False Positive (FP): Hệ thống không báo nhầm tài nguyên đang hoạt động hoặc đã được miễn trừ.
   - True Negative (TN): Bỏ qua chính xác tài nguyên hợp lệ.
   - False Negative (FN): Không bỏ sót tài nguyên trong phạm vi quét.
   - Insufficient Data: Xác nhận hệ thống biết khi nào **không đủ dữ liệu** để kết luận thay vì giả định số liệu bằng 0.

### Phạm vi môi trường:
- **AWS Account:** `376129867108` (Môi trường AWS thật, hoàn toàn không dùng mock trong thực nghiệm).
- **Region ưu tiên:** `ap-southeast-1` (Singapore) — Khu vực triển khai chính của Stack Cloud Resource Guardian.
- **IAM Role kết nối:** `GuardianReadRole` (Được cấp quyền chỉ đọc nghiêm ngặt `SecurityAudit`, `ReadOnlyAccess` qua CloudFormation stack `guardian-read-role-demo`).
- **Giao diện quản trị:** https://d3qn9wabid8ws0.cloudfront.net/

---

## 2. Bảng dự toán chi phí và hạn ngạch (Quotas)

Nhằm tuân thủ nguyên tắc FinOps, toàn bộ tài nguyên thử nghiệm đều được chọn ở mức cấu hình nhỏ nhất (minimal footprint), có thể khởi tạo và xóa sạch trong vòng 1–2 phút.

### 2.1. Bảng chi phí chi tiết

| Test Case | Dịch vụ AWS | Loại & Cấu hình tài nguyên | Đơn giá AWS (ap-southeast-1) | Chi phí 24h | Chi phí 48h | Ghi chú FinOps |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **TC01** | Amazon EBS | 1x Volume gp3 (1 GiB, unattached) | $0.088 / GB-tháng | **$0.0029** | **$0.0058** | Kích thước tối thiểu cho phép của EBS gp3 |
| **TC02** | Amazon VPC | 1x Elastic IP (unassociated) | $0.005 / địa chỉ / giờ | **$0.1200** | **$0.2400** | Phí giữ public IPv4 không gắn vào instance |
| **TC03** | Amazon EC2 | 1x Security Group (chưa gắn ENI) | Miễn phí ($0.00) | **$0.0000** | **$0.0000** | Không phát sinh chi phí |
| **TC04** | Amazon ECR | 1x Private Repository (0 images) | Miễn phí lưu trữ repo | **$0.0000** | **$0.0000** | Không push image lớn, chỉ tạo repository |
| **TC05** | AWS Lambda | 1x Function Python 3.12 (128 MB, 0 inv) | Miễn phí (thuộc Free Tier) | **$0.0000** | **$0.0000** | 0 lượt gọi, kích thước code < 1 KB |
| **TC06** | IAM / Tags | 1x SG có tag `guardian:keep = true` | Miễn phí ($0.00) | **$0.0000** | **$0.0000** | Kiểm chứng bộ lọc triệt tiêu báo động giả |
| **TC07** | Amazon EC2 | 1x t4g.nano instance (chạy 15–30p) | $0.0054 / giờ | **$0.0030** | **$0.0030** | Dùng kiểm tra ngưỡng cửa sổ metrics |
| **TC08** | Scanning API | API Call / CloudWatch Metrics Read | Miễn phí trong hạn mức GetMetricData | **$0.0000** | **$0.0000** | Dưới 1 triệu metric requests/tháng |
| **TỔNG CỘNG** | | | **~$0.0105 / giờ** | **~$0.126 USD** (~3,300 VNĐ) | **~$0.249 USD** (~6,500 VNĐ) | **Chi phí toàn bộ thí nghiệm < 10,000 VNĐ** |

### 2.2. Kiểm tra Service Quotas

- **Elastic IP:** Hạn ngạch mặc định 5 EIPs / region. Thử nghiệm dùng 1 EIP (chiếm 20% quota).
- **EBS Volume:** Hạn ngạch 300 TB gp3 / region. Thử nghiệm dùng 1 GiB (chiếm 0.0003% quota).
- **Security Group:** Hạn ngạch 2,500 SGs / VPC. Thử nghiệm dùng 2 SGs (chiếm 0.08% quota).
- **Lambda:** Hạn ngạch 10,000 hàm. Thử nghiệm dùng 1 hàm.
- **ECR:** Hạn ngạch 10,000 repositories. Thử nghiệm dùng 1 repo.

---

## 3. Thiết kế chi tiết 8 Test Cases

```
                                      [Thực nghiệm AWS Thật]
                                                │
         ┌──────────────────────────────────────┼──────────────────────────────────────┐
         ▼                                      ▼                                      ▼
   [Tài nguyên Lãng phí]               [Cơ chế Quan sát & Bằng chứng]        [Kiểm soát Báo nhầm & Lỗi]
   • TC01: EBS Unattached              • TC01-03: OBSERVING vs REVIEW        • TC06: FP Control (guardian:keep)
   • TC02: EIP Unassociated            • TC04: ECR_NO_LIFECYCLE              • TC07: INSUFFICIENT_DATA
   • TC03: SG Unused                   • TC05: LAMBDA_UNUSED                 • TC08: PARTIAL Scan Handling
```

### TC01 — EBS_UNATTACHED (EBS Volume chưa gắn)
- **Tài nguyên:** 1x EBS Volume gp3 dung lượng 1 GiB ở trạng thái `available` (chưa gắn vào EC2).
- **Nguyên lý phát hiện:** `evaluate_ebs` đọc danh sách volume từ EC2 API. Nếu `volume["State"] == "available"` và không có `Attachments`:
  - Lần quét 1 (mới tạo): `observed_hours < orphan_hours` (mặc định 24h) $\rightarrow$ Trạng thái `OBSERVING`. Hệ thống bắt đầu theo dõi thời gian và không vội vàng kết luận.
  - Sau khi quan sát liên tục đủ 24 giờ: $\rightarrow$ Chuyển sang `REVIEW` kèm bằng chứng `size_gib = 1`, `observed_hours >= 24`.

### TC02 — EIP_UNASSOCIATED (Elastic IP không liên kết)
- **Tài nguyên:** 1x Elastic IP được allocate nhưng không gán `AssociationId` vào ENI hoặc EC2.
- **Nguyên lý phát hiện:** `evaluate_eip` kiểm tra `AssociationId`.
  - Nếu thiếu association: Trạng thái ban đầu `OBSERVING`.
  - Sau `orphan_hours`: Chuyển sang `REVIEW`.
  - **Bằng chứng (Evidence):** Cung cấp `AllocationId`, `PublicIp`, `domain = "vpc"` và `observed_hours`. Không suy đoán tùy tiện chi phí khi không có hóa đơn CUR.

### TC03 — SECURITY_GROUP_UNUSED (Security Group không sử dụng)
- **Tài nguyên:** 1x Security Group `crg-demo-sg-unused`, không gắn vào bất kỳ card mạng (ENI) nào và không có Security Group nào khác tham chiếu đến nó trong ingress/egress rules.
- **Nguyên lý phát hiện:** `collectors.py` duyệt toàn bộ ENIs từ `DescribeNetworkInterfaces` và các rules tham chiếu chéo.
  - SG `default` của VPC: Được loại trừ tự động theo thiết kế (không bao giờ báo nhầm SG mặc định).
  - SG demo: Trạng thái ban đầu `OBSERVING`. Sau khi theo dõi đủ `sg_unused_days` (mặc định 7 ngày = 168h) $\rightarrow$ Trạng thái `REVIEW`.

### TC04 — ECR_NO_LIFECYCLE (Kho ảnh ECR thiếu chính sách vòng đời)
- **Tài nguyên:** 1x Private ECR Repository `crg-demo-ecr-no-lifecycle` không tạo Lifecycle Policy.
- **Nguyên lý phát hiện:** `evaluate_ecr_repository` kiểm tra qua `get_lifecycle_policy`.
  - Do chưa có policy: Phát hiện ngay tại lần quét đầu tiên với trạng thái `REVIEW`.
  - **Quy tắc phân biệt:** Do repo chưa có image cũ, hệ thống **chỉ phát hiện** `ECR_NO_LIFECYCLE`, tuyệt đối **không phát sinh** `ECR_IMAGE_OLD` (chứng minh tính chính xác của bộ phân loại).

### TC05 — LAMBDA_UNUSED (Hàm Lambda không hoạt động)
- **Tài nguyên:** 1x Hàm Lambda tối giản Python 3.12 (128 MB), không cấu hình trigger và 0 lượt gọi (invocations = 0).
- **Nguyên lý phát hiện:** `collectors.py` truy vấn CloudWatch metric `Invocations` trong cửa sổ `window_hours` (24h).
  - Vì tổng số invocations $\le$ `lambda_max_invocations` (mặc định 0):
  - Phát sinh cảnh báo `LAMBDA_UNUSED` với lý do rõ ràng: *"Unused Lambda function with 0 invocations and no event source mappings"*.
  - Bằng chứng hiển thị: `runtime = python3.12`, `code_size_bytes`, `invocations = 0`, `event_source_mappings = 0`.

### TC06 — FALSE POSITIVE CONTROL (Kiểm soát Báo động giả)
- **Tài nguyên:** 
  1. Security Group có tag `guardian:keep = true` (`crg-demo-sg-keep-control`).
  2. Security Group mặc định của VPC (`default`).
- **Kỳ vọng:** Cả hai tài nguyên dù không gắn ENI nhưng **không bao giờ xuất hiện** trong danh sách cảnh báo `REVIEW` hay `OBSERVING`.
  - Chứng minh cơ chế ngoại lệ chủ động (`guardian:keep`) và logic nhận diện tài nguyên hệ thống mặc định hoạt động chính xác (True Negative).

### TC07 — INSUFFICIENT_DATA (Tài nguyên thiếu dữ liệu quan sát)
- **Tài nguyên:** Tài nguyên mới tạo có `LaunchTime` nhỏ hơn cửa sổ metrics (`LaunchTime > start`), hoặc tài nguyên CloudWatch không trả đủ 80% số mẫu cần thiết (`coverage < 0.8`).
- **Nguyên lý phát hiện:** Hệ thống phân loại thành `INSUFFICIENT_DATA` với lý do: *"Instance younger than observation window"* hoặc *"Missing CloudWatch metrics; not classified as idle"*.
- **Ý nghĩa:** Chứng minh hệ thống không bao giờ tự ý gán `missing metrics = 0` để kết luận bừa bãi là idle.

### TC08 — PARTIAL SCAN HANDLING (Xử lý quét từng phần khi có lỗi dịch vụ)
- **Tình huống:** Thử nghiệm quét khi một dịch vụ AWS gặp lỗi tạm thời (ví dụ: giới hạn quyền hoặc timeout).
- **Kỳ vọng:**
  - Lượt quét hiển thị trạng thái `PARTIAL` (màu vàng cam).
  - Ghi nhận đầy đủ mã lỗi (ví dụ: `AccessDenied`, `TIME_BUDGET`) kèm loại dịch vụ bị ảnh hưởng.
  - **Các findings thu thập thành công từ những dịch vụ khác trong cùng region không bị mất hay bị hủy bỏ.**

---

## 4. Ma trận đánh giá kết quả (Evaluation Matrix)

| Kết quả đánh giá | Định nghĩa trong Cloud Resource Guardian | Ví dụ thực tế |
| :--- | :--- | :--- |
| **True Positive (TP)** | Phát hiện chính xác tài nguyên thực sự lãng phí kèm bằng chứng đầy đủ. | TC01 (EBS unattached), TC02 (EIP unassociated), TC04 (ECR no lifecycle), TC05 (Lambda 0 inv). |
| **False Positive (FP)** | Báo nhầm tài nguyên đang sử dụng hoặc tài nguyên đã có chủ đích giữ lại. | Đạt 0 lỗi nếu TC06 và các SG active không bị báo động. |
| **True Negative (TN)** | Bỏ qua chính xác tài nguyên hợp lệ hoặc đã được gắn nhãn miễn trừ `guardian:keep`. | SG `default` và SG gắn tag `guardian:keep: true` không bị cảnh báo. |
| **False Negative (FN)** | Bỏ sót tài nguyên lãng phí nằm trong phạm vi và nhóm dịch vụ được quét. | Đạt 0 lỗi nếu toàn bộ tài nguyên theo manifest đều được inventory ghi nhận. |
| **Insufficient Evidence** | Tài nguyên chưa đủ thời gian hoặc thiếu CloudWatch metrics để kết luận. | Phân loại đúng vào `OBSERVING` hoặc `INSUFFICIENT_DATA`. |

---

## 5. Quy trình thực hiện & Tiêu chí nghiệm thu

1. **Giai đoạn chuẩn bị (Hiện tại):**
   - Đã tạo template CloudFormation `tests/demo_aws/demo_resources.yaml`.
   - Đã tạo script tự động `tests/demo_aws/manage_experiment.py`.
   - Đã hoàn tất tài liệu kế hoạch và bảng chi phí.
2. **Giai đoạn phê duyệt (Gate):**
   - Xin phê duyệt từ Quản trị viên đối với danh sách tài nguyên và mức chi phí ~$0.133 USD.
3. **Giai đoạn triển khai (Sau phê duyệt):**
   - Chạy `python tests/demo_aws/manage_experiment.py apply`.
   - Lưu trữ `manifest.json`.
4. **Giai đoạn kiểm thử & Thu thập bằng chứng:**
   - Kích hoạt **Quét ngay** trên giao diện https://d3qn9wabid8ws0.cloudfront.net/.
   - Lấy `ScanId`, chụp ảnh bằng chứng (Evidence modal) trên trình duyệt.
   - Thử nghiệm chức năng phản hồi: Bấm **Giữ lại** (Keep) và **Bỏ qua** (Ignore) để ghi nhận luồng xử lý thực tế.
5. **Giai đoạn dọn dẹp (Teardown):**
   - Chạy `python tests/demo_aws/manage_experiment.py destroy`.
   - Xác nhận AWS CloudFormation stack đã xóa sạch, không để lại tài nguyên tồn dư.
