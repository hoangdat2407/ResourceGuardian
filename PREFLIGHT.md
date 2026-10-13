# Cloud Resource Guardian — kiểm tra trước triển khai

Ngày: 2026-10-11. Đích: account `376129867108`, region `ap-southeast-1`, stack `cloud-resource-guardian`.

## Trạng thái

Chỉ kiểm tra cục bộ và đọc AWS qua AWS MCP. Không gọi AWS CLI, không chạy/import deploy.py hoặc publish.py, không tạo change set, không upload, không tạo/sửa/xóa tài nguyên AWS. Đã compile các script mà không thực thi chúng. Chưa sửa mã ứng dụng hoặc template.

STS GetCallerIdentity thành công: `arn:aws:iam::376129867108:user/datht`, account khớp đích. Các API đọc đều được kiểm tra qua danh sách `api_calls` của MCP.

## Kết quả kiểm tra

| Kiểm tra | Kết quả trong phiên này |
|---|---|
| Đọc nguồn | README.md, VALIDATION.md, template.yaml, target-role.yaml, backend, frontend, demo, deployment/publish scripts và tests |
| Backend | 26/26 unittest pass; Moto/mock, không phải AWS integration |
| UI | tests/ui_smoke.py pass trên Chrome cục bộ: dashboard, lọc/tìm, ignore, cấu hình, email demo, region limit, polling, history, mobile, token hết hạn |
| Python/JavaScript | compileall và node --check pass |
| Dependencies | pip check pass trong .venv-preflight |
| Template cục bộ | cfn-lint 1.57.2: 0 lỗi, 0 cảnh báo cho cả hai template tại ap-southeast-1 |
| Template AWS | CloudFormation ValidateTemplate qua MCP thành công cho cả hai template; không chứng minh provisioning/quota/runtime pass |
| Lambda package | Python 3.12, manylinux2014_x86_64; 2.202 file, ZIP CRC pass, handler/dependencies đúng root, không có DLL/PYD Windows |
| Kích thước | ZIP 16.656.699 byte; giải nén 22.901.609 byte; nằm dưới giới hạn account trả về |
| SHA-256 ZIP | a5cae9d7368234308e4ef7078cd3ad0e79b2c208739cff84843c0c7f744c2db5 |
| SAM build | Không chạy; đã kiểm tra cách đóng gói pip/ZIP tương đương script dự án |
| cfn-guard | Chưa chạy: không có executable, guardpycfn hoặc bộ rules của dự án; chưa chứng nhận compliance tự động |

Lượt unittest đầu chạy khi pip còn cài đặt nên lỗi import boto3. Sau khi pip hoàn tất, chạy lại toàn bộ và 26/26 pass. Không thay test để đạt kết quả.

Artifact cục bộ: `.preflight/lambda.zip`, `.preflight/package_local.py`, `.preflight/lambda-package/`, `.preflight/ui/desktop.png`, `.preflight/ui/mobile.png`, `.venv-preflight/` và Python bytecode cache. Không có credentials trong báo cáo.

## Khảo sát tài nguyên và quyền

- CloudFormation DescribeStacks: không có stack tại ap-southeast-1.
- S3 ListBuckets: không có bucket trong account; HeadBucket tên `crg-artifacts-376129867108-ap-southeast-1` trả 404. Đây không phải giữ chỗ tên bucket toàn cầu.
- CloudFront: không có distribution hoặc OAC được trả về.
- Lambda: 0 function. DynamoDB, SQS, API Gateway v2, Cognito user pools, EventBridge rules và log groups `/aws/lambda/`: không có tài nguyên được trả về tại region đích.
- Cognito DescribeUserPoolDomain: prefix `crg-376129867108-ap-southeast-1` chưa có DomainDescription; cần kiểm tra lại lúc tạo.
- IAM có 4 role sẵn: ba service-linked roles ResourceExplorer/Support/TrustedAdvisor và `EC2StopInstancesPolicy`. Không có GuardianReadRole; giữ nguyên các role sẵn có.
- EC2 instances, volumes, addresses, snapshots sở hữu bởi account và AMIs sở hữu bởi account đều rỗng tại region đích. Không suy rộng kết luận sang region khác.
- Identity có AdministratorAccess, không thấy permissions boundary ở GetUser; không có inline policies/groups. Đọc nội dung policy xác nhận Allow *.
- SimulatePrincipalPolicy cho 14 thao tác tiêu biểu CloudFormation/S3/IAM/Lambda/CloudFront/Cognito/DynamoDB/SQS/EventBridge/Logs/API Gateway trả allowed. Đây là bằng chứng IAM mô phỏng, không bảo đảm toàn bộ quyền hiệu lực, SCP, resource policy hoặc kiểm soát ghi của MCP.
- DescribeTrails không trả trail: chưa chứng minh có lưu audit dài hạn; không tạo trail trong phiên này.

## Điểm chặn triển khai nguyên trạng

GetAccountSettings và Service Quotas đều xác nhận concurrency Lambda bằng **10**. `template.yaml:190` đặt `ReservedConcurrentExecutions: 3`. Theo AWS, reserved concurrency phải để lại 100 cho unreserved pool. Vì vậy không nên triển khai nguyên trạng với quota hiện tại.

Phương án đề xuất cho lab, chỉ thực hiện sau duyệt: bỏ thuộc tính ReservedConcurrentExecutions của WorkerFunction. Ba Lambda dùng chung quota account 10; worker không còn giới hạn riêng 3, có thể cạnh tranh concurrency với API/scheduler. Giữ lease, cooldown và throttling hiện có; chỉ kết nối một tenant/một region lúc smoke test.

Phương án thay thế: xin tăng quota lên ít nhất 103, chờ AWS chấp thuận rồi giữ giới hạn worker 3. Chưa gửi yêu cầu tăng quota.

Tham khảo: https://docs.aws.amazon.com/lambda/latest/dg/configuration-concurrency.html

Các giới hạn cấu hình đã đọc: DynamoDB chưa có Retain/UpdateReplacePolicy/PITR; web bucket chưa có versioning hoặc explicit deny HTTP trong bucket policy, dù có encryption, public access block và CloudFront OAC. Stack deletion có thể làm mất dữ liệu; bucket có object có thể khiến deletion thất bại. Không tự đổi các chính sách này trong preflight. Ứng dụng mở self-signup, chưa có quota tenant toàn platform hoặc giới hạn chi phí cứng.

## Khả năng MCP

- `run_script` + `call_boto3`: có khả năng gọi AWS API; STS, inventory, IAM simulation và ValidateTemplate đã chạy thành công.
- Sandbox MCP không đọc trực tiếp ổ đĩa máy này và không có mạng tùy ý để pip/build. Đóng gói phải làm cục bộ, đã chứng minh thành công.
- `get_presigned_url` có giao diện cấp URL PUT S3 cho file cục bộ. Sau duyệt: tạo artifact bucket qua MCP, lấy URL qua MCP, gửi ZIP bằng HTTPS PUT, kiểm tra HeadObject qua MCP. Không cần AWS CLI hoặc local AWS credentials. URL sẽ không được ghi vào báo cáo/log.
- CloudFormation có thể được điều phối bằng CreateChangeSet/DescribeChangeSet/ExecuteChangeSet/DescribeStacks qua run_script. Chưa gọi các API ghi để thử khả năng; không khẳng định deploy đã được quyền ghi thực tế.
- Frontend dùng cùng cầu nối upload cho index.html, app.js, styles.css và config.json, sau đó CreateInvalidation qua MCP.
- Không thấy thiếu giao diện công cụ thiết yếu cho quy trình trên. Phần chưa kiểm chứng là PUT thật, API ghi thật, SAM transform trong change set và provisioning. Nếu MCP từ chối ở giai đoạn đó sẽ báo đúng API/bước bị chặn, không fallback CLI.

## Kế hoạch sau khi duyệt

1. Xác nhận STS, trạng thái stack/tên tài nguyên/quota một lần nữa. Áp dụng thay đổi concurrency đã được duyệt, chạy lại lint. Nếu phát hiện stack/tài nguyên mới ngoài kế hoạch, dừng để đánh giá quyền sở hữu.
2. Tạo private artifact bucket `crg-artifacts-376129867108-ap-southeast-1` tại region đích, chặn public access và bật SSE-S3. Dùng key theo stack và SHA/timestamp, không ghi đè key cũ. Bucket này nằm ngoài stack ứng dụng.
3. Upload ZIP qua URL ký bởi MCP. Chuẩn bị bản template đóng gói với Globals.Function.CodeUri trỏ đúng bucket/key. Tạo change set loại CREATE, CAPABILITY_IAM và CAPABILITY_AUTO_EXPAND, DomainPrefix=`crg-376129867108-ap-southeast-1`, SenderEmail rỗng.
4. Đọc change set và kết quả validation; chỉ thực thi khi đúng danh sách tạo mới dự kiến, không sửa/xóa tài nguyên ngoài phạm vi. Theo dõi đến CREATE_COMPLETE; khi thất bại lưu lý do, không tự xóa stack hoặc tài nguyên khác để thử lại.
5. Đọc Outputs, tạo config.json đúng API/Cognito/CloudFront URL. Upload 4 file frontend vào đúng WebBucket của stack; invalidate CloudFront; kiểm tra HTTPS, CORS, route bảo vệ.
6. Người dùng đăng ký/xác minh email và đăng nhập trên Hosted UI. Không yêu cầu gửi mật khẩu/OTP/token trong chat. Lấy ExternalId từ profile /me đã xác thực cùng ApiPrincipal/ScanPrincipal từ stack.
7. Tạo stack riêng `guardian-read-role-demo` với RoleSuffix=demo, role `GuardianReadRole-demo`, CAPABILITY_NAMED_IAM. Trust chỉ hai principal của stack và ExternalId của tenant. Sau đó lưu connection tới account 376129867108, chỉ ap-southeast-1.
8. Smoke test AWS thật: API chưa đăng nhập bị chặn, Cognito PKCE/logout, connection đúng/sai ExternalId, quét async, DynamoDB/history, isolation hai tenant khi có hai tài khoản thử, scheduler, logs/failure queue. Phân biệt pass/failed/not-tested và bàn giao URLs/ARNs.

## Tài nguyên và quyền cần dùng

Tài nguyên chính: 3 Lambda Python 3.12 (API 29s, worker 300s, scheduler 60s; 256MB), 3 execution roles với inline policies, 3 log groups retention 7 ngày, HTTP API/JWT authorizer/stage/routes và Lambda permissions; Cognito pool/client/domain; một DynamoDB PAY_PER_REQUEST có TTL; một SQS failure queue giữ 14 ngày; EventBridge rule mỗi giờ và permission; private web S3 bucket/bucket policy; CloudFront distribution/OAC. SAM sinh thêm permission, stage và async invocation config. Thêm artifact bucket ngoài stack và một read role trong stack riêng. Không tạo SES identity khi SenderEmail rỗng, không tạo EC2/RDS/NAT.

Quyền triển khai: CloudFormation create/describe/execute change set, describe stack/events và thao tác rollback cần thiết; S3 tạo/cấu hình bucket, PutObject/GetObject/HeadObject, bucket policy; IAM CreateRole/GetRole/PutRolePolicy/AttachRolePolicy/TagRole/PassRole (và quyền tháo/xóa phục vụ rollback); tạo/cấu hình Lambda, Logs, DynamoDB, SQS, EventBridge, API Gateway v2, Cognito, CloudFront/OAC và invalidation. Không cần cấp admin cho Lambda. Chỉ thêm SES create identity/send khi bật email sau này.

Quyền runtime: API đọc/ghi dữ liệu tenant, invoke worker và AssumeRole; scheduler scan/update bảng và invoke worker; worker đọc/ghi bảng, gửi SQS failure và AssumeRole; các Lambda ghi logs. ApiRole/ScanRole hiện cho AssumeRole theo pattern `arn:aws:iam::*:role/GuardianReadRole-*`; trust của read role mới là giới hạn hai principal + ExternalId.

Read role chỉ có ec2:DescribeInstances, DescribeVolumes, DescribeAddresses, DescribeSnapshots, DescribeImages và cloudwatch:GetMetricData trên Resource `*`. Không có stop/terminate/delete tài nguyên được quét.

## Chi phí và giới hạn chưa kiểm thử

Có thể tính phí: Lambda requests/duration, API Gateway requests, DynamoDB reads/writes/storage (scheduler scan mỗi giờ), CloudWatch logs và GetMetricData, S3 storage/requests cho cả hai bucket, CloudFront requests/transfer/invalidation, Cognito theo lượng sử dụng, SQS; SES nếu bật. Chưa đo bill, chưa có mức sử dụng để tính dự toán đáng tin cậy, không giả định Free Tier. Mặc định tenant quét mỗi 6 giờ; API thủ công cooldown 15 phút. Không tạo Budget hay tài nguyên thử có phí trong kế hoạch mặc định.

Chưa kiểm thử AWS end-to-end: Cognito/JWT/CORS/PKCE thật, trust AssumeRole đúng/sai, multi-tenant thật, Lambda retries/destination/quotas, scheduler thật, metrics thật, SES thật, tải/concurrency. Region hiện rỗng nên một scan thành công chỉ chứng minh luồng empty inventory; không chứng minh rule phát hiện tài nguyên thật. EBS/EIP cần quan sát theo thời gian (mặc định 24 giờ); EC2 cần 24–72 giờ metrics; snapshot cần mẫu có tuổi/tham chiếu AMI. Việc tạo tài nguyên thử hoặc thay đổi quyền để fault injection sẽ cần phạm vi cụ thể được duyệt.

MVP chỉ tối đa 3 region/tenant, 100 tài nguyên mỗi loại/region, 50 findings hiển thị/region, worker 300 giây, lịch sử 30 ngày và 20 kết quả region gần nhất. Heuristic không phải kết luận được phép xóa. Không có chứng nhận compliance hoặc kiểm thử tải trong preflight này.
