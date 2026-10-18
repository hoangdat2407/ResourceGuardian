# Cloud Resource Guardian — MVP

Bản MVP của Cloud-T9, triển khai trên AWS bằng Python/boto3 và Lambda. Gồm mã nguồn frontend, backend, hạ tầng AWS SAM và script triển khai. Chưa có stack hoặc website công khai trên AWS: cần đăng nhập account của bạn để triển khai.

## 1. Thử ngay tại máy, không cần AWS

Cài Python 3.12, giải nén ZIP rồi mở terminal tại thư mục `Cloud-Resource-Guardian-MVP`:

```powershell
python demo.py
```

Mở **http://127.0.0.1:8080**, chọn **Mở dashboard demo**. Dữ liệu gắn nhãn DEMO là dữ liệu mẫu; chế độ này không dùng AWS SDK, không xác thực Cognito thật, không gửi email và không phát hiện tài nguyên thật. Dữ liệu demo nằm trong RAM, khởi động lại sẽ reset.

Có thể thử dashboard, tìm/lọc cảnh báo, cấu hình, bỏ qua 7 ngày, quét ngay và lịch sử. Quét demo chạy trong khoảng ba giây, dashboard cập nhật mỗi năm giây. Demo không áp dụng cooldown 15 phút của AWS thật. Dừng bằng Ctrl+C.

## 2. Phạm vi AWS thật

| Tính năng | Cách thực hiện |
|---|---|
| Đăng ký, đăng nhập, đăng xuất | Cognito Hosted UI, Authorization Code + PKCE; token chỉ lưu trong sessionStorage |
| Nhiều người dùng | API Gateway xác minh JWT; backend lấy userId từ claim `sub`, không lấy từ body |
| Kết nối AWS | Một account/người dùng; STS AssumeRole, Role ARN và ExternalId riêng |
| Quét tài nguyên | EC2, EBS volume, Elastic IP, EBS snapshot; tối đa ba region/người dùng |
| Quét ngay | POST `/scans` trả `scan_id`; Lambda backend Invoke async Lambda worker |
| Theo dõi tiến độ | API trạng thái và frontend tự lấy kết quả mỗi năm giây |
| Quét định kỳ | EventBridge kích hoạt Lambda scheduler mỗi giờ, chọn profile đến hạn |
| Lưu kết quả | DynamoDB theo tenant; lịch sử 30 ngày, màn hình 20 lần quét region gần nhất |
| Ngoại lệ | Tag `guardian:keep=true`, giữ lại nội bộ qua API và bỏ qua tài nguyên 1–30 ngày (web mặc định 7); áp dụng từ lần quét tiếp theo |
| Email tùy chọn | SES gửi tới email Cognito đã xác minh; chỉ gửi khi danh sách REVIEW thay đổi |
| Xử lý lỗi | PARTIAL khi một phần API lỗi; async retry, SQS chỉ là failure destination |

Ứng dụng không có quyền dừng hoặc xóa tài nguyên account cần quét. Người dùng kiểm tra cảnh báo rồi xử lý trong AWS Console.

## 3. Triển khai trên AWS — Windows / PowerShell

### 3.1. Công cụ và đăng nhập

Cần Python 3.12 và AWS CLI v2 cập nhật. Script `deploy.py` không cần Docker hoặc SAM CLI. Tài khoản triển khai cần quyền tạo stack CloudFormation và các dịch vụ IAM, Lambda, API Gateway, Cognito, DynamoDB, EventBridge, SQS, S3, CloudFront, CloudWatch Logs; thêm SES nếu bật email. Dùng account lab dành cho môn học.

Nếu đăng nhập AWS Console thông thường, AWS CLI >=2.32.0 hỗ trợ:

```powershell
aws login --profile guardian-lab
aws configure set region ap-southeast-1 --profile guardian-lab
aws sts get-caller-identity --profile guardian-lab
```

`aws login` mở trình duyệt để bạn tự đăng nhập. IAM identity cần `SignInLocalDevelopmentAccess` cho cách đăng nhập này. Nếu account dùng IAM Identity Center, dùng `aws configure sso --profile guardian-lab` rồi `aws sso login --profile guardian-lab`.

Không gửi access key, secret, session token, mật khẩu hoặc mã MFA vào chat. Đăng nhập tại máy không tự chia sẻ phiên AWS với ChatGPT.

### 3.2. Cài dependencies triển khai

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-deploy.txt
```

Trong Linux/macOS, dùng `.venv/bin/python` thay `.\.venv\Scripts\python.exe`.

### 3.3. Tạo bản thay đổi để kiểm tra trước (tùy chọn)

```powershell
.\.venv\Scripts\python.exe deploy.py --profile guardian-lab --region ap-southeast-1 --domain-prefix crg-cloudt9-CHUOI-RIENG --plan
```

Thay `CHUOI-RIENG` bằng chữ thường/số để domain Cognito không trùng toàn vùng. `--plan` tạo bucket artifact và upload code, rồi tạo change set; chưa thực thi hạ tầng ứng dụng. Script in các tài nguyên dự kiến và lệnh execute change set. Chỉ thực thi change set sau khi bạn kiểm tra đúng account và stack. Đợi CREATE_COMPLETE/UPDATE_COMPLETE rồi chạy `publish.py`.

### 3.4. Hoặc triển khai và xuất bản web trong một lệnh

```powershell
.\.venv\Scripts\python.exe deploy.py --profile guardian-lab --region ap-southeast-1 --domain-prefix crg-cloudt9-CHUOI-RIENG
```

Script đóng gói Lambda, upload S3, tạo change set, thực thi, chờ CloudFormation rồi upload ba file frontend và `config.json`. CloudFront có thể cần vài phút. Cuối cùng script in **WebUrl**; mở URL đó để đăng ký tài khoản bằng email và xác minh email.

Hạ tầng chính: private S3 + CloudFront → Cognito / API Gateway → Lambda backend / scheduler / worker → DynamoDB; worker dùng STS và AWS SDK đọc account người dùng. SQS chỉ nhận các sự kiện quét thất bại sau retry.

Template hiện không đặt ReservedConcurrentExecutions cho worker để phù hợp account lab có quota Lambda bằng 10. API, scheduler và worker dùng chung concurrency của account; worker không có giới hạn riêng bằng 3. Lease theo tenant, cooldown và API throttling vẫn được giữ. Chỉ đặt reserved concurrency sau khi quota cho phép giữ đủ phần unreserved mà AWS yêu cầu. Khi stack lỗi, xem CloudFormation Events trước khi thử lại.

### 3.5. Bật email (tùy chọn)

Thêm `--sender-email email-cua-ban@example.com` vào lệnh deploy. CloudFormation tạo SES EmailIdentity; mở thư xác minh được AWS gửi tới địa chỉ đó. Nếu SES đang trong sandbox, địa chỉ người nhận cũng phải được xác minh tại SES **ap-southeast-1**. Địa chỉ nhận của ứng dụng lấy từ email Cognito đã xác minh; người dùng không nhập tùy ý người nhận.

Trên web, mở Cấu hình & cảnh báo → bật email. Gửi email thất bại không làm mất kết quả quét; dashboard hiển thị lỗi và thử lại ở lần quét sau. Dedup theo danh sách resource REVIEW, không theo từng thay đổi nhỏ của CPU. SES không cung cấp giao dịch chung với DynamoDB; trường hợp hiếm khi gửi thành công nhưng lưu dấu gửi thất bại có thể dẫn tới email trùng.

## 4. Kết nối AWS account cần quét

1. Đăng nhập web → Kết nối AWS → mở hướng dẫn tạo role.
2. Sao chép **ApiPrincipal**, **ScanPrincipal**, **ExternalId**.
3. Trong account cần quét, triển khai `target-role.yaml` bằng CloudFormation Console hoặc CLI bên dưới.
4. Dán RoleArn từ Outputs vào web, chọn các region thực sự chứa tài nguyên, bấm Kiểm tra và lưu kết nối.
5. Bấm Quét ngay. Dashboard tự cập nhật kết quả.

Ví dụ PowerShell (thay giá trị giữa dấu `<...>`):

```powershell
aws cloudformation deploy --template-file target-role.yaml --stack-name guardian-read-role-demo --capabilities CAPABILITY_NAMED_IAM --parameter-overrides ApiPrincipal='<ARN_API_ROLE>' ScanPrincipal='<ARN_WORKER_ROLE>' ExternalId='<EXTERNAL_ID>' RoleSuffix=demo --region ap-southeast-1 --profile guardian-lab
aws cloudformation describe-stacks --stack-name guardian-read-role-demo --query 'Stacks[0].Outputs' --region ap-southeast-1 --profile guardian-lab
```

Dùng profile của account đích nếu khác account triển khai. Mỗi người dùng nên có RoleSuffix riêng. Role không có path và tên phải là `GuardianReadRole-<suffix>`; trust policy chỉ cho hai principal và ExternalId tương ứng. Policy Resource `*` áp dụng cho các API Describe/GetMetricData được liệt kê, không phải mọi thao tác AWS.

## 5. Rule và giới hạn quan sát

- **EC2:** instance running và tồn tại trước cửa sổ 24–168 giờ (mặc định 24). GetMetricData lấy Maximum CPU mỗi giờ rồi tính p95; NetworkIn/Out lấy Sum mỗi giờ, tính trung bình trên số giờ thực đo riêng từng chiều rồi cộng thành MiB/giờ. Cả ba metric cần ít nhất `ceil(window_hours × 80%)` mẫu. Không đủ độ phủ hoặc có mẫu không hợp lệ thì trả `INSUFFICIENT_DATA`; giờ thiếu không được coi là 0. CPU và network thấp là heuristic, không chứng minh instance vô dụng.
- **EBS/EIP:** bắt đầu tính thời gian không dùng từ lần quan sát đầu tiên; không dùng tuổi tài nguyên như thời gian không attach/associate. Vẫn cập nhật quan sát khi tài nguyên được giữ lại hoặc bỏ qua. Khi thấy được sử dụng lại, reset cửa sổ. Khoảng trống giữa quan sát >48 giờ cũng reset. Thay đổi giữa hai lần quét có thể không được phát hiện.
- **Snapshot:** tuổi >=ngưỡng, trạng thái completed, không có tag giữ lại và không tham chiếu bởi các AMI đã đọc (bao gồm AMI bị vô hiệu hóa); bỏ qua dấu hiệu AWS Backup. Đây chưa phải kiểm tra đầy đủ backup/retention. Không ước tính tiền snapshot theo VolumeSize. Nếu danh sách AMI bị cắt, không đánh dấu snapshot là không được tham chiếu.
- Chỉ đọc region đã chọn. Mỗi loại tối đa 100 tài nguyên/region và 50 findings/region; vượt giới hạn báo PARTIAL. Worker time budget 300 giây. Account lớn cần chia job, tăng giới hạn có kiểm soát và kiểm thử tải.
- Một account/người dùng, tối đa ba region trong danh sách hỗ trợ. Kết nối lại sẽ bắt đầu cửa sổ EBS/EIP mới; kết quả và ngoại lệ cũ không áp dụng cho kết nối mới.
- Quét thủ công tối thiểu 15 phút/lần. Job chưa hoàn tất sau 15 phút hiển thị TIMED_OUT; kiểm tra failure queue rồi quét lại. Async delivery có thể lặp; worker có lease và kiểm tra scan_id để không ghi đè kết quả mới.
- Scheduler scan bảng DynamoDB mỗi giờ, phù hợp MVP ít người dùng. Khi tăng quy mô cần GSI theo due time, quota tenant và chia lô. Chưa có quota tenant toàn platform hoặc giới hạn chi phí cứng.

Xem [RULES.md](RULES.md) cho danh mục rule, cấu trúc bằng chứng, hợp đồng collector và API giữ lại nội bộ. Finding bổ sung `rule_id` và `recommendation`, giữ các trường cũ cho frontend hiện tại. Nút giữ lại trên dashboard thuộc mục 9, chưa bổ sung ở mục 7.

## 6. API contract

Tất cả API yêu cầu Cognito access token trong `Authorization: Bearer ...`. API Gateway xác minh JWT, Lambda kiểm tra `token_use=access`. Tenant luôn lấy từ `sub`.

| Method | Route | Nội dung |
|---|---|---|
| GET | /me | Profile, thông tin tạo IAM Role và khả năng gửi email |
| PUT | /connection | role_arn, regions; STS xác minh account |
| PUT | /settings | Sáu ngưỡng số có kiểm tra min/max |
| POST | /scans | Tạo job; 202 + scan_id, 409 nếu đang chạy, 429 nếu chưa đủ 15 phút |
| GET | /scans/{scanId} | Trạng thái/kết quả của scan thuộc người dùng; scan cũ ngoài 20 lịch sử có thể 404 |
| GET | /findings | Kết quả hiện tại theo region của kết nối hiện tại |
| GET | /history | 20 kết quả region hoàn tất gần nhất; retention 30 ngày |
| PUT | /ignore | region, resource_id, days; ngoại lệ 1–30 ngày |
| PUT | /keep | region, resource_id, enabled boolean; bật/tắt giữ lại nội bộ, trả kept boolean |
| PUT | /notifications | enabled boolean; email nhận lấy từ Cognito GetUser |

Frontend chủ động poll `/findings` để cập nhật toàn bộ region; `/scans/{scanId}` có sẵn để theo dõi từng job. SUCCEEDED chỉ có nghĩa các API trong phạm vi MVP hoàn tất; không khẳng định mọi tài nguyên account đều được kiểm tra.

## 7. Kiểm thử

Xem `VALIDATION.md` để phân biệt kiểm tra đã chạy và kiểm tra AWS còn thiếu.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe tests/ui_smoke.py
```

Nếu dùng SAM CLI: `sam validate --lint --region ap-southeast-1` rồi `sam build`. Dùng virtualenv riêng cho SAM nếu dependencies của SAM CLI xung đột với phiên bản test đã pin.

Sau deploy phải thử Cognito thật, sai ExternalId, role bị thu hồi, hai người dùng, EC2 metrics thật, EBS/EIP theo thời gian, snapshot/AMI, scheduler và SES. Chỉ đánh dấu kiểm thử cloud pass sau khi chạy và lưu bằng chứng thật.

## 8. Chi phí và dọn dẹp

Không giả định Free Tier bao phủ tất cả. Tài nguyên platform có thể phát sinh phí: Lambda, CloudWatch API/logs, DynamoDB, Cognito, S3, CloudFront, SQS, SES. Dùng AWS Pricing Calculator theo lượng sử dụng dự kiến và AWS Budget theo mức của bạn. Budget là cảnh báo, không phải giới hạn chi phí cứng.

Không cần tạo EC2/RDS/NAT chỉ để trình diễn MVP. Tận dụng tài nguyên lab có sẵn hoặc xem demo mẫu. EBS/EIP/snapshot thử cũng có thể phát sinh phí.

Để xóa: lấy đúng WebBucket trong Outputs và dọn **chỉ các file MVP** của bucket đó, rồi xóa stack `cloud-resource-guardian` trong CloudFormation. Xóa stack read role ở account đích để thu hồi truy cập. Artifact bucket `crg-artifacts-<account>-<region>` và Lambda log groups có thể cần dọn riêng sau khi kiểm tra. Xóa platform không xóa tài nguyên được quét. Không dọn bucket, stack hoặc resource khác của bạn.

## 9. Sơ đồ và tài liệu chính thức

`diagrams/cloud-resource-guardian.drawio` là bản sơ đồ tại ngày đóng gói, có bốn tab báo cáo và các tab chi tiết. Các hình báo cáo PNG nằm cùng thư mục. Hạ tầng MVP giữ cách gọi async đã vẽ; thêm failure destination SQS để vận hành lỗi.

- AWS CLI browser login: https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html
- API Gateway JWT: https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html
- STS ExternalId: https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_common-scenarios_third-party.html
- Lambda async error handling: https://docs.aws.amazon.com/lambda/latest/dg/invocation-async-configuring.html
- SAM EventInvokeConfig: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-property-function-eventinvokeconfiguration.html
- SES verified identities: https://docs.aws.amazon.com/ses/latest/dg/verify-addresses-and-domains.html
- Cognito access token scopes: https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html
