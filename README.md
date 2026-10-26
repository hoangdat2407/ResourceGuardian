# Cloud Resource Guardian — MVP

Bản MVP của Cloud-T9, triển khai trên AWS bằng Python/boto3 và Lambda. Gồm mã nguồn frontend, backend, hạ tầng AWS SAM và script triển khai. Lịch sử triển khai được ghi trong [DEPLOYMENT.md](DEPLOYMENT.md) và [HANDOFF.md](HANDOFF.md); cần xác minh revision đang chạy và bằng chứng AWS trước khi nghiệm thu bản thay đổi hiện tại.

Task 8 bổ sung admission/lease bằng giao dịch, RESULT + HISTORY nguyên tử, consumer phục hồi failure queue và đối soát job quá hạn mỗi 5 phút. Xem [hợp đồng và runbook Task 8](TASK8.md), [harness AWS opt-in](TASK8-AWS.md) và [kết quả validation](VALIDATION.md). Phần AWS của thay đổi này chưa được nghiệm thu; dữ liệu triển khai cũ bên dưới không xác nhận revision Task 8.

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
| Đăng nhập, đăng xuất | Cognito Hosted UI, Authorization Code + PKCE; chỉ admin tạo user; token chỉ lưu trong sessionStorage |
| Nhiều người dùng | Tối đa 5 user nội bộ theo release gate; API Gateway xác minh JWT; backend lấy userId từ claim `sub`, không lấy từ body |
| Kết nối AWS | Một account/người dùng; STS AssumeRole, Role ARN và ExternalId riêng; chọn 1–4 nhóm dịch vụ |
| Quét tài nguyên | EC2; EBS/Snapshot/S3 multipart; RDS; EIP/NAT Gateway/ALB/NLB; tối đa ba region/người dùng |
| Quét ngay | POST `/scans` không có body, trả `scan_id`; Lambda backend Invoke async Lambda worker |
| Theo dõi tiến độ | API trạng thái và frontend tự lấy kết quả mỗi năm giây |
| Quét định kỳ | EventBridge kích hoạt Lambda scheduler mỗi giờ, chọn profile đến hạn |
| Lưu kết quả | DynamoDB theo tenant; lịch sử 30 ngày, phân trang 20 lần quét region mặc định |
| Phản hồi & Ngoại lệ | Tag `guardian:keep=true` cho EC2/EBS/EIP/snapshot/RDS/NAT; API `/feedback` cho cả chín loại (acknowledged, kept, ignoreUntil tối đa 30 ngày); handler `/keep` và `/ignore` tương thích ngược chỉ dùng nội bộ |
| Email tùy chọn | SES mặc định tắt; khi được cấu hình, gửi tới email Cognito đã xác minh nếu danh sách REVIEW thay đổi |
| Xử lý lỗi | PARTIAL khi một phần API lỗi/đạt giới hạn/hết time budget; async retry → SQS failure destination → recovery; đối soát TIMED_OUT mỗi 5 phút; DLQ vận hành |

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
- **Snapshot:** tuổi >=ngưỡng, trạng thái completed, không có tag giữ lại và không tham chiếu bởi các AMI đã đọc (bao gồm AMI bị vô hiệu hóa); bỏ qua dấu hiệu AWS Backup. Nếu danh sách AMI bị cắt, báo PARTIAL với INVENTORY_TRUNCATED, không đánh dấu snapshot là không được tham chiếu.
- **S3 multipart:** cảnh báo upload chưa hoàn tất có tuổi **lớn hơn** 7 ngày. Scanner không gọi ListParts/Complete/Abort và không suy diễn dung lượng hay chi phí.
- **RDS:** instance available và đủ tuổi cửa sổ; CPUUtilization p95 và DatabaseConnections p95 đều dưới ngưỡng. Dùng hourly Maximum.
- **NAT Gateway:** gateway available và đủ tuổi; tính trung bình hourly Sum riêng cho BytesInFromSource và BytesInFromDestination theo số mẫu thực đo của từng chiều, cộng rồi đổi thành MiB/giờ để so ngưỡng.
- **ALB/NLB:** load balancer active và đủ tuổi; ALB dùng RequestCount/Sum, NLB dùng NewFlowCount/Sum. Scanner không gọi DescribeTags.
- Mọi metric bắt buộc phải có ít nhất `ceil(window_hours × 0.8)` mẫu giờ hợp lệ. Sample 0 thật được tính; thiếu mẫu, số âm, boolean, kiểu sai, NaN/infinity hoặc phép tính overflow tạo `INSUFFICIENT_DATA`. Tài nguyên thiếu thời điểm tạo hoặc chưa tồn tại đủ cửa sổ cũng có trạng thái này. Evidence giữ ngưỡng, đơn vị, số mẫu nhận/hợp lệ/lỗi và nguyên nhân; dữ liệu thiếu/lỗi không được thay bằng 0 hoặc dùng để kết luận ít hoạt động.
- Collector lọc timestamp theo `[observation_start, observation_end)`, yêu cầu đúng lưới giờ và khử trùng điểm cùng timestamp. Phản hồi CloudWatch sai cấu trúc, timestamp xung đột hoặc phân trang lỗi làm scan `PARTIAL`, không sinh kết luận ít hoạt động từ chuỗi lỗi.
- Bốn nhóm dịch vụ: `compute` (EC2), `storage` (EBS/Snapshot/S3 multipart), `database` (RDS), `network` (EIP/NAT/ALB/NLB). Profile cũ mặc định bật đủ bốn nhóm.
- Chỉ đọc region đã chọn. Mỗi loại tối đa 100 tài nguyên/region, kết quả hiển thị tối đa 50 findings/region. Worker giữ tối đa 100 ứng viên nội bộ và giới hạn kết quả lưu ở 300 KiB; phải cắt dữ liệu thì báo `PARTIAL`. `finding_count` có thể là cận dưới khi nhóm ứng viên bị cắt; `total_candidate_count` ghi số ứng viên trước khi cắt. Worker time budget 300 giây và dừng AWS reads trước 30 giây còn lại.
- Một account/người dùng, tối đa ba region. Mọi PUT `/connection` tạo connection version mới; result, observation và feedback cũ không áp dụng cho kết nối mới.
- Quét thủ công tối thiểu 15 phút/lần. Job có deadline 15 phút; API hiển thị TIMED_OUT khi quá hạn và reconciler lưu trạng thái/history ở lượt đối soát kế tiếp khi hạ tầng hoạt động bình thường. Admission, connection version và run token ngăn job trùng/cũ ghi đè kết quả mới. Không đủ 60 giây trước STS thì worker kết thúc TIMED_OUT; hết budget trong collector tạo PARTIAL với dữ liệu hợp lệ đã có.
- Scheduler scan bảng DynamoDB mỗi giờ, phù hợp tối đa 5 user nội bộ. Khi tăng quy mô cần GSI theo due time, quota tenant và chia lô.

Xem [RULES.md](RULES.md) cho danh mục rule, cấu trúc bằng chứng, hợp đồng collector và API giữ lại nội bộ. Finding bổ sung `rule_id` và `recommendation`, giữ các trường cũ cho frontend hiện tại. Nút giữ lại trên dashboard thuộc mục 9, chưa bổ sung ở mục 7.

Phạm vi Task 7 được chốt cho chín loại trên. Báo cáo còn nêu các dịch vụ khác trong bốn nhóm, hai nhóm AI/analytics và giám sát/tích hợp, cùng dữ liệu billing/cost; cần đầu vào collector của Task 6 và bộ rule tương ứng trước khi nghiệm thu các phần này. Hoàn thiện hiển thị/thao tác dashboard thuộc Task 9; kiểm thử local chưa chứng minh đã chạy trên AWS thật.

## 6. API contract

Tất cả API yêu cầu Cognito access token trong `Authorization: Bearer ...`. API Gateway xác minh JWT, Lambda kiểm tra `token_use=access`. Tenant luôn lấy từ `sub`.

| Method | Route | Nội dung |
|---|---|---|
| GET | /me | Profile allowlist, complete settings, service groups, IAM principals và khả năng gửi email |
| PUT | /connection | `role_arn`, `regions`, optional `service_groups`; STS xác minh account và rotate connection version |
| PUT | /settings | Partial update cho 11 ngưỡng số; merge với setting hiện tại và kiểm tra min/max/type |
| POST | /scans | Body rỗng; 202 + scan_id, 409 nếu đang chạy, 429 nếu chưa đủ 15 phút |
| GET | /scans/{scanId} | Trạng thái/kết quả retained của scan thuộc tenant và kết nối hiện tại |
| GET | /findings | Kết quả hiện tại đã overlay feedback; kept/ignore active bị ẩn, acknowledged vẫn hiện; bỏ keep/ignore khôi phục ứng viên còn được lưu |
| GET | /history | Snapshot bất biến; `limit` 1–100, mặc định 20; `next_token` tenant-bound |
| GET | /feedback | Feedback của kết nối hiện tại; `limit`/`next_token` như history |
| PUT | /feedback | `region`, `finding_id` và subset `acknowledged`/`kept`/`ignoreUntil`; clear cũng dùng PUT |
| PUT | /notifications | Chỉ `enabled` boolean; email nhận lấy từ Cognito GetUser |
| PUT | /keep | Handler nội bộ tương thích ngược: `region`, `resource_id`, `enabled` boolean; template hiện không xuất bản route |
| PUT | /ignore | Handler nội bộ tương thích ngược: `region`, `resource_id`, `days` 1–30; template hiện không xuất bản route |

Frontend poll `/findings` để cập nhật toàn bộ region; `/scans/{scanId}` theo dõi một job. `finding_id` là SHA-256 deterministic của type/region/stable identity và là khóa feedback; `resource_id` chỉ để hiển thị. Route/method sai trả 404/405 trước khi tạo profile. Mỗi body tối đa 10 KiB. `SUCCEEDED` chỉ có nghĩa các API trong phạm vi đã chọn hoàn tất.

Worker giữ ứng viên bị `/feedback` che trong kết quả nội bộ, nên bỏ keep hoặc ignore hết hạn có thể làm chúng hiện lại mà không cần quét mới, kể cả sau lượt quét tiếp theo. Khả năng khôi phục giới hạn trong ứng viên được giữ; dữ liệu cũ chưa lưu ứng viên cần một lượt quét mới. API không xuất trường `candidates`. `/history` và `/scans/{scanId}` giữ snapshot lúc quét; phản hồi mới chỉ overlay `/findings`, không sửa lịch sử. Handler `/keep` và `/ignore` cũ dùng resource ID và chỉ tác động lượt quét sau; đây là cơ chế độc lập với `/feedback`.

## 7. Kiểm thử

Xem `VALIDATION.md` để phân biệt kiểm tra đã chạy và kiểm tra AWS còn thiếu.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe tests/ui_smoke.py
```

Nếu dùng SAM CLI: `sam validate --lint --region ap-southeast-1` rồi `sam build`. Dùng virtualenv riêng cho SAM nếu dependencies của SAM CLI xung đột với phiên bản test đã pin.

Sau deploy, reviewer và executor phải là hai người khác nhau. Reviewer xác nhận change set không replace UserPool, Cognito chỉ admin tạo user, `ListUsers` không quá 5 user và target role đúng allowlist chỉ đọc. Executor chạy `CRG_AWS_E2E=1 ... test_aws_e2e.py` với hai token và manifest đã sanitize. EC2/EBS/EIP/Snapshot/S3 multipart cần evidence thật; RDS/NAT/ALB/NLB chỉ được SKIPPED với `RESOURCE_NOT_AVAILABLE` hoặc `COST_NOT_APPROVED`. SES không là release gate.

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
