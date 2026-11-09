# NHẬT KÝ QUÁ TRÌNH PHÁT TRIỂN DỰ ÁN
## CLOUD RESOURCE GUARDIAN — PROJECT WORK LOG & TEAM COLLABORATION

---

## 1. Tổng quan Dự án & Nhân sự Thực hiện

Căn cứ trên dữ liệu lịch sử commit, tác giả pull request và định danh người dùng thực tế từ GitHub Repository (https://github.com/hoangdat2407/ResourceGuardian.git), dự án được xây dựng và phối hợp bởi các thành viên:

| Họ và tên | GitHub Username | Email định danh | Vai trò & Trách nhiệm chính trên mã nguồn |
| :--- | :--- | :--- | :--- |
| **Hoàng Đạt** | `hoangdat2407` / `datjava` | `hoangdat2407@gmail.com`<br>`23021518@vnu.edu.vn` | **Trưởng nhóm & Kiến trúc sư Đám mây (AWS Architect / Lead):**<br>- Thiết kế kiến trúc tổng thể, hạ tầng CloudFormation (`template.yaml`).<br>- Triển khai xác thực Amazon Cognito, PKCE S256 và luồng tự đăng ký.<br>- Bộ quét chỉ đọc (Scanners), điều phối API Gateway, S3/CloudFront deployment (`deploy.py`, `publish.py`).<br>- Thiết kế và thực thi thí nghiệm tài nguyên thật trên AWS Singapore. |
| **Phạm Đức** | `ducp8822` | `ducp8822@gmail.com` | **Kỹ sư Backend & Động cơ Quy tắc (Rules Engine & Frontend UI):**<br>- Phát triển động cơ quy tắc phát hiện thuần (`src/rules.py`) cho các nhóm tài nguyên.<br>- Xây dựng cơ chế theo dõi thời gian quan sát (`first_seen_at`, `last_seen_at`, `observed_hours`).<br>- Thiết kế các luồng giao diện: Bộ lọc phạm vi quét, chi tiết bằng chứng (Evidence Modal), quản lý phản hồi (Keep/Ignore) và phân trang lịch sử quét (History).<br>- Lập trình các bài kiểm thử đơn vị và kiểm thử tích hợp giao diện. |
| **Nguyễn Trung Hải** | `easterlywind` / `trunghai` | `haitrung101@gmail.com` | **Kỹ sư Vận hành & Tích hợp (Operations & Notifications Engineer):**<br>- Phát triển hệ thống thông báo email qua Amazon SES (`src/app.py:notify`).<br>- Xây dựng cơ chế claim token nguyên tử chống gửi trùng email và cooldown theo lịch quét.<br>- Thiết lập hàng đợi sự cố SQS Dead Letter Queue (DLQ), chính sách redrive và hàm khôi phục `RecoveryFunction`. |

---

## 2. Phương thức Phối hợp Nhóm (Team Collaboration Methods)

> *Ghi chú phương pháp luận:* Nhóm không tự tạo biên bản họp giả lập. Toàn bộ thông tin phối hợp dưới đây được trích xuất trực tiếp từ các bằng chứng kỹ thuật có thật trên GitHub: lịch sử nhánh, mô tả Pull Request, commit checkpoints và mã nguồn kiểm thử.

1. **Mô hình Quản lý Nhánh (Branching Strategy):**
   - Nhóm áp dụng mô hình Feature Branching kết hợp Gitflow:
     - Nhánh `main`: Nhánh ổn định, phản ánh trạng thái đã kiểm thử và sẵn sàng xuất bản lên AWS Cloud.
     - Các nhánh tính năng độc lập theo từng thành viên: `datht` (Hoàng Đạt), `duc` (Phạm Đức), `codex/hai-tasks-10-12` (Nguyễn Trung Hải), `codex/task-7-finding-observations`, `codex/task-8-scheduling-recovery`.
2. **Quy trình Tích hợp và Đánh giá Mã nguồn (Code Review & Pull Requests):**
   - Mọi tính năng lớn đều được bàn giao qua Pull Request có mô tả phạm vi kỹ thuật (scope), bảng nghiệm thu, liệt kê các ca kiểm thử đạt được và các điều kiện rào cản (blockers).
   - Tổng cộng **6 Pull Requests** lớn được mở, giải quyết xung đột (conflict resolution trên `template.yaml`) và merge an toàn vào nhánh `main`.
3. **Phân định Ranh giới Kỹ thuật (Decoupled Interfaces & File Ownership):**
   - Tránh xung đột mã nguồn bằng cách phân tách rõ ràng trách nhiệm:
     - Thuật toán phát hiện được cô lập trong `src/rules.py` (hàm thuần túy, không phụ thuộc I/O).
     - Tương tác AWS SDK được đóng gói trong `src/collectors.py`.
     - Điều phối serverless, database và bảo mật tập trung tại `src/app.py`.
     - Giao diện web được quản lý độc lập tại thư mục `web/`.
4. **Bàn giao Dựa trên Kiểm thử Tự động (Test-Driven Handoff):**
   - Trước khi tích hợp PR, mỗi thành viên cung cấp bằng chứng kiểm thử tự động (Unit tests, Playwright UI tests, CloudFormation linter) để đảm bảo không hồi quy (zero regression) chức năng của nhau.

---

## 3. Nhật ký Công việc Chi tiết theo Thứ tự Thời gian (Chronological Work Log)

### Giai đoạn 1: Khởi tạo Kiến trúc MVP & Bộ quét Chỉ đọc (13/10/2026 – 19/10/2026)

- **Ngày 13/10/2026**
  - **Công việc:** Khởi tạo kiến trúc nền tảng Cloud Resource Guardian MVP, thiết lập template CloudFormation ban đầu, cấu hình HTTP API Gateway và bảng DynamoDB.
  - **Kết quả:** Xây dựng khung kiến trúc serverless ban đầu, định nghĩa cấu trúc dữ liệu `TENANT#` và quyền hạn chỉ đọc.
  - **Người thực hiện:** Hoàng Đạt (`datjava`)
  - **Bằng chứng:** Commit `d6cded4` (*feat: initial Cloud Resource Guardian MVP*).

- **Ngày 16/10/2026**
  - **Công việc:** Xây dựng bộ thu thập tài nguyên AWS chỉ đọc (Read-only scanners) cho EC2, EBS, EIP và thiết lập khung API phản hồi.
  - **Kết quả:** Triển khai các collector đầu tiên trên `collectors.py` và các route API `/connection`, `/me`, `/findings`.
  - **Người thực hiện:** Hoàng Đạt (`hoangdat2407`)
  - **Bằng chứng:** Commit `ef35d90` (*feat: add read-only AWS scanners and feedback API*).

- **Ngày 18/10/2026**
  - **Công việc:** Hoàn thiện bộ quy tắc phát hiện giai đoạn 1 (Phase 1 resource rules) và xây dựng API xử lý giữ lại tài nguyên (`/keep`).
  - **Kết quả:** Bổ sung logic đánh giá ổ đĩa EBS chưa gắn (`EBS_UNATTACHED`), Elastic IP chưa liên kết (`EIP_UNASSOCIATED`) và cơ chế miễn trừ qua thẻ `guardian:keep`.
  - **Người thực hiện:** Phạm Đức (`ducp8822`) & Hoàng Đạt (`hoangdat2407`)
  - **Bằng chứng:**
    - Commit `570f430` (*feat: complete phase one resource rules and keep API*)
    - Pull Request **#1** (*feat: add read-only AWS scanners and feedback API*) merged bởi `hoangdat2407`.
    - Pull Request **#2** (*feat: complete phase one resource rules and keep API*) merged bởi `hoangdat2407`.

- **Ngày 19/10/2026**
  - **Công việc:** Sửa lỗi gọi API mạng, loại bỏ tham số `MaxResults` không tương thích trong `DescribeAddresses` và kiểm chứng quét tài nguyên mạng.
  - **Kết quả:** Bộ quét mạng hoạt động ổn định trên AWS SDK mà không bị lỗi cú pháp tham số.
  - **Người thực hiện:** Hoàng Đạt (`hoangdat2407`)
  - **Bằng chứng:** Commit `debea62` (*fix(collectors): remove MaxResults from DescribeAddresses and verify network scan*).

---

### Giai đoạn 2: Chuẩn hóa 9 Loại Tài nguyên, Điều phối Lỗi & Thông báo SES (26/10/2026 – 27/10/2026)

- **Ngày 26/10/2026**
  - **Công việc:** 
    - Hoàn thiện bộ quy tắc và cấu trúc bằng chứng (Evidence Schema) nhất quán cho 9 loại tài nguyên cốt lõi (EC2, EBS, EIP, Snapshot, S3 Multipart, RDS, NAT Gateway, ALB, NLB).
    - Củng cố luật tính toán metrics cho RDS, NAT Gateway và Load Balancers; chặn việc kết luận bừa bãi khi CloudWatch thiếu mẫu.
  - **Kết quả:** 100% các evaluator được chuyển thành hàm thuần túy (pure functions); bổ sung đầy đủ trường `observation_start`, `observation_end`, `coverage` trong evidence.
  - **Người thực hiện:** Phạm Đức (`ducp8822`)
  - **Bằng chứng:**
    - Commit `67441ee`, `d9a3b26`, `767f32a`.
    - Pull Request **#3** (*feat: complete Task 7 rules and evidence for nine resource types*) merged ngày 26/10/2026.

- **Ngày 27/10/2026**
  - **Công việc:**
    - Triển khai lập lịch quét tự động qua EventBridge Rule và cơ chế phục hồi sự cố Worker Timeout (Task 8).
    - Triển khai hệ thống cảnh báo qua email Amazon SES (Task 10–12): Atomic conditional claim chống gửi trùng lặp, cơ chế cooldown theo lịch quét, tích hợp SQS Dead Letter Queue và hàm `RecoveryFunction`.
    - Giải quyết xung đột mã nguồn trên `template.yaml`.
  - **Kết quả:**
    - Hoàn thiện điều phối vòng đời quét: Khóa `lease_until` trong DynamoDB tự giải phóng sau 15 phút 30 giây nếu worker bị treo.
    - Bản tin lỗi được chuyển hướng vào `DeadLetters` SQS queue, xử lý lại tối đa 5 lần trước khi đưa sang `OperationsDeadLetters`.
  - **Người thực hiện:** Phạm Đức (`ducp8822`), Nguyễn Trung Hải (`easterlywind`), Hoàng Đạt (`datjava`)
  - **Bằng chứng:**
    - Commit `81d083d`, `a8034f9` (Phạm Đức).
    - Commit `3288353` (Nguyễn Trung Hải).
    - Pull Request **#4** (*feat: complete Task 8 scheduling and failure recovery*) merged ngày 27/10/2026.
    - Pull Request **#5** (*feat: Hải tasks 10–12 — SES notifications, integration verification, operations*) merged ngày 27/10/2026.
    - Commit `543a293` (*merge: resolve template.yaml conflict and integrate main into duc*).

---

### Giai đoạn 3: Trực quan hóa Dashboard, Quản lý Phản hồi & Lịch sử Quét (30/10/2026 – 01/11/2026)

- **Ngày 30/10/2026**
  - **Công việc:**
    - Bổ sung cơ chế lưu trữ mốc thời gian quan sát (`first_seen_at`, `last_seen_at`) vào bảng DynamoDB.
    - Xây dựng giao diện bộ lọc phạm vi quét trên web (tìm kiếm, lọc theo dịch vụ, region, mức cảnh báo, trạng thái xem).
    - Phát triển modal xem chi tiết bằng chứng (`#finding-dialog`) và các nút điều khiển phản hồi: **Giữ lại (Keep)** và **Bỏ qua (Ignore 1–30 ngày)**.
    - Xây dựng bảng quản lý phản hồi độc lập (`#feedback-management`) hỗ trợ phân trang và hủy bỏ cờ giữ lại/bỏ qua.
  - **Kết quả:** Kỹ sư có thể tương tác trực tiếp với cảnh báo, ẩn các tài nguyên đã xác nhận mà không làm thay đổi tài nguyên AWS thật.
  - **Người thực hiện:** Phạm Đức (`ducp8822`)
  - **Bằng chứng:** Commit `8e140bb`, `d9313dd`, `40ceeb3`, `8770678`, `1d3a026`, `6f09a85`, `576b382`, `03cd770`, `da0922e`.

- **Ngày 31/10/2026**
  - **Công việc:**
    - Xây dựng tính năng phân trang lịch sử quét (`GET /history`) theo con trỏ cursor (20 bản ghi/trang).
    - Sửa lỗi giữ lại dữ liệu toàn bộ các region trong chi tiết lịch sử (`/scans/{scanId}`).
    - Đồng bộ bộ dữ liệu mẫu demo 9 tài nguyên phục vụ chạy thử nghiệm không cần kết nối cloud (`demo.py`).
  - **Kết quả:** Hoàn thiện luồng tra cứu lịch sử quét đa vùng, lưu trữ snapshot bất biến trong 30 ngày.
  - **Người thực hiện:** Phạm Đức (`ducp8822`)
  - **Bằng chứng:** Commit `4cfc103`, `2b6de95`, `5cbf387`, `1d3d7c2`, `3342085`.

- **Ngày 01/11/2026**
  - **Công việc:** Củng cố tài liệu triển khai, tích hợp toàn bộ kiểm thử hồi quy, thêm ảnh xem trước giao diện desktop và mobile. Merge gói tính năng Task 7–9 vào nhánh chính.
  - **Kết quả:** Nhánh `main` đạt trạng thái ổn định toàn diện cho phiên bản nền tảng 9 tài nguyên.
  - **Người thực hiện:** Phạm Đức (`ducp8822`) & Hoàng Đạt (`hoangdat2407`)
  - **Bằng chứng:**
    - Commit `1ada5d9`, `268b97e`, `5209cd4`, `aaa541f`.
    - Pull Request **#6** (*feat: persist finding observations and complete dashboard feedback/history flows*) merged ngày 01/11/2026 bởi `hoangdat2407`.

---

### Giai đoạn 4: Mở rộng 38 Dịch vụ, Tự Đăng ký Cognito, Tối giản Giao diện & Nghiệm thu AWS Thật (06/11/2026 – 08/11/2026)

- **Ngày 06/11/2026 – 07/11/2026**
  - **Công việc:**
    - Mở rộng phạm vi bao phủ lên **38 loại tài nguyên thu thập, 39 quy tắc phát hiện và 40 trường ngưỡng cấu hình** (bổ sung Container, Serverless, NoSQL, Analytics, Integration).
    - Triển khai chức năng **Tự đăng ký tài khoản (Cognito Self-Sign-Up)** trực tiếp trên giao diện: Form đăng ký, xác minh OTP email, gửi lại mã, quên và đặt lại mật khẩu; kiểm tra 5 tiêu chuẩn mật khẩu Cognito.
    - Tái thiết kế toàn bộ giao diện theo phong cách tối giản: Xóa bỏ 100% slogan quảng cáo, xóa 100% emoji khỏi DOM, ẩn Rule ID trên UI, thiết kế Accordion 6 nhóm dịch vụ dạng 1 cột dọc (tối đa 2 input/hàng trên desktop, 1 input trên mobile).
    - Tạo và execute CloudFormation Change Set `guardian-1793977048349973777` trên stack production `cloud-resource-guardian` (`AllowAdminCreateUserOnly: false`, `replacement=False`).
    - Xuất bản frontend mới lên S3 WebBucket và CloudFront (`https://d3qn9wabid8ws0.cloudfront.net/`).
  - **Kết quả:** Triển khai thành công tính năng đăng ký thật trên live Cognito; frontend tối giản vận hành trên production; toàn bộ 398 bài unit test và UI tests đạt 100%.
  - **Người thực hiện:** Hoàng Đạt (`hoangdat2407`)
  - **Bằng chứng:** Commit `6bff2dd` (*feat: add cognito self-sign-up, minimalist UI, and real AWS detection experiment*).

- **Ngày 07/11/2026**
  - **Công việc:**
    - Xây dựng bộ công cụ quản lý vòng đời tài nguyên thử nghiệm thực tế (`tests/demo_aws/demo_resources.yaml` và `manage_experiment.py`).
    - Triển khai stack thử nghiệm `crg-demo-experiment-stack` trên AWS Singapore gồm 6 tài nguyên thật (EBS 1 GiB unattached, EIP unassociated, SG unused, SG có thẻ `guardian:keep`, ECR không lifecycle, Lambda 0 lượt gọi).
    - Kích hoạt lượt quét thật **ScanId `34eb7157-dbec-454a-b796-452fc9c71d97`** qua quyền `GuardianReadRole-demo`.
    - Chụp 8 ảnh bằng chứng giao diện kết xuất số liệu thực nghiệm (`docs/screenshots/`).
  - **Kết quả:**
    - Phát hiện chuẩn xác 100% các tài nguyên thử nghiệm: EBS và EIP mới tạo xếp vào `OBSERVING`, ECR xếp `REVIEW`, Lambda xếp `REVIEW`.
    - Triệt tiêu hoàn toàn báo động giả (True Negative) đối với SG có thẻ `guardian:keep` và SG `default`.
    - Phân loại đúng ALB thiếu số liệu sang `INSUFFICIENT_DATA`.
    - Ghi nhận trạng thái `PARTIAL` khi 2 dịch vụ FSX/MemoryDB chưa subscribe mà không làm mất findings.
  - **Người thực hiện:** Hoàng Đạt (`hoangdat2407`)
  - **Bằng chứng:** Tệp `tests/demo_aws/manifest.json`, ScanId `34eb7157...` lưu trên DynamoDB.

- **Ngày 08/11/2026**
  - **Công việc:**
    - Thực thi bài kiểm thử hiệu năng k6 chuẩn công nghiệp (`tests/performance/k6_readonly.js`) nhắm vào CloudFront CDN.
    - Lập trình bộ kiểm thử độ bền bỉ và an ninh IAM (`tests/resilience/test_resilience_and_security.py`).
    - Hoàn tất bộ hồ sơ thẩm định bằng chứng, kiểm tra NFR và kịch bản video demo 10 phút.
  - **Kết quả:**
    - Đo lường k6 đạt 156 requests không lỗi, P50 = 975ms.
    - Xác định rõ tính chất bằng chứng ảnh chụp là `MIXED` (giao diện tĩnh tải thật từ CloudFront, dữ liệu nạp qua route interception từ kết quả quét AWS thật).
    - Xuất bản đầy đủ các tài liệu nghiệm thu cuối cùng.
  - **Người thực hiện:** Hoàng Đạt (`hoangdat2407`)
  - **Bằng chứng:** Bộ tài liệu `docs/FINAL_*.md` và kết quả log kiểm thử tự động.

---

## 4. Bảng Tổng hợp Đóng góp Theo Phân công GitHub

| Thành viên | Số Commits trực tiếp | Pull Requests tạo / liên quan | Các Tệp / Module Chịu trách nhiệm chính |
| :--- | :---: | :---: | :--- |
| **Hoàng Đạt** (`hoangdat2407`) | 7 commits | PR #1 (Author), PR #2 (Merge), PR #3 (Merge), PR #4 (Merge), PR #5 (Merge), PR #6 (Merge) | `template.yaml`, `src/app.py`, `web/app.js`, `web/index.html`, `web/styles.css`, `deploy.py`, `publish.py`, `tests/demo_aws/`, `tests/performance/`, `tests/resilience/` |
| **Phạm Đức** (`ducp8822`) | 23 commits | PR #2 (Author), PR #3 (Author), PR #4 (Author), PR #6 (Author) | `src/rules.py`, `src/collectors.py`, `web/app.js` (Feedback/History flows), `demo.py`, `tests/test_rules.py`, `tests/ui_finding_details.py`, `tests/ui_history_management.py` |
| **Nguyễn Trung Hải** (`easterlywind`) | 1 commit | PR #5 (Author) | `src/app.py:notify` (SES notifications), `template.yaml:DeadLetters/OperationsDeadLetters`, `tests/test_notifications.py` |

---

## 5. Thống kê Lịch sử Triển khai Hạ tầng AWS (CloudFormation Deployments)

Các đợt triển khai trên tài khoản AWS `376129867108` tại Region Singapore (`ap-southeast-1`):

1. **Stack `cloud-resource-guardian` (Stack chính hệ thống):**
   - *Khởi tạo ban đầu:* Tháng 10/2026 qua AWS SAM (`StackId: arn:aws:cloudformation:ap-southeast-1:376129867108:stack/cloud-resource-guardian/81f52de0-c53a-11f1-8a39-02ffd9f7b9e9`).
   - *Cập nhật Change Set:* `guardian-1793977048349973777` (thực thi ngày 07/11/2026), bật tính năng `AllowAdminCreateUserOnly: false` trên Cognito User Pool `ap-southeast-1_NwY3bQKBQ`, cập nhật Lambda package mới.
2. **Stack `guardian-read-role-demo` (Stack cấp quyền chỉ đọc):**
   - *Khởi tạo:* Tháng 10/2026 (`StackId: arn:aws:cloudformation:ap-southeast-1:376129867108:stack/guardian-read-role-demo/4b1fba80-c542-11f1-a054-0affe454644b`).
   - *Quyền hạn:* Cấp role `GuardianReadRole-demo` tin cậy `ApiRole` và `ScanRole` kèm điều kiện ExternalId cố định.
3. **Stack `crg-demo-experiment-stack` (Stack tài nguyên thử nghiệm):**
   - *Khởi tạo:* Ngày 07/11/2026 lúc 13:55:36 UTC (`StackId: arn:aws:cloudformation:ap-southeast-1:376129867108:stack/crg-demo-experiment-stack/d3436800-dab2-11f1-b6e2-0afff8ca2f29`).
   - *Tài nguyên tạo:* 1 EBS 1 GiB, 1 Elastic IP, 2 Security Groups, 1 ECR Repository, 1 Lambda Function. Quản lý dọn dẹp tập trung qua `tests/demo_aws/manifest.json`.
