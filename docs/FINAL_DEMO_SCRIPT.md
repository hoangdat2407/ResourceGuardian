# KỊCH BẢN QUAY VIDEO DEMO CUỐI KỲ (10 PHÚT)
## CLOUD RESOURCE GUARDIAN — GIÁM SÁT & TỐI ƯU HÓA CHI PHÍ TÀI NGUYÊN AWS

---

### Thông tin chung
- **Thời lượng:** 10 phút (00:00 – 10:00).
- **Ngôn ngữ:** Tiếng Việt.
- **Phong cách trình bày:** Chuyên nghiệp, trực diện, bằng chứng thực tế, không lý thuyết sáo rỗng.
- **Môi trường demo:** Production Website https://d3qn9wabid8ws0.cloudfront.net/ & AWS Console Singapore (`ap-southeast-1`).
- **Tài khoản AWS:** `376129867108`.

---

### Phân cảnh chi tiết 10 phút

#### [00:00 – 01:00] PHÂN CẢNH 1: GIỚI THIỆU & KIẾN TRÚC SERVERLESS
- **Thời lượng:** 60 giây.
- **Màn hình cần mở:**
  1. Slide hoặc sơ đồ kiến trúc hệ thống (`BC1-kien-truc-chuc-nang.png` hoặc `BC2-kien-truc-trien-khai.png`).
  2. Website production https://d3qn9wabid8ws0.cloudfront.net/.
- **Thao tác thực hiện:**
  - Trỏ chuột vào các tầng kiến trúc: CloudFront CDN, API Gateway, 5 hàm AWS Lambda, DynamoDB, Cognito User Pool và tài khoản khách hàng được quét.
- **Lời thoại tự nhiên:**
  > *"Kính chào quý thầy cô và các bạn. Trong quản trị đám mây AWS, lãng phí chi phí (FinOps waste) thường phát sinh âm thầm từ các tài nguyên bị bỏ quên sau khi thử nghiệm hoặc kết thúc dự án: ví dụ ổ cứng EBS tháo rời nhưng không xóa, IP tĩnh không gắn hay kho ảnh container không có vòng đời.*
  > 
  > *Dự án **Cloud Resource Guardian** được chúng em xây dựng như một giải pháp FinOps an toàn tuyệt đối, hoạt động hoàn toàn trên nền tảng **Serverless 100% của AWS**. Hệ thống tuân thủ nghiêm ngặt 3 nguyên tắc vàng:*
  > *1. **Strictly Read-Only:** Chỉ sử dụng quyền đọc, tuyệt đối không can thiệp hay xóa tài nguyên của khách hàng.*
  > *2. **Bằng chứng khách quan:** Mọi cảnh báo đều đi kèm dữ liệu metrics CloudWatch và thuộc tính kỹ thuật cụ thể.*
  > *3. **Tôn trọng quyền chủ động:** Khách hàng là người duy nhất quyết định giữ lại hay giải phóng tài nguyên."*
- **Evidence cần quay:** Sơ đồ khối kiến trúc kết nối qua IAM Role.
- **Phương án thay thế nếu có sự cố:** Mở hình ảnh sơ đồ vẽ trên Draw.io sẵn trong repo.

---

#### [01:00 – 02:00] PHÂN CẢNH 2: ĐĂNG NHẬP COGNITO & KẾT NỐI AWS BẰNG GUARDIANREADROLE
- **Thời lượng:** 60 giây.
- **Màn hình cần mở:** Trang web https://d3qn9wabid8ws0.cloudfront.net/.
- **Thao tác thực hiện:**
  - Nhập thông tin đăng nhập Cognito qua luồng PKCE S256 bảo mật.
  - Sau khi đăng nhập, mở trang `Kết nối AWS`.
  - Hiển thị thông số kết nối: Role ARN `arn:aws:iam::376129867108:role/GuardianReadRole-demo` và ExternalId.
  - Bấm nút **Kiểm tra và lưu kết nối**. Badge chuyển sang màu xanh `Đã kết nối`.
- **Lời thoại tự nhiên:**
  > *"Để bắt đầu, em đăng nhập vào hệ thống qua Amazon Cognito User Pool. Toàn bộ phiên làm việc được mã hóa bằng OAuth 2.0 PKCE S256, đảm bảo phân lập dữ liệu người dùng đa người thuê (Multi-tenant isolation).*
  > 
  > *Ở bước kết nối AWS, khách hàng không bao giờ phải cung cấp Access Key hay Secret Key. Chúng em cung cấp sẵn CloudFormation template tạo một IAM Role chỉ đọc mang tên `GuardianReadRole`. Role này áp dụng điều kiện `sts:ExternalId` duy nhất của tài khoản đăng nhập, ngăn chặn hoàn toàn nguy cơ tấn công tráo quyền Confused Deputy.*
  > 
  > *Em chọn khu vực quét Singapore (`ap-southeast-1`) và lưu kết nối thành công."*
- **Evidence cần quay:** Thẻ xác nhận kết nối xanh `Đã kết nối` và chuỗi Role ARN chuẩn.
- **Phương án thay thế:** Trình chiếu tệp template `target-role.yaml` giải thích các action chỉ đọc.

---

#### [02:00 – 03:00] PHÂN CẢNH 3: MINH CHỨNG TÀI NGUYÊN THỰC TẾ TRÊN AWS CONSOLE
- **Thời lượng:** 60 giây.
- **Màn hình cần mở:** AWS Management Console tài khoản `376129867108`, Region Singapore.
- **Thao tác thực hiện:**
  - Mở EC2 Console: quay ổ cứng EBS `vol-0dd1bd1d0f63a7f87` (trạng thái `available`, chưa gắn).
  - Mở Elastic IP: quay địa chỉ `54.151.234.194` (`Association ID: -`).
  - Mở Security Groups: chỉ vào `crg-demo-sg-unused` (0 ENI) và `crg-demo-sg-keep-control` (có tag `guardian:keep = true`).
  - Mở ECR Console: chỉ vào repo `crg-demo-ecr-no-lifecycle` (không có Lifecycle Policy).
  - Mở Lambda Console: hàm `crg-demo-lambda-unused` (0 invocations).
- **Lời thoại tự nhiên:**
  > *"Để chứng minh hệ thống đọc dữ liệu AWS thật 100%, em xin mở trực tiếp giao diện AWS Management Console:*
  > - *Tại đây, chúng ta có một ổ đĩa EBS gp3 dung lượng 1 GiB ở trạng thái `available`.*
  > - *Một địa chỉ IP tĩnh Elastic IP chưa gắn vào bất kỳ máy chủ nào.*
  > - *Một Security Group trống không đính kèm card mạng.*
  > - *Một kho ảnh container ECR hoàn toàn không có chính sách vòng đời.*
  > - *Và một hàm Lambda không hề phát sinh lệnh gọi nào.*
  > 
  > *Tất cả các tài nguyên này đã được gắn thẻ nhận diện dự án rõ ràng và sẵn sàng cho đợt rà soát."*
- **Evidence cần quay:** Thuộc tính `available` của EBS, `No association` của EIP, tag `guardian:keep: true` của SG.
- **Phương án thay thế:** Xem tệp `tests/demo_aws/manifest.json`.

---

#### [03:00 – 04:00] PHÂN CẢNH 4: CẤU HÌNH NGƯỠNG & KÍCH HOẠT QUÉT NGAY
- **Thời lượng:** 60 giây.
- **Màn hình cần mở:**
  1. Trang `Cấu hình` (`#page-settings`).
  2. Trang `Tổng quan` (`#page-overview`).
- **Thao tác thực hiện:**
  - Mở trang `Cấu hình`: Click mở Accordion 6 nhóm dịch vụ, chỉ vào 40 trường ngưỡng tùy chỉnh. Bấm **Lưu thay đổi**.
  - Quay lại trang `Tổng quan`, bấm nút **Quét ngay** (`Scan Now`).
  - Đồng hồ đếm ngược và trạng thái polling tự động kích hoạt.
- **Lời thoại tự nhiên:**
  > *"Trước khi quét, kỹ sư có thể tùy chỉnh toàn bộ 40 ngưỡng phát hiện trong 6 nhóm dịch vụ tại trang Cấu hình. Thiết kế Accordion dọc tối giản 1 cột giúp tra cứu tiện lợi và ẩn hoàn toàn các mã kỹ thuật Rule ID gây rối mắt.*
  > 
  > *Bây giờ, em bấm nút **Quét ngay**. Phía sau hậu trường, Lambda API Function sẽ kích hoạt Worker Lambda qua cơ chế Event-driven bất đồng bộ. Worker sẽ dùng quyền của GuardianReadRole để duyệt qua 38 loại tài nguyên và tính toán số liệu metrics trong cửa sổ 24 giờ của CloudWatch.*
  > 
  > *Giao diện sẽ tự động cập nhật kết quả mà người dùng không cần bấm F5 tải lại trang."*
- **Evidence cần quay:** Nút `Quét ngay` chuyển sang trạng thái đang quét, thanh tiến độ polling 5s.
- **Phương án thay thế:** Xem kết quả lượt quét đã lưu trong `Lịch sử quét`.

---

#### [04:00 – 06:00] PHÂN CẢNH 5: BẰNG CHỨNG PHÁT HIỆN & THAO TÁC FINOPS (KEEP / IGNORE)
- **Thời lượng:** 120 giây (2 phút).
- **Màn hình cần mở:** Trang `Tài nguyên cần kiểm tra` (`#page-findings`) và Modal `#finding-dialog`.
- **Thao tác thực hiện:**
  - **Điểm 1 (ECR No Lifecycle):** Mở finding `crg-demo-ecr-no-lifecycle`. Bấm **Xem chi tiết**. Mở bảng Evidence chỉ rõ `has_lifecycle_policy: false`. Đóng popup.
  - **Điểm 2 (Lambda Unused):** Mở finding `crg-demo-lambda-unused`. Chỉ rõ bằng chứng `invocations = 0`.
  - **Điểm 3 (EBS & EIP - Observing Window):** Lọc theo trạng thái `Đang quan sát` (`OBSERVING`). Giải thích tại sao volume `vol-0dd1bd1d0f63a7f87` chưa bị kết luận xóa ngay (vì mới tạo, cần đủ 24 giờ).
  - **Điểm 4 (False Positive Control):** Lọc tìm SG `crg-demo-sg-keep-control` và SG `default`. Kết quả không thấy (chứng minh bộ lọc triệt tiêu báo động giả).
  - **Điểm 5 (Thao tác FinOps):** Bấm **Giữ lại** cho Lambda function. Finding ẩn ngay lập tức. Bấm **Bỏ qua 7 ngày** cho ECR repository. Cuộn xuống mở bảng `Đang giữ và bỏ qua`.
- **Lời thoại tự nhiên:**
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
- **Phương án thay thế:** Mở ảnh chụp `docs/screenshots/03-evidence-ecr-no-lifecycle.png` và `06-feedback-keep-ignore.png`.

---

#### [06:00 – 07:00] PHÂN CẢNH 6: KIỂM THỬ HIỆU NĂNG BẰNG K6 (PERFORMANCE NFR)
- **Thời lượng:** 60 giây.
- **Màn hình cần mở:** Terminal chạy k6 và kết quả tệp báo cáo `docs/NON_FUNCTIONAL_AUDIT.md`.
- **Thao tác thực hiện:**
  - Mở terminal: chạy đoạn script kiểm thử đọc an toàn `tests/performance/k6_readonly.js` hoặc hiển thị bảng tổng kết k6.
  - Chỉ vào các chỉ số: 156 requests, 0% lỗi HTTP, thời gian đáp ứng trung vị 975 ms, P95 1.77 giây.
- **Lời thoại tự nhiên:**
  > *"Bên cạnh tính năng, chúng em thực hiện kiểm thử phi chức năng về hiệu năng (Performance) bằng công cụ k6 tiêu chuẩn công nghiệp.*
  > 
  > *Với kịch bản tải an toàn dưới 2 requests/giây để bảo vệ ngân sách đám mây, CloudFront đã xử lý 156 requests liên tục với **tỷ lệ lỗi tuyệt đối 0.00%**, thời gian phản hồi trung vị đạt **975 mili-giây** và phân vị 95 đạt **1.77 giây**.*
  > 
  > *Hệ thống chứng minh khả năng chịu tải ổn định mà không làm nghẽn API Gateway hay vượt hạn ngạch của dịch vụ."*
- **Evidence cần quay:** Bảng log xanh của k6 hiển thị `checks: 100.00%`, `http_req_failed: 0.00%`.
- **Phương án thay thế:** Trình chiếu tệp kết quả k6 trong `docs/NON_FUNCTIONAL_AUDIT.md`.

---

#### [07:00 – 08:00] PHÂN CẢNH 7: ĐỘ BỀN BỈ & XỬ LÝ LỖI (FAULT TOLERANCE & PARTIAL SCAN)
- **Thời lượng:** 60 giây.
- **Màn hình cần mở:**
  1. Thẻ trạng thái cam `Chưa đầy đủ` (`PARTIAL`) trên trang Tổng quan.
  2. Bằng chứng ALB `test-idle-alb` trong mục `Thiếu dữ liệu`.
- **Thao tác thực hiện:**
  - Rê chuột vào thông báo lỗi: `SubscriptionRequiredException: FSX, MEMORYDB`.
  - Mở finding của ALB: chỉ vào lý do *"Missing CloudWatch metrics; not classified as idle"*, độ phủ `coverage = 0.0`.
- **Lời thoại tự nhiên:**
  > *"Một trong những điểm vượt trội của dự án là khả năng **chịu lỗi từng phần (Fault Tolerance)**:*
  > 
  > *Trong lượt quét vừa rồi, tài khoản thử nghiệm chưa kích hoạt gói cước cho FSx và MemoryDB. Thay vì bị crash toàn bộ hệ thống, scanner của chúng em đã bắt lỗi `SubscriptionRequiredException`, hiển thị huy hiệu màu cam **Chưa đầy đủ (PARTIAL)** và **bảo toàn nguyên vẹn 100% các kết quả thu thập được từ các dịch vụ khác**.*
  > 
  > *Đồng thời, đối với Application Load Balancer thiếu dữ liệu CloudWatch, hệ thống xếp vào mục **Thiếu dữ liệu (INSUFFICIENT_DATA)** với độ phủ 0%, kiên quyết không gán số liệu thiếu bằng 0 để kết luận bừa bãi là tài nguyên rảnh rỗi."*
- **Evidence cần quay:** Badge cam `PARTIAL` và lý do minh bạch trong chi tiết finding.
- **Phương án thay thế:** Xem mã nguồn xử lý ngoại lệ trong `src/collectors.py:930`.

---

#### [08:00 – 09:00] PHÂN CẢNH 8: LOGGING CLOUDWATCH & KIẾN TRÚC AN TOÀN
- **Thời lượng:** 60 giây.
- **Màn hình cần mở:** AWS CloudWatch Log Groups của Lambda (`/aws/lambda/cloud-resource-guardian-WorkerFunction...`).
- **Thao tác thực hiện:**
  - Mở CloudWatch Logs Insights hoặc Log stream mới nhất.
  - Tìm theo từ khóa `scan_completed` hoặc `metric_series`.
  - Chỉ vào các dòng log có cấu trúc JSON ghi nhận `ScanId`, `counts` và thời gian thực thi.
- **Lời thoại tự nhiên:**
  > *"Tại tầng giám sát (Observability), toàn bộ hoạt động quét đều được ghi log có cấu trúc vào AWS CloudWatch Logs. Mỗi sự kiện mang theo đúng `ScanId` để truy vết từ đầu đến cuối.*
  > 
  > *Về mặt FinOps và an toàn chi phí, toàn bộ hệ thống là **Serverless 100%**: không phát sinh chi phí duy trì khi không có lượt quét. Lượt quét hôm nay với hàng chục tài nguyên thực tế tốn chưa đầy **100 đồng Việt Nam**.*
  > 
  > *Cơ chế SQS Dead Letter Queue có chính sách redrive 5 lần đảm bảo không thất lạc sự kiện nếu có sự cố mạng xảy ra."*
- **Evidence cần quay:** JSON log trong CloudWatch hiển thị `ScanId: 34eb7157-dbec-454a-b796-452fc9c71d97`.
- **Phương án thay thế:** Xem log đã lưu trong tệp báo cáo `docs/DEMO_EXPERIMENT_RESULTS.md`.

---

#### [09:00 – 10:00] PHÂN CẢNH 9: TỔNG KẾT, ĐÁNH GIÁ ĐỊNH LƯỢNG & KẾT THÚC
- **Thời lượng:** 60 giây.
- **Màn hình cần mở:**
  1. Bảng tổng hợp định lượng trong `docs/DEMO_EXPERIMENT_RESULTS.md`.
  2. Trang chủ hệ thống Cloud Resource Guardian.
- **Thao tác thực hiện:**
  - Trình chiếu bảng tổng hợp: 9/9 test cases PASS (100%), 0 False Positives, 100% bằng chứng minh bạch.
  - Lời cảm ơn và chào kết thúc.
- **Lời thoại tự nhiên:**
  > *"Tổng kết lại buổi thực nghiệm hôm nay:*
  > - *Hệ thống đã hoàn thành xuất sắc **9 trên 9 kịch bản kiểm thử thực tế trên AWS**, đạt tỷ lệ chính xác **100%**.*
  > - *Phát hiện chính xác 5 nhóm tài nguyên lãng phí thật (True Positives).*
  > - *Đạt tỷ lệ báo động nhầm bằng 0 (Zero False Positives).*
  > - *Chứng minh rõ ràng khả năng nhận biết khi nào **không đủ bằng chứng** để bảo vệ an toàn cho hệ thống của khách hàng.*
  > 
  > *Dự án Cloud Resource Guardian đã chứng minh là một công cụ FinOps thiết thực, tin cậy, an toàn và sẵn sàng cho môi trường thực tế.*
  > 
  > *Em xin chân thành cảm ơn quý thầy cô trong hội đồng và các bạn đã chú ý lắng nghe!"*
- **Evidence cần quay:** Màn hình kết thúc hiển thị bảng tổng kết số liệu và logo Cloud Guardian.
