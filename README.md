# Cloud Resource Guardian — MVP

Cloud Resource Guardian giúp người dùng xem xét tài nguyên AWS có dấu hiệu ít sử dụng. Dự án gồm backend Python/boto3 chạy trên Lambda, dashboard HTML/CSS/JavaScript, hạ tầng AWS SAM và script triển khai.

Phạm vi evaluator nghiêm ngặt ban đầu gồm chín loại tài nguyên. Source hiện khai báo 38 loại tài nguyên, 39 rule và 40 trường ngưỡng; cả 38 loại có đường collector qua 12 nhóm dịch vụ có thể chọn. Những đường mở rộng chưa có cùng mức bằng chứng AWS và kiểm soát missing-data như chín loại lõi, vì vậy không được xem các số khai báo là số chức năng đã nghiệm thu production.

Hướng dẫn triển khai, chạy harness và khôi phục nằm trong [DEPLOYMENT.md](DEPLOYMENT.md). Demo và test local không xác nhận phiên bản đang chạy trên AWS hoặc kết quả nghiệm thu cloud. Trạng thái đối chiếu hiện tại nằm trong [báo cáo nghiệm thu cuối](docs/FINAL_ACCEPTANCE_AUDIT.md).

Báo cáo Search/Filter theo resource type, inventory identity mới và giới hạn dữ liệu nằm tại [docs/RESOURCE_FILTER_COVERAGE_AUDIT.md](docs/RESOURCE_FILTER_COVERAGE_AUDIT.md).

## 1. Thử ngay tại máy, không cần AWS

Cài Python 3.12 rồi mở PowerShell tại root repository, nơi có `demo.py`, `src/` và `web/`. Demo chỉ dùng thư viện chuẩn Python, không cần cài dependencies AWS:

```powershell
python demo.py
```

Mở **http://127.0.0.1:8080**, chọn **Mở dashboard demo**. Dữ liệu gắn nhãn DEMO là dữ liệu mẫu; chế độ này không dùng AWS SDK, không xác thực Cognito thật, không gửi email và không phát hiện tài nguyên thật. Dữ liệu demo nằm trong RAM, khởi động lại sẽ reset.

Có thể thử dashboard, tìm/lọc cảnh báo, cấu hình, đã xem/bỏ đã xem, giữ lại, bỏ qua 1–30 ngày, quét ngay và lịch sử. Các cờ độc lập và giữ qua refresh/scan tiếp; history không bị sửa theo feedback mới. Quét demo chạy trong khoảng ba giây; dashboard lấy kết quả mỗi năm giây khi còn lượt quét đang chạy. Demo không áp dụng cooldown 15 phút của AWS thật. Dừng bằng Ctrl+C.

Demo có EC2, EBS, Elastic IP, snapshot, S3 multipart, RDS, NAT Gateway, ALB và NLB thuộc bốn nhóm. Cấu hình mặc định có số đếm inventory mẫu tổng cộng 31, với 10 finding: 8 REVIEW, 1 OBSERVING và 1 INSUFFICIENT_DATA. Inventory/metrics là dữ liệu tổng hợp, được đánh giá bằng evaluator thuần hiện hành; đổi ngưỡng/cửa sổ có thể đổi finding và evidence ở scan tiếp theo. Không suy từ các số mẫu này sang tài nguyên hoặc chi phí AWS thật.

Demo lưu/lọc bốn nhóm và 11 cấu hình. First/last được cập nhật trước feedback, giữ qua lượt quét tiếp và tạm biến mất, hết hạn sau 30 ngày không quan sát; đổi kết nối reset registry cùng dữ liệu phiên. Thời gian quan sát EBS/EIP trong mẫu là dữ liệu tổng hợp riêng, không phải thời gian thật đã chờ trên AWS. Snapshot history giữ giá trị lúc quét. SES và control email mặc định tắt; demo từ chối bật email. [Kiểm tra tích hợp demo](tests/ui_integrated_demo.py) và các fixture riêng kiểm tra chín loại, mốc quan sát, feedback và phân trang.

## 2. Phạm vi AWS thật

| Tính năng | Cách thực hiện |
|---|---|
| Đăng ký, đăng nhập, đăng xuất | Cognito Hosted UI, Authorization Code + PKCE; UserPool hiện cho phép tự đăng ký và xác minh email; token chỉ lưu trong sessionStorage |
| Nhiều người dùng | API Gateway xác minh JWT; backend lấy userId từ claim `sub`, không lấy từ body. Mốc 5 user là giả định vận hành của scheduler hiện tại, không phải quota Cognito |
| Kết nối AWS | Một account/người dùng; STS AssumeRole, Role ARN và ExternalId riêng; chọn ít nhất một trong 12 nhóm dịch vụ |
| Quét tài nguyên | 38 loại có đường collector qua 12 nhóm có thể chọn; chín loại lõi có bộ bằng chứng nghiêm ngặt hơn. Analytics đã selectable nhưng chưa được xác minh bằng scan production trong thay đổi này |
| Quét ngay | POST `/scans` không có body, trả `scan_id`; Lambda backend Invoke async Lambda worker |
| Theo dõi tiến độ | Frontend lấy `/findings` mỗi năm giây khi còn QUEUED/RUNNING; dừng khi terminal hoặc lỗi |
| Quét định kỳ | EventBridge kích hoạt Lambda scheduler mỗi giờ, chọn profile đến hạn |
| Lưu kết quả | DynamoDB theo tenant; lịch sử 30 ngày. Scan mới có thể lưu inventory identity theo page riêng ngoài RESULT, còn scan legacy chỉ có aggregate count |
| Phản hồi & Ngoại lệ | Tag `guardian:keep=true` cho EC2/EBS/EIP/snapshot/RDS/NAT; API `/feedback` cho cả chín loại (acknowledged, kept, ignoreUntil tối đa 30 ngày); handler `/keep` và `/ignore` tương thích ngược chỉ dùng nội bộ |
| Email tùy chọn | SES mặc định tắt; khi bật, gửi tới email Cognito đã xác minh nếu tập REVIEW đang hiện không rỗng, thay đổi và đã qua cooldown |
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

`aws login` mở trình duyệt để bạn tự đăng nhập. IAM identity cần `SignInLocalDevelopmentAccess` cho cách đăng nhập này; quyền đăng nhập không thay thế quyền triển khai. Nếu account dùng IAM Identity Center, dùng `aws configure sso --profile guardian-lab` rồi `aws sso login --profile guardian-lab` theo [hướng dẫn AWS](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html). Xác nhận cách truy cập với người quản lý account trước khi chọn luồng đăng nhập.

Không gửi access key, secret, session token, mật khẩu hoặc mã MFA vào chat. Đăng nhập tại máy không tự chia sẻ phiên AWS với ChatGPT.

### 3.2. Cài dependencies triển khai

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-deploy.txt
```

`python` phải là Python 3.12; nếu máy có nhiều bản, dùng đúng executable 3.12 hoặc `py -3.12` khi đã đăng ký với Python Launcher để tạo venv. Nếu `.venv` đã tồn tại, kiểm tra `.\.venv\Scripts\python.exe --version` rồi dùng lại môi trường phù hợp. Nếu báo `No module named pip`, chạy `.\.venv\Scripts\python.exe -m ensurepip --upgrade` trước khi cài dependencies. Trong Linux/macOS, dùng `.venv/bin/python` thay `.\.venv\Scripts\python.exe`.

### 3.3. Chuẩn bị artifact và change set để review

Đọc [release gate và bước đóng gói offline](DEPLOYMENT.md#manual-release-gate); hoàn tất kiểm tra local, review source/template, commit revision và pin ZIP trước khi tạo change set. Ví dụ dưới dùng stack nghiệm thu riêng; chỉ chạy sau khi đã xác nhận account/region và quyền triển khai:

```powershell
.\.venv\Scripts\python.exe deploy.py `
  --profile guardian-lab --region ap-southeast-1 `
  --stack cloud-resource-guardian-task8-test `
  --domain-prefix crg-task8-CHUOI-RIENG `
  --artifact .preflight/task8-artifacts/task8-final.zip --plan
```

Thay `CHUOI-RIENG` bằng chữ thường/số để domain Cognito không trùng toàn vùng. `--plan` vẫn tạo/cấu hình artifact bucket, upload ZIP và tạo change set; đây là thao tác ghi AWS. Reviewer kiểm tra change set thực tế, IAM và tác động dữ liệu trước khi executor thực thi. `deploy.py` mặc định dùng stack `cloud-resource-guardian`, vì vậy luôn truyền rõ `--stack` đúng phạm vi.

### 3.4. Thực thi change set đã review và xuất bản web

Executor dùng đúng lệnh `execute-change-set` mà script in ra cho change set đã duyệt, rồi chờ stack đạt `CREATE_COMPLETE`/`UPDATE_COMPLETE`. Upload `web/target-role.yaml` vào WebBucket của stack trước theo [hướng dẫn triển khai](DEPLOYMENT.md#artifact-và-xuất-bản-web), rồi xuất bản web vào cùng stack:

```powershell
.\.venv\Scripts\python.exe publish.py --profile guardian-lab --region ap-southeast-1 --stack cloud-resource-guardian-task8-test
```

Script upload ba file frontend và `config.json`, rồi tạo CloudFront invalidation bao phủ cả template đã upload. Kiểm tra đủ năm object, config thật và invalidation hoàn tất.

Người dùng có thể đăng ký trên web, xác minh email rồi đăng nhập. Nếu môi trường nghiệm thu muốn giới hạn tài khoản, quản trị viên phải áp dụng quy trình phê duyệt riêng; template hiện không tắt tự đăng ký. Không mô tả môi trường hiện tại là admin-only.

Hạ tầng chính: private S3 + CloudFront → Cognito / API Gateway → Lambda backend / scheduler / worker → DynamoDB; worker dùng STS và AWS SDK đọc account người dùng. SQS `DeadLetters` nhận OnFailure worker và có recovery consumer; `OperationsDeadLetters` nhận redrive và lỗi vận hành của scheduler/reconciler/delivery.

Template không đặt ReservedConcurrentExecutions; năm Lambda dùng chung concurrency của account. Xác minh quota thực tế trước khi thay đổi concurrency, không lấy số quota từ lần triển khai cũ. Lease theo tenant, cooldown và API throttling vẫn được giữ. Khi stack lỗi, xem CloudFormation Events trước khi thử lại. Chạy `deploy.py` không có `--plan` sẽ tự execute và publish; luồng nghiệm thu ở đây dùng change set đã review.

### 3.5. Bật email (tùy chọn)

Thêm `--sender-email email-cua-ban@example.com` vào lệnh deploy. CloudFormation tạo SES EmailIdentity; mở thư xác minh được AWS gửi tới địa chỉ đó. Nếu SES đang trong sandbox, địa chỉ người nhận cũng phải được xác minh tại SES **ap-southeast-1**. Địa chỉ nhận của ứng dụng lấy từ email Cognito đã xác minh; người dùng không nhập tùy ý người nhận.

Trên web, mở Cấu hình & cảnh báo → bật email. Digest gửi sau lượt quét nếu tập REVIEW đang hiển thị không rỗng, thay đổi fingerprint và đã qua cooldown, theo region và địa chỉ Cognito đã xác minh. Khi toàn bộ REVIEW biến mất, ứng dụng cập nhật dedup nhưng không gửi thư báo hết finding. Lịch gửi đi cùng lịch quét, không thêm scheduler riêng. Conditional write giữ quyền gửi cho một worker; cooldown bằng `interval_hours`. Dedup theo loại tài nguyên, resource ID và rule, không theo dao động CPU; đổi kết nối hoặc người nhận không dùng lại dấu gửi cũ.

Thông báo lưu trạng thái, thời điểm, fingerprint và SES `message_id` trong bản ghi `NOTICE#...`. `SENT` chỉ có nghĩa SES nhận yêu cầu, không chứng minh email đã vào hộp thư. `FAILED` là lỗi SES rõ ràng; `UNKNOWN` là chưa biết SES đã nhận hay chưa; `STATE_FAILED` là lỗi trạng thái trước khi gọi SES; `SENT_UNRECORDED` là SES đã nhận nhưng chưa ghi được kết quả vào DynamoDB. Kết quả quét vẫn được giữ. Cooldown áp dụng cả lỗi/không rõ kết quả; lần quét sau đủ hạn mới thử lại. Không bảo đảm exactly-once vì SES và DynamoDB không có giao dịch chung; kiểm tra log và NOTICE trước khi gửi lại thủ công.

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
- Với chín loại lõi, metric bắt buộc phải có ít nhất `ceil(window_hours × 0.8)` mẫu giờ hợp lệ. Sample 0 thật được tính; thiếu mẫu, số âm, boolean, kiểu sai, NaN/infinity hoặc phép tính overflow tạo `INSUFFICIENT_DATA`. Tài nguyên thiếu thời điểm tạo hoặc chưa tồn tại đủ cửa sổ cũng có trạng thái này. Evidence giữ ngưỡng, đơn vị, số mẫu nhận/hợp lệ/lỗi và nguyên nhân; dữ liệu thiếu/lỗi không được thay bằng 0 hoặc dùng để kết luận ít hoạt động. Các evaluator metric mở rộng cũng không còn biến chuỗi rỗng thành zero; chúng trả `INSUFFICIENT_DATA`, nhưng chưa có AWS E2E đồng đều cho cả 38 loại.
- Collector lọc timestamp theo `[observation_start, observation_end)`, yêu cầu đúng lưới giờ và khử trùng điểm cùng timestamp. Phản hồi CloudWatch sai cấu trúc, timestamp xung đột hoặc phân trang lỗi làm scan `PARTIAL`, không sinh kết luận ít hoạt động từ chuỗi lỗi.
- Backend cho chọn 12 nhóm: `compute`, `storage`, `database`, `network`, `serverless`, `monitoring`, `security`, `backup`, `nosql`, `containers`, `integration`, `analytics`. Profile cũ vẫn mặc định bốn nhóm lõi.
- Chỉ đọc region đã chọn. Mỗi loại tối đa 100 tài nguyên/region, kết quả hiển thị tối đa 50 findings/region. Worker giữ tối đa 100 ứng viên nội bộ và giới hạn RESULT ở 300 KiB; phải cắt dữ liệu thì báo `PARTIAL`. `finding_count` có thể là cận dưới khi nhóm ứng viên bị cắt. Scan mới ghi danh tính inventory theo page DynamoDB riêng, tenant/connection/scan/region/type/run-token scoped, TTL 30 ngày; scan legacy vẫn chỉ có aggregate counts và UI không tạo Resource ID giả. Worker timeout 300 giây; collector dừng khi còn dưới 60 giây và persistence chừa tối thiểu 10 giây cho finalization.
- Một account/người dùng, tối đa ba region. Mọi PUT `/connection` tạo connection version mới; result, observation và feedback cũ không áp dụng cho kết nối mới.
- Quét thủ công tối thiểu 15 phút/lần. Job có deadline 15 phút; API hiển thị TIMED_OUT khi quá hạn và reconciler lưu trạng thái/history ở lượt đối soát kế tiếp khi hạ tầng hoạt động bình thường. Admission, connection version và run token ngăn job trùng/cũ ghi đè kết quả mới. Không đủ 60 giây trước STS thì worker kết thúc TIMED_OUT; hết budget trong collector tạo PARTIAL với dữ liệu hợp lệ đã có.
- Scheduler scan bảng DynamoDB mỗi giờ, phù hợp tối đa 5 user nội bộ. Khi tăng quy mô cần GSI theo due time, quota tenant và chia lô.

Xem [RULES.md](RULES.md) cho danh mục rule, cấu trúc bằng chứng, hợp đồng collector và API giữ lại nội bộ. Finding bổ sung `rule_id` và `recommendation`; dashboard hỗ trợ đã xem, giữ lại và bỏ qua qua API `/feedback`.

Chín loại lõi có hợp đồng metric/evidence và bằng chứng local sâu hơn. Source mở rộng lên 38 loại/39 rule/40 trường ngưỡng và 12 nhóm selectable. `ECR_IMAGE_OLD` nay đọc `DescribeImages.imagePushedAt`; DocumentDB và Neptune dùng client riêng; CloudFront chỉ được một region xác định thu thập. Target role cần thêm `ecr:DescribeImages`; DocumentDB và Neptune tiếp tục dùng quyền IAM `rds:DescribeDBClusters` đã có vì AWS management API của hai dịch vụ dùng prefix `rds:`. Route CloudFormation `/inventory` đã được khai báo trong source release nhưng chưa được deploy, và chưa có scan production mới cho phạm vi mở rộng. Không dùng các số 38/39/40 để tuyên bố đã nghiệm thu AWS.

## 6. API contract

Tất cả API yêu cầu Cognito access token trong `Authorization: Bearer ...`. API Gateway xác minh JWT, Lambda kiểm tra `token_use=access`. Tenant luôn lấy từ `sub`.

| Method | Route | Nội dung |
|---|---|---|
| GET | /me | Profile allowlist, complete settings, service groups, IAM principals và khả năng gửi email |
| PUT | /connection | `role_arn`, `regions`, optional `service_groups`; STS xác minh account và rotate connection version |
| PUT | /settings | Partial update cho 40 trường ngưỡng đã khai báo; merge với setting hiện tại và kiểm tra min/max/type. Mười một trường thuộc bộ rule lõi ban đầu |
| POST | /scans | Body rỗng; 202 + scan_id, 409 nếu đang chạy, 429 nếu chưa đủ 15 phút |
| GET | /scans/{scanId} | Trạng thái/kết quả retained của scan thuộc tenant và kết nối hiện tại |
| GET | /findings | Kết quả hiện tại đã overlay feedback; kept/ignore active bị ẩn, acknowledged vẫn hiện; bỏ keep/ignore khôi phục ứng viên còn được lưu |
| GET | /inventory | Source API cho inventory identity của một `scan_id`, limit 1–500, cursor tenant/filter-bound và filter type/service/region/q; trả `available`, `aggregate_only`, `complete`. `template.yaml` chưa xuất bản route này nên deployment hiện tại vẫn fallback aggregate cho đến khi change set được duyệt |
| GET | /history | Snapshot bất biến; `limit` 1–100, mặc định 20; `next_token` tenant-bound |
| GET | /feedback | Feedback của kết nối hiện tại; `limit`/`next_token` như history |
| PUT | /feedback | `region`, `finding_id` và subset `acknowledged`/`kept`/`ignoreUntil`; thời hạn UTC kết thúc bằng `Z`, null để xóa; clear cũng dùng PUT |
| PUT | /notifications | Chỉ `enabled` boolean; email nhận lấy từ Cognito GetUser |
| PUT | /keep | Handler nội bộ tương thích ngược: `region`, `resource_id`, `enabled` boolean; template hiện không xuất bản route |
| PUT | /ignore | Handler nội bộ tương thích ngược: `region`, `resource_id`, `days` 1–30; template hiện không xuất bản route |

Frontend poll `/findings` khi có QUEUED/RUNNING, tối đa 185 lượt; khi terminal hoặc lỗi thì dừng. `/scans/{scanId}` trả chi tiết một job, được UI dùng để mở lịch sử nhiều region. `finding_id` là SHA-256 deterministic của type/region/stable identity và là khóa feedback; `resource_id` chỉ để hiển thị. Route/method sai trả 404/405 trước khi tạo profile. Mỗi body tối đa 10 KiB. `SUCCEEDED` chỉ có nghĩa các API trong phạm vi đã chọn hoàn tất.
Trang `Tài nguyên cần kiểm tra` giữ ngữ cảnh lượt quét trong một thanh tóm tắt; Scan ID, trigger và lỗi dịch vụ chỉ xuất hiện trong panel chi tiết. Scope inventory tải hết cursor `/inventory` cho scan mới và tìm theo ID, tên, service, type, region, account, scan ID/thời gian; khi API/scan legacy chỉ có count, UI ghi rõ aggregate-only. Chế độ `Tìm trong lịch sử` phân trang `/history` đến hết dữ liệu retained và tìm **findings lịch sử**, lọc theo thời gian hoàn tất bằng `Asia/Ho_Chi_Minh`; lịch sử cũ không được giả là có inventory identities. Giới hạn retained là 30 ngày. Chi tiết finding mở trong side panel trên desktop, full-screen trên mobile; quản lý keep/ignore nằm ở tab `Đã giữ & bỏ qua`.

Worker giữ ứng viên bị `/feedback` che trong kết quả nội bộ, nên bỏ keep hoặc ignore hết hạn có thể làm chúng hiện lại mà không cần quét mới, kể cả sau lượt quét tiếp theo. Khả năng khôi phục giới hạn trong ứng viên được giữ; dữ liệu cũ chưa lưu ứng viên cần một lượt quét mới. API không xuất trường `candidates`. `/history` và `/scans/{scanId}` giữ snapshot lúc quét; phản hồi mới chỉ overlay `/findings`, không sửa lịch sử. Handler `/keep` và `/ignore` cũ dùng resource ID và chỉ tác động lượt quét sau; đây là cơ chế độc lập với `/feedback`.

## 7. Kiểm thử

Các lệnh dưới đây kiểm tra local, cần Python 3.12; Node.js cho kiểm tra JavaScript và Git cho kiểm tra diff. Tạo `.venv` nếu chưa có, hoặc dùng lại môi trường Python 3.12 phù hợp. Nếu thiếu pip, xem mục 3.2. Đặt `CRG_AWS_E2E=0` trong phiên này để discover không bật API thật từ biến môi trường được kế thừa. Điều kiện và cách chạy AWS E2E nằm trong [DEPLOYMENT.md](DEPLOYMENT.md#manual-release-gate).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:CRG_AWS_E2E = '0'
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m playwright install chromium
$env:UI_QA_DIR = Join-Path (Get-Location) '.preflight\ui-qa'
.\.venv\Scripts\python.exe tests/ui_smoke.py
node --check web/app.js
.\.venv\Scripts\cfn-lint.exe template.yaml target-role.yaml web/target-role.yaml
git diff --check
```

Smoke tự khởi động demo riêng; không cần giữ server demo khác. Có thể dùng Chrome đã cài bằng cách đặt `CHROMIUM_EXECUTABLE` tới executable đã xác minh thay cho tải Chromium. Chọn regression theo thay đổi: `tests/ui_scope_filters.py`, `tests/ui_finding_details.py`, `tests/ui_finding_feedback.py`, `tests/ui_feedback_management.py`, `tests/ui_history_management.py`; `tests/ui_redesign.py` kiểm tra các trạng thái và `tests/ui_integrated_demo.py` kiểm tra tích hợp demo HTTP. Chạy từng script bằng Python trong `.venv`. Các suite này là local/demo/fixture.

Nếu dùng SAM CLI: `sam validate --lint --region ap-southeast-1` rồi `sam build`. Dùng virtualenv riêng cho SAM nếu dependencies của SAM CLI xung đột với phiên bản test đã pin.

Trước execute, reviewer và executor phải là hai người khác nhau; reviewer rà tác động UserPool và trạng thái tự đăng ký, số user phù hợp với giới hạn vận hành scheduler, cùng allowlist chỉ đọc. Sau deploy, executor chạy AWS E2E riêng theo [DEPLOYMENT.md](DEPLOYMENT.md#aws-e2e-cho-rule-và-web); suite này đổi connection version, nên bằng chứng EBS/EIP đủ thời gian phải lấy bằng scan tiếp trên cùng kết nối. EC2/EBS/EIP/Snapshot/S3 multipart cần evidence thật; RDS/NAT/ALB/NLB chỉ được SKIPPED với `RESOURCE_NOT_AVAILABLE` hoặc `COST_NOT_APPROVED`. SES không là release gate.

## 8. Chi phí và dọn dẹp

Không giả định Free Tier bao phủ tất cả. Tài nguyên platform có thể phát sinh phí: Lambda, CloudWatch API/logs, DynamoDB, Cognito, S3, CloudFront, SQS, SES. Dùng AWS Pricing Calculator theo lượng sử dụng dự kiến và AWS Budget theo mức của bạn. Budget là cảnh báo, không phải giới hạn chi phí cứng.

Không cần tạo EC2/RDS/NAT chỉ để trình diễn MVP. Tận dụng tài nguyên lab có sẵn hoặc xem demo mẫu. EBS/EIP/snapshot thử cũng có thể phát sinh phí.

Khi được yêu cầu dọn môi trường, xác nhận đúng account/region/tên stack đã triển khai, lấy WebBucket từ Outputs và dọn **chỉ các file MVP** thuộc stack đó trước khi xóa chính stack đã xác nhận trong CloudFormation. Không mặc định tên stack vì môi trường thử dùng tên riêng. Xóa đúng stack read role ở account đích để thu hồi truy cập. Artifact bucket `crg-artifacts-<account>-<region>` có thể dùng chung nhiều stack; chỉ dọn artifact liên quan và kiểm tra log groups còn lại trước khi xử lý riêng. Xóa platform không xóa tài nguyên được quét.

## 9. Sơ đồ và tài liệu chính thức

`diagrams/cloud-resource-guardian.drawio` là bản sơ đồ tại ngày đóng gói, có bốn tab báo cáo và các tab chi tiết. Các hình báo cáo PNG nằm cùng thư mục. Hạ tầng MVP giữ cách gọi async đã vẽ; thêm failure destination SQS để vận hành lỗi.

- AWS CLI browser login: https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html
- API Gateway JWT: https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html
- STS ExternalId: https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_common-scenarios_third-party.html
- Lambda async error handling: https://docs.aws.amazon.com/lambda/latest/dg/invocation-async-configuring.html
- SAM EventInvokeConfig: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-property-function-eventinvokeconfiguration.html
- SES verified identities: https://docs.aws.amazon.com/ses/latest/dg/verify-addresses-and-domains.html
- Cognito access token scopes: https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html
