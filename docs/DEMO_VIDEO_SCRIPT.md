# KỊCH BẢN QUAY VIDEO DEMO (7–9 PHÚT)
## CLOUD RESOURCE GUARDIAN — HỆ THỐNG GIÁM SÁT & PHÁT HIỆN LÃNG PHÍ TÀI NGUYÊN AWS

---

### Thông tin tổng quan
- **Thời lượng dự kiến:** 8 phút (dao động trong khoảng 7 – 9 phút).
- **Ngôn ngữ:** Tiếng Việt.
- **Mục tiêu:** Minh họa trực tiếp hệ thống đọc dữ liệu AWS thật, phát hiện chính xác tài nguyên lãng phí, đưa ra bằng chứng minh bạch và thể hiện tính nhân văn của giải pháp (không tự ý xóa tài nguyên của người dùng).
- **Địa chỉ website demo:** https://d3qn9wabid8ws0.cloudfront.net/
- **AWS Region thử nghiệm:** `ap-southeast-1` (Singapore).

---

### Phân cảnh chi tiết

#### PHÂN CẢNH 1: MỞ ĐẦU & GIỚI THIỆU HỆ THỐNG (0:00 – 1:15)
- **Hình ảnh trên màn hình:**
  - Mở trang chủ https://d3qn9wabid8ws0.cloudfront.net/.
  - Thao tác chuyển đổi mượt mà giữa các tab `Đăng nhập`, `Đăng ký`, `Quên mật khẩu`.
  - Phóng to nhẹ vào thanh điều hướng tối giản, sạch sẽ, không khẩu hiệu quảng cáo.
- **Lời thoại (Voiceover):**
  > *"Xin chào thầy cô và các bạn. Trong các doanh nghiệp sử dụng điện toán đám mây AWS, bài toán tối ưu chi phí (FinOps) luôn là thách thức lớn khi các tài nguyên như ổ cứng EBS chưa gắn, Elastic IP không liên kết hay kho ảnh ECR thiếu chính sách vòng đời thường bị bỏ quên và âm thầm phát sinh chi phí hàng tháng.*
  > 
  > *Hôm nay, em xin giới thiệu dự án **Cloud Resource Guardian** — hệ thống giám sát và phát hiện lãng phí tài nguyên AWS đa dịch vụ. Dự án hoạt động theo nguyên tắc an toàn tuyệt đối: **chỉ sử dụng quyền đọc (Read-only)**, **đưa ra bằng chứng cụ thể** và trao quyền quyết định xử lý cho kỹ sư phụ trách, tuyệt đối không tự ý can thiệp hay xóa tài nguyên của khách hàng."*

---

#### PHÂN CẢNH 2: ĐĂNG NHẬP COGNITO & GIAO DIỆN TỐI GIẢN (1:15 – 2:30)
- **Hình ảnh trên màn hình:**
  - Nhập thông tin hoặc bấm `Đăng nhập với AWS Cognito`.
  - Màn hình chuyển hướng bảo mật qua Cognito Hosted UI với chuẩn OAuth 2.0 PKCE S256 và quay trở về ứng dụng tại CloudFront.
  - Lướt nhanh qua Dashboard: 4 thẻ chỉ số tổng quan (`Tài nguyên đã quét`, `Cần kiểm tra`, `Đang quan sát`, `Thiếu dữ liệu`), card `Phạm vi theo dõi` và `Lần quét gần nhất`.
- **Lời thoại (Voiceover):**
  > *"Hệ thống sử dụng Amazon Cognito User Pool kết hợp luồng OAuth 2.0 Authorization Code có bảo vệ PKCE S256, đảm bảo phân lập dữ liệu người dùng (tenant isolation) an toàn.*
  > 
  > *Giao diện được thiết kế theo phong cách tối giản hiện đại: loại bỏ hoàn toàn các câu slogan thừa hay icon trang trí không cần thiết, tập trung trực tiếp vào số liệu kỹ thuật, đơn vị đo và trạng thái tài nguyên giúp kỹ sư nắm bắt thông tin nhanh chóng."*

---

#### PHÂN CẢNH 3: KẾT NỐI AWS ACCOUNT VÀ KÍCH HOẠT QUÉT THẬT (2:30 – 3:45)
- **Hình ảnh trên màn hình:**
  - Mở trang `Kết nối AWS`.
  - Hiển thị 3 bước thiết lập: Tải template `target-role.yaml`, dán `RoleArn` từ CloudFormation Outputs (`arn:aws:iam::376129867108:role/GuardianReadRole-demo`), chọn region `ap-southeast-1` và các nhóm dịch vụ.
  - Bấm **Kiểm tra và lưu kết nối**. Thông báo thành công màu xanh hiển thị.
  - Chuyển về trang `Tổng quan` và bấm nút **Quét ngay** (`Scan Now`).
  - Hiển thị trạng thái đang quét (spinner / polling 5s tự động cập nhật).
- **Lời thoại (Voiceover):**
  > *"Để kết nối tài khoản AWS cần quét, khách hàng không cần chia sẻ Access Key hay Secret Key. Chúng em cung cấp sẵn CloudFormation template tạo một IAM Role chỉ đọc mang tên `GuardianReadRole`, chỉ tin cậy đúng ExternalId riêng biệt của người dùng.*
  > 
  > *Bây giờ, em bấm nút **Quét ngay**. Hệ thống gửi yêu cầu quét bất đồng bộ tới backend serverless trên AWS, gọi các API của EC2, VPC, ECR, Lambda và CloudWatch Metrics trong region Singapore để đối chiếu với 39 quy tắc phát hiện."*

---

#### PHÂN CẢNH 4: PHÂN TÍCH KẾT QUẢ VÀ BẰNG CHỨNG THỰC TẾ (3:45 – 5:30)
- **Hình ảnh trên màn hình:**
  - Lượt quét hoàn tất chuyển sang badge xanh `Hoàn tất` (`SUCCEEDED`).
  - Mở trang `Tài nguyên cần kiểm tra`.
  - **Điểm 1 (TC04 — ECR_NO_LIFECYCLE):** Click vào finding `crg-demo-ecr-no-lifecycle`. Bấm nút **Xem chi tiết**. Mở modal hiển thị bằng chứng: `has_lifecycle_policy: false`.
  - **Điểm 2 (TC05 — LAMBDA_UNUSED):** Click vào finding `crg-demo-lambda-unused`. Mở modal hiển thị bằng chứng: `invocations = 0`, `event_source_mappings = 0`, runtime Python 3.12.
  - **Điểm 3 (TC01 & TC02 — EBS & EIP):** Lọc theo trạng thái `Đang quan sát` (`OBSERVING`). Cho thấy volume 1 GiB và Elastic IP đang ở trạng thái theo dõi thời gian chứ chưa bị kết luận vội vàng.
- **Lời thoại (Voiceover):**
  > *"Kết quả quét đã hiển thị đầy đủ trên màn hình:*
  > 
  > *Thứ nhất, đối với kho ảnh ECR `crg-demo-ecr-no-lifecycle`, hệ thống phát hiện ngay tại lần quét đầu tiên vì thiếu Lifecycle Policy. Bấm vào **Xem chi tiết**, chúng ta thấy rõ bằng chứng khách quan từ API, kèm khuyến nghị cụ thể.*
  > 
  > *Thứ hai, hàm Lambda `crg-demo-lambda-unused` không phát sinh bất kỳ lượt gọi nào trong cửa sổ 24 giờ của CloudWatch, được xếp vào diện cần kiểm tra.*
  > 
  > *Đặc biệt, quý thầy cô có thể thấy ở ổ cứng EBS và địa chỉ Elastic IP mới tạo, hệ thống xếp vào trạng thái **Đang quan sát (OBSERVING)** thay vì báo động ngay lập tức. Đây là điểm vượt trội của Cloud Resource Guardian: chúng em thiết lập cửa sổ quan sát thực tế để tránh báo động giả khi tài nguyên chỉ vừa mới được tạo ra phục vụ công việc tạm thời."*

---

#### PHÂN CẢNH 5: KIỂM SOÁT BÁO NHẦM & BẢO VỆ DỮ LIỆU THIẾU (5:30 – 6:30)
- **Hình ảnh trên màn hình:**
  - Lọc tìm kiếm tài nguyên `crg-demo-sg-keep-control` (đã gắn tag `guardian:keep: true`) và Security Group `default`.
  - Màn hình hiển thị: *"Không có tài nguyên phù hợp"* (chứng minh bộ lọc triệt tiêu báo động giả).
  - Mở mục `Thiếu dữ liệu` (`INSUFFICIENT_DATA`) giải thích trường hợp tài nguyên mới hơn cửa sổ quan sát.
- **Lời thoại (Voiceover):**
  > *"Để chứng minh tính chính xác trong việc kiểm soát báo động giả (False Positive Control):*
  > 
  > *Trong tài khoản, em đã tạo một Security Group thử nghiệm nhưng gắn thẻ `guardian:keep = true` đại diện cho các tài nguyên dự phòng có chủ đích. Kết quả cho thấy hệ thống triệt tiêu hoàn toàn và không đưa vào danh sách cảnh báo.*
  > 
  > *Tương tự, các tài nguyên thiếu số liệu metrics của CloudWatch sẽ được đưa vào mục **Thiếu dữ liệu** với thông báo rõ ràng, thay vì giả định ngầm số liệu thiếu bằng 0 để kết luận sai lệch."*

---

#### PHÂN CẢNH 6: THAO TÁC FINOPS — GIỮ LẠI & BỎ QUA CẢNH BÁO (6:30 – 7:30)
- **Hình ảnh trên màn hình:**
  - Tại bảng cảnh báo, bấm nút **Giữ lại** cho Lambda function. Finding biến mất khỏi danh sách chính, xuất hiện thông báo: *"Đã giữ lại. Cảnh báo đã được ẩn."*
  - Tại finding ECR, chọn menu **Bỏ qua 7 ngày**. Finding được ẩn.
  - Cuộn xuống phần `Đang giữ và bỏ qua` bên dưới: Hiển thị 2 bản ghi vừa thao tác, kèm nút `Bỏ giữ lại` và `Hủy bỏ qua`.
  - Mở trang `Cấu hình`: Hiển thị Accordion dọc 1 cột với 6 nhóm dịch vụ, điều chỉnh một giá trị ngưỡng và bấm **Lưu thay đổi**.
- **Lời thoại (Voiceover):**
  > *"Khi nhận được cảnh báo, kỹ sư vận hành có 2 lựa chọn xử lý nhanh ngay trên giao diện:*
  > - *Bấm **Giữ lại** nếu xác định tài nguyên cần thiết cho hệ thống.*
  > - *Bấm **Bỏ qua 7 ngày** nếu tài nguyên đang trong giai đoạn thử nghiệm.*
  > 
  > *Mọi phản hồi được lưu trữ minh bạch và có thể hủy bỏ bất cứ lúc nào tại khu vực quản lý phản hồi bên dưới. Đồng thời, kỹ sư có thể linh hoạt điều chỉnh toàn bộ 40 ngưỡng phát hiện trong 6 nhóm dịch vụ tại trang Cấu hình để phù hợp với đặc thù dự án."*

---

#### PHÂN CẢNH 7: KẾT LUẬN & DỌN DẸP TỰ ĐỘNG (7:30 – 8:15)
- **Hình ảnh trên màn hình:**
  - Mở terminal chạy lệnh: `python tests/demo_aws/manage_experiment.py destroy --region ap-southeast-1`.
  - Hiển thị thông báo stack CloudFormation đã xóa sạch toàn bộ tài nguyên thử nghiệm.
  - Quay lại trang chủ website tổng kết.
- **Lời thoại (Voiceover):**
  > *"Kết thúc buổi demo, em kích hoạt lệnh dọn dẹp tự động. Toàn bộ các tài nguyên demo được xóa sạch trong tích tắc thông qua CloudFormation manifest, tổng chi phí thực tế cho toàn bộ bài kiểm tra chỉ chưa đầy mười nghìn đồng.*
  > 
  > *Cloud Resource Guardian đã chứng minh là một giải pháp FinOps an toàn, đáng tin cậy, đọc dữ liệu thật từ AWS và biết chính xác khi nào **đủ bằng chứng** hoặc **không đủ bằng chứng** để đưa ra khuyến nghị. Em xin chân thành cảm ơn quý thầy cô và các bạn đã chú ý theo dõi."*
