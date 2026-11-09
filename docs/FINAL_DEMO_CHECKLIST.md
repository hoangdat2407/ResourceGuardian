# KỊCH BẢN & CHECKLIST QUAY VIDEO DEMO BẢO VỆ (10 PHÚT)
## CLOUD RESOURCE GUARDIAN — 10-MINUTE DEMO REHEARSAL CHECKLIST

---

## 1. Checklist Chuẩn bị Trước khi Bấm Quay (Pre-Recording Checklist)

- [ ] **Trình duyệt & Môi trường:**
  - Mở sẵn tab 1: Production Website https://d3qn9wabid8ws0.cloudfront.net/ (đã đăng xuất sạch, màn hình đăng nhập).
  - Mở sẵn tab 2: AWS Management Console tài khoản `376129867108`, Region Singapore (`ap-southeast-1`).
  - Mở sẵn tab 3: CloudWatch Logs Insights (`/aws/lambda/cloud-resource-guardian-WorkerFunction...`).
- [ ] **Tài nguyên Thử nghiệm:**
  - Xác nhận 6 tài nguyên trong `tests/demo_aws/manifest.json` đang ở trạng thái hoạt động:
    - `vol-0dd1bd1d0f63a7f87` (EBS 1 GiB gp3 `available`).
    - `eipalloc-094552008df2fbdc3` (`54.151.234.194`, `unassociated`).
    - `sg-08a66cd261539c3e4` (`crg-demo-sg-unused`).
    - `sg-092e7ea0b1bd40bd9` (`crg-demo-sg-keep-control`, có tag `guardian:keep: true`).
    - `crg-demo-ecr-no-lifecycle` (ECR repo rỗng).
    - `crg-demo-lambda-unused` (Lambda 0 invocations).
- [ ] **Màn hình & Âm thanh:**
  - Độ phân giải quay màn hình: 1920x1080 (Full HD) hoặc 1440x900.
  - Phóng to trình duyệt lên 110% hoặc 125% để chữ và số liệu hiển thị rõ ràng trên video.
  - Mic thu âm rõ ràng, không tạp âm.

---

## 2. Kịch bản Quay Chi tiết 10 Phút (Từng Phân cảnh)

### [00:00 – 01:00] PHÂN CẢNH 1: MỞ ĐẦU & GIỚI THIỆU HỆ THỐNG
- **Thời lượng:** 60 giây.
- **Màn hình hiển thị:** Trang chủ website https://d3qn9wabid8ws0.cloudfront.net/.
- **Thao tác:** Chuyển đổi giữa 3 tab điều hướng khách `Đăng nhập`, `Đăng ký`, `Quên mật khẩu`.
- **Lời thoại (Voiceover):**
  > *"Kính chào quý thầy cô trong hội đồng và các bạn. Trong quản trị đám mây AWS, bài toán tối ưu chi phí (FinOps) luôn đối mặt với vấn đề lãng phí từ các tài nguyên bị bỏ quên sau giai đoạn thử nghiệm: như ổ đĩa EBS tháo rời, địa chỉ IP tĩnh không gán, hay kho ảnh ECR thiếu chính sách vòng đời.*
  > 
  > *Dự án **Cloud Resource Guardian** được nhóm chúng em xây dựng như một công cụ FinOps chuyên nghiệp, vận hành hoàn toàn trên kiến trúc **Serverless 100% của AWS**.*
  > 
  > *Hệ thống hoạt động theo nguyên tắc an toàn cao nhất: **Chỉ đọc (Strictly Read-Only)**, **Đưa ra bằng chứng kỹ thuật minh bạch** và trao quyền quyết định xử lý cho kỹ sư phụ trách, tuyệt đối không tự ý can thiệp làm gián đoạn hệ thống của khách hàng."*
- **Evidence cần quay:** Giao diện tối giản, thanh điều hướng gọn gàng không slogan thừa.
- **Phương án dự phòng:** Nếu mạng chậm, mở tab dự phòng đã load sẵn.

---

### [01:00 – 02:00] PHÂN CẢNH 2: ĐĂNG NHẬP COGNITO & KẾT NỐI ROLE CHỈ ĐỌC
- **Thời lượng:** 60 giây.
- **Màn hình hiển thị:** Màn hình Đăng nhập và trang `Kết nối AWS`.
- **Thao tác:**
  - Đăng nhập vào ứng dụng qua giao diện Cognito.
  - Chuyển sang mục `Kết nối AWS`.
  - Hiển thị thông số kết nối: Role ARN `arn:aws:iam::376129867108:role/GuardianReadRole-demo` và ExternalId.
  - Bấm **Kiểm tra và lưu kết nối**. Badge chuyển sang màu xanh `Đã kết nối`.
- **Lời thoại (Voiceover):**
  > *"Để bắt đầu, em đăng nhập vào hệ thống. Phiên làm việc được quản trị bằng Amazon Cognito User Pool kết hợp luồng OAuth 2.0 PKCE S256, bảo đảm phân lập dữ liệu đa người thuê (Multi-tenant isolation).*
  > 
  > *Ở bước kết nối tài khoản AWS, khách hàng không cần chia sẻ Access Key hay Secret Key. Chúng em cung cấp sẵn CloudFormation template tạo một IAM Role chỉ đọc mang tên `GuardianReadRole`, có cơ chế kiểm tra `sts:ExternalId` duy nhất của tài khoản đăng nhập để triệt tiêu nguy cơ tấn công tráo quyền Confused Deputy.*
  > 
  > *Em chọn khu vực quét Singapore (`ap-southeast-1`) và lưu kết nối thành công."*
- **Evidence cần quay:** Thẻ xanh `Đã kết nối`, 3 giá trị Parameters trong khung bên cạnh.

---

### [02:00 – 03:00] PHÂN CẢNH 3: MINH CHỨNG TÀI NGUYÊN THẬT TRÊN AWS CONSOLE
- **Thời lượng:** 60 giây.
- **Màn hình hiển thị:** AWS Management Console (Tab 2), tài khoản `376129867108` tại Singapore.
- **Thao tác:**
  - Chuyển tab sang EC2 Console: Chỉ vào ổ đĩa EBS `vol-0dd1bd1d0f63a7f87` (trạng thái `available`).
  - Mở Elastic IP: Chỉ vào IP `54.151.234.194` (trống `AssociationId`).
  - Mở Security Groups: Chỉ vào `crg-demo-sg-unused` (0 ENI) và `crg-demo-sg-keep-control` (có tag `guardian:keep = true`).
  - Mở ECR Console: Chỉ vào repo `crg-demo-ecr-no-lifecycle` (không có Lifecycle Policy).
  - Mở Lambda Console: Hàm `crg-demo-lambda-unused` (0 invocations).
- **Lời thoại (Voiceover):**
  > *"Để chứng minh hệ thống đọc dữ liệu thật từ AWS, em xin mở trực tiếp AWS Management Console của tài khoản `376129867108`:*
  > - *Một ổ đĩa EBS gp3 dung lượng 1 GiB ở trạng thái `available`.*
  > - *Một địa chỉ IP tĩnh Elastic IP chưa gắn vào bất kỳ máy chủ nào.*
  > - *Một Security Group trống không đính kèm card mạng.*
  > - *Một kho ảnh container ECR hoàn toàn không có chính sách vòng đời.*
  > - *Và một hàm Lambda không hề phát sinh lệnh gọi nào.*
  > 
  > *Tất cả các tài nguyên này đã được gắn thẻ nhận diện dự án rõ ràng và sẵn sàng cho đợt rà soát."*
- **Evidence cần quay:** Trạng thái `available`, `No association`, tag `guardian:keep: true`.

---

### [03:00 – 04:00] PHÂN CẢNH 4: CẤU HÌNH NGƯỠNG & KÍCH HOẠT QUÉT NGAY
- **Thời lượng:** 60 giây.
- **Màn hình hiển thị:** Trang `Cấu hình` và Trang `Tổng quan`.
- **Thao tác:**
  - Mở trang `Cấu hình`: Click mở Accordion 6 nhóm dịch vụ, chỉ vào các trường ngưỡng tùy chỉnh. Bấm **Lưu thay đổi**.
  - Quay lại trang `Tổng quan`, bấm nút **Quét ngay** (`Scan Now`).
  - Thanh tiến độ polling 5s tự động cập nhật.
- **Lời thoại (Voiceover):**
  > *"Trước khi quét, kỹ sư có thể linh hoạt tùy chỉnh toàn bộ 40 ngưỡng phát hiện trong 6 nhóm dịch vụ tại trang Cấu hình. Thiết kế Accordion dọc tối giản 1 cột giúp tra cứu tiện lợi và ẩn hoàn toàn các mã kỹ thuật Rule ID gây rối mắt.*
  > 
  > *Bây giờ, em bấm nút **Quét ngay**. Phía sau hậu trường, Lambda API Function sẽ kích hoạt Worker Lambda qua cơ chế Event-driven bất đồng bộ. Worker sẽ dùng quyền của GuardianReadRole để duyệt qua 38 loại tài nguyên và tính toán số liệu metrics trong cửa sổ 24 giờ của CloudWatch.*
  > 
  > *Giao diện sẽ tự động cập nhật kết quả mà người dùng không cần bấm F5 tải lại trang."*
- **Evidence cần quay:** Nút `Quét ngay` chuyển sang trạng thái đang quét, thanh tiến độ polling 5s.

---

### [04:00 – 06:00] PHÂN CẢNH 5: BẰNG CHỨNG PHÁT HIỆN & THAO TÁC FINOPS (KEEP / IGNORE)
- **Thời lượng:** 120 giây (2 phút).
- **Màn hình hiển thị:** Trang `Tài nguyên cần kiểm tra` và Modal `#finding-dialog`.
- **Thao tác:**
  - **Điểm 1 (ECR No Lifecycle):** Mở finding `crg-demo-ecr-no-lifecycle`. Bấm **Xem chi tiết**. Mở bảng Evidence chỉ rõ `has_lifecycle_policy: false`. Đóng popup.
  - **Điểm 2 (Lambda Unused):** Mở finding `crg-demo-lambda-unused`. Chỉ rõ bằng chứng `invocations = 0`.
  - **Điểm 3 (EBS & EIP - Observing Window):** Lọc theo trạng thái `Đang quan sát` (`OBSERVING`). Giải thích tại sao volume `vol-0dd1bd1d0f63a7f87` chưa bị kết luận xóa ngay (vì mới tạo, cần đủ 24 giờ).
  - **Điểm 4 (False Positive Control):** Lọc tìm SG `crg-demo-sg-keep-control` và SG `default`. Kết quả không thấy (chứng minh bộ lọc triệt tiêu báo động giả).
  - **Điểm 5 (Thao tác FinOps):** Bấm **Giữ lại** cho Lambda function. Finding ẩn ngay lập tức. Bấm **Bỏ qua 7 ngày** cho ECR repository. Cuộn xuống mở bảng `Đang giữ và bỏ qua`.
- **Lời thoại (Voiceover):**
  > *"Lượt quét đã hoàn tất và kết quả đưa ra vô cùng ấn tượng:*
  > 
  > *1. Với kho ảnh ECR, hệ thống phát hiện ngay cảnh báo `Cần kiểm tra` với bằng chứng khách quan: `has_lifecycle_policy: false`, kèm khuyến nghị thiết lập vòng đời.*
  > *2. Với hàm Lambda, hệ thống đối chiếu CloudWatch xác nhận 0 lượt gọi và không có Event Source Mapping.*
  > 
  > *Đặc biệt nhất là ở ổ đĩa EBS và địa chỉ Elastic IP: hệ thống xếp vào trạng thái **Đang quan sát (OBSERVING)**. Đây là tính năng then chốt của Cloud Resource Guardian: chúng em không vội vã báo động khi tài nguyên vừa mới tạo, mà phải theo dõi liên tục đủ cửa sổ 24 giờ để tránh làm phiền kỹ sư với các tài nguyên đang dùng dở.*
  > 
  > *Ngược lại, Security Group có gắn thẻ `guardian:keep: true` và nhóm mặc định `default` hoàn toàn không bị báo động, chứng minh tỷ lệ báo động giả (False Positive) là 0%.*
  > 
  > *Khi cần xử lý, kỹ sư chỉ việc bấm **Giữ lại** hoặc chọn **Bỏ qua 7 ngày**. Finding sẽ được ẩn lập tức khỏi bảng điều khiển để giải phóng tầm nhìn, nhưng vẫn được lưu vết minh bạch tại khu vực quản lý phản hồi bên dưới."*
- **Evidence cần quay:** Modal chi tiết Evidence dạng bảng thuộc tính kỹ thuật rõ ràng; thông báo màu xanh `Đã giữ lại. Cảnh báo đã được ẩn.`

---

### [06:00 – 07:00] PHÂN CẢNH 6: KIỂM THỬ HIỆU NĂNG BẰNG K6
- **Thời lượng:** 60 giây.
- **Màn hình hiển thị:** Terminal chạy k6 và báo cáo `docs/NON_FUNCTIONAL_AUDIT.md`.
- **Thao tác:**
  - Mở terminal hiển thị kết quả kiểm thử tải an toàn `tests/performance/k6_readonly.js`.
  - Chỉ chuột vào các chỉ số: 156 requests, 0% lỗi HTTP, thời gian đáp ứng trung vị 975 ms, P90 1.48 giây.
- **Lời thoại (Voiceover):**
  > *"Bên cạnh tính năng, chúng em thực hiện kiểm thử phi chức năng về hiệu năng (Performance) bằng công cụ k6 tiêu chuẩn công nghiệp.*
  > 
  > *Với kịch bản tải an toàn dưới 2 requests/giây để bảo vệ ngân sách đám mây, CloudFront đã xử lý 156 requests liên tục với **tỷ lệ lỗi tuyệt đối 0.00%**, thời gian phản hồi trung vị đạt **975 mili-giây** và phân vị 90 đạt **1.48 giây**.*
  > 
  > *Hệ thống chứng minh khả năng phục vụ ổn định trên mạng lưới CDN mà không làm nghẽn API Gateway hay phát sinh lỗi kết nối."*
- **Evidence cần quay:** Bảng log xanh của k6 hiển thị `checks: 100.00%`, `http_req_failed: 0.00%`.

---

### [07:00 – 08:00] PHÂN CẢNH 7: ĐỘ BỀN BỈ & XỬ LÝ LỖI (FAULT TOLERANCE & PARTIAL)
- **Thời lượng:** 60 giây.
- **Màn hình hiển thị:** Thẻ trạng thái cam `Chưa đầy đủ` (`PARTIAL`) trên trang Tổng quan và chi tiết finding ALB.
- **Thao tác:**
  - Rê chuột vào thông báo lỗi: `SubscriptionRequiredException: FSX, MEMORYDB`.
  - Mở finding của ALB: chỉ vào lý do *"Missing CloudWatch metrics; not classified as idle"*, độ phủ `coverage = 0.0`.
- **Lời thoại (Voiceover):**
  > *"Một trong những điểm vượt trội của dự án là khả năng **chịu lỗi từng phần (Fault Tolerance)**:*
  > 
  > *Trong lượt quét vừa rồi, tài khoản thử nghiệm chưa kích hoạt gói cước cho FSx và MemoryDB. Thay vì bị crash toàn bộ hệ thống, scanner của chúng em đã bắt lỗi `SubscriptionRequiredException`, hiển thị huy hiệu màu cam **Chưa đầy đủ (PARTIAL)** và **bảo toàn nguyên vẹn 100% các kết quả thu thập được từ các dịch vụ khác**.*
  > 
  > *Đồng thời, đối với Application Load Balancer thiếu dữ liệu CloudWatch, hệ thống xếp vào mục **Thiếu dữ liệu (INSUFFICIENT_DATA)** với độ phủ 0%, kiên quyết không gán số liệu thiếu bằng 0 để kết luận bừa bãi là tài nguyên rảnh rỗi."*
- **Evidence cần quay:** Badge cam `PARTIAL` và lý do minh bạch trong chi tiết finding.

---

### [08:00 – 09:00] PHÂN CẢNH 8: LOGGING CLOUDWATCH & KIẾN TRÚC AN TOÀN
- **Thời lượng:** 60 giây.
- **Màn hình hiển thị:** AWS CloudWatch Console (Tab 3), Log Groups `/aws/lambda/cloud-resource-guardian-WorkerFunction...`.
- **Thao tác:**
  - Mở log stream mới nhất.
  - Tìm theo từ khóa `scan_completed`.
  - Chỉ vào các dòng log có cấu trúc JSON ghi nhận `ScanId: 34eb7157...`, `counts` và thời gian thực thi.
- **Lời thoại (Voiceover):**
  > *"Tại tầng giám sát (Observability), toàn bộ hoạt động quét đều được ghi log có cấu trúc vào AWS CloudWatch Logs. Mỗi sự kiện mang theo đúng `ScanId` để truy vết từ đầu đến cuối.*
  > 
  > *Về mặt FinOps và an toàn chi phí, toàn bộ hệ thống là **Serverless 100%**: không phát sinh chi phí duy trì khi không có lượt quét. Lượt quét hôm nay với hàng chục tài nguyên thực tế tốn chưa đầy **100 đồng Việt Nam**.*
  > 
  > *Cơ chế SQS Dead Letter Queue có chính sách redrive 5 lần đảm bảo không thất lạc sự kiện nếu có sự cố mạng xảy ra."*
- **Evidence cần quay:** JSON log trong CloudWatch hiển thị `ScanId: 34eb7157-dbec-454a-b796-452fc9c71d97`.

---

### [09:00 – 10:00] PHÂN CẢNH 9: TỔNG KẾT, ĐÁNH GIÁ ĐỊNH LƯỢNG & KẾT THÚC
- **Thời lượng:** 60 giây.
- **Màn hình hiển thị:** Bảng tổng hợp định lượng trong `docs/FINAL_NFR_RESULTS.md` và Trang chủ Cloud Guardian.
- **Thao tác:**
  - Trình chiếu bảng tổng kết: 9/9 test cases PASS (100%), 0 False Positives, 100% bằng chứng minh bạch.
  - Lời cảm ơn và chào kết thúc.
- **Lời thoại (Voiceover):**
  > *"Tổng kết lại buổi thực nghiệm hôm nay:*
  > - *Hệ thống đã hoàn thành xuất sắc **9 trên 9 kịch bản kiểm thử thực tế trên AWS**, đạt tỷ lệ chính xác quy tắc **100%**.*
  > - *Phát hiện chính xác các nhóm tài nguyên lãng phí thật (True Positives).*
  > - *Đạt tỷ lệ báo động nhầm bằng 0 (Zero False Positives).*
  > - *Chứng minh rõ ràng khả năng nhận biết khi nào **không đủ bằng chứng** để bảo vệ an toàn cho hệ thống của khách hàng.*
  > 
  > *Dự án Cloud Resource Guardian đã chứng minh là một công cụ FinOps thiết thực, tin cậy, an toàn và sẵn sàng cho môi trường thực tế.*
  > 
  > *Em xin chân thành cảm ơn quý thầy cô trong hội đồng và các bạn đã chú ý lắng nghe!"*

---

## 3. Checklist Sau khi Quay Video (Post-Recording Cleanup Checklist)

Sau khi hoàn tất quay video và lưu lại toàn bộ tư liệu:

- [ ] **Lệnh dọn dẹp tài nguyên thử nghiệm:**
  ```bash
  ./.venv/bin/python tests/demo_aws/manage_experiment.py destroy --profile datht --region ap-southeast-1
  ```
- [ ] **Xác minh đã xóa sạch tài nguyên:**
  - Xác nhận stack `crg-demo-experiment-stack` đã bị xóa khỏi CloudFormation.
  - Kiểm tra không còn EIP: `aws ec2 describe-addresses --allocation-ids eipalloc-094552008df2fbdc3 --region ap-southeast-1 --profile datht` (trả về `NotFound`).
  - Xác nhận chi phí duy trì trở về **$0.00**.
