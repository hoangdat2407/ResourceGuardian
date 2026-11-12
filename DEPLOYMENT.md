# Triển khai và vận hành Cloud Resource Guardian

Tài liệu này hướng dẫn thao tác, không xác nhận trạng thái một stack đang chạy. Luôn kiểm tra account, region, revision và Outputs thực tế. Cách cài công cụ, đăng nhập và triển khai cơ bản nằm trong [README.md](README.md#3-triển-khai-trên-aws--windows--powershell).

## Manual release gate

1. Hoàn tất kiểm tra local ở [README.md](README.md#7-kiểm-thử), commit revision và rà diff code/template/IAM. Giữ hai bản [target-role.yaml](target-role.yaml) và [web/target-role.yaml](web/target-role.yaml) giống nhau.
2. Xác nhận account bằng STS, chọn stack/region và phạm vi chi phí. Nghiệm thu dùng stack riêng `cloud-resource-guardian-task8-test` tại `ap-southeast-1`, SES tắt; không dùng stack đang phục vụ người dùng để fault injection.
3. Reviewer ghi revision, account/stack/region, template/IAM diff, tác động replacement của UserPool, trạng thái self-sign-up theo template, số user vận hành dự kiến và allowlist chỉ đọc của target role. Executor được cấp quyền phải khác reviewer; hai tên khai báo trong manifest không tự xác thực danh tính hay cấp quyền cloud.
4. Review change set thực tế trước khi execute. `deploy.py --plan` có thể tạo/cấu hình artifact bucket, upload ZIP và tạo change set; đây là thao tác ghi AWS. `publish.py` ghi S3 và invalidate CloudFront.
5. Pin SHA-256 của ZIP và source/template đã review. Deploy chính ZIP đó qua `--artifact`, không đóng gói lại sau khi pin. Thay đổi source hoặc template cần cập nhật pin trước lần nghiệm thu tiếp theo.
6. Chạy E2E với hai tenant khác nhau; giữ scan ID, UTC, revision/hash, region, kết quả và log/request ID đã loại secrets. Không lưu password, OTP, token, credentials hoặc presigned URL trong source/manifest/evidence.

Rule bắt buộc có evidence AWS thật cho EC2, EBS, EIP, snapshot và stale S3 multipart. RDS/NAT/ALB/NLB chỉ được `SKIPPED` với `RESOURCE_NOT_AVAILABLE` hoặc `COST_NOT_APPROVED`. EBS/EIP phải chờ đủ cửa sổ quan sát thật, mặc định 24 giờ; không sửa timestamp để thay bằng chứng. Không tạo tài nguyên tính phí chỉ để lấy evidence khi chưa được chấp thuận.

Phân biệt `PASS`, `FAIL`, `CHƯA CHẠY`, `THIẾU ĐẦU VÀO` và `SKIPPED`. Test local/Moto, inventory rỗng hoặc trang đăng nhập không chứng minh rule và luồng đa tenant hoạt động trên AWS.

## Artifact và xuất bản web

ZIP Lambda cần ba module trong `src/` và dependencies của `src/requirements.txt`, tương thích Linux x86_64/Python 3.12. `deploy.py --artifact` kiểm tra byte nguồn so với checkout và từ chối fault wrapper. Harness tạo manifest pin bằng lệnh `package` ở phần dưới.

Ví dụ tạo change set trên stack thử sau khi đã xác nhận phiên AWS và phạm vi:

```powershell
.\.venv\Scripts\python.exe deploy.py `
  --profile guardian-lab --region ap-southeast-1 `
  --stack cloud-resource-guardian-task8-test `
  --domain-prefix crg-task8-CHUOI-RIENG `
  --artifact .preflight/task8-artifacts/task8-final.zip --plan
```

Thay `CHUOI-RIENG` bằng chữ thường/số độc nhất. Executor chỉ execute change set đã được reviewer duyệt. Sau khi stack hoàn tất, xác minh cả năm Lambda API/scheduler/worker/recovery/reconciler dùng đúng hash ZIP, handler và cấu hình chuẩn; SES vẫn tắt.

`publish.py` tạo `config.json` từ Outputs và upload `index.html`, `styles.css`, `app.js`. Script chưa upload `target-role.yaml`; đưa [web/target-role.yaml](web/target-role.yaml) lên đúng WebBucket trước khi gọi publish để invalidation bao phủ đủ năm object. Sau khi xác nhận account/stack và gate, dùng Outputs thực tế:

```powershell
$reviewStack = 'cloud-resource-guardian-task8-test'
$webBucket = aws cloudformation describe-stacks --stack-name $reviewStack --profile guardian-lab --region ap-southeast-1 --query "Stacks[0].Outputs[?OutputKey=='WebBucket'].OutputValue | [0]" --output text
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($webBucket) -or $webBucket -eq 'None') { throw 'Khong lay duoc WebBucket cua stack da chon' }
aws s3 cp .\web\target-role.yaml "s3://$webBucket/target-role.yaml" --content-type application/yaml --cache-control no-store --profile guardian-lab --region ap-southeast-1
if ($LASTEXITCODE -ne 0) { throw 'Upload target-role.yaml that bai' }
.\.venv\Scripts\python.exe publish.py --stack $reviewStack --profile guardian-lab --region ap-southeast-1
```

Kiểm tra đủ năm object, MIME/cache/hash, config không phải demo và CloudFront invalidation hoàn tất. UserPool template hiện cho phép self-sign-up và xác minh email; nếu môi trường nghiệm thu yêu cầu account nội bộ, áp dụng quy trình phê duyệt riêng hoặc review thay đổi Cognito trước deploy, không mô tả template hiện tại là admin-only.

Trước UPDATE, lưu template/artifact/config/assets cũ đúng phạm vi để có thể khôi phục. Không tự xóa stack, bucket hoặc dữ liệu tenant để xử lý lỗi triển khai.

## Inventory identity rollout — cần phê duyệt

Source mới dùng cùng bảng DynamoDB, không thêm GSI và không rewrite dữ liệu: inventory được lưu bằng item page tenant/connection/scan/region/type có TTL. Scan cũ giữ aggregate count và frontend fallback tương thích. Không có migration dữ liệu bắt buộc, nhưng capability chưa reachable trên stack cho đến khi reviewer duyệt:

1. Event `GET /inventory` đã được thêm cho `ApiFunction` trong `template.yaml`. Route kế thừa Cognito JWT default authorizer giống `/findings`; không tạo Lambda mới.
2. Thêm đúng một action mới vào cả `target-role.yaml` và `web/target-role.yaml`: `ecr:DescribeImages`. DocumentDB và Neptune dùng boto3 clients riêng nhưng AWS IAM management API vẫn dùng `rds:DescribeDBClusters`, action này đã có. Không thêm các action không tồn tại `docdb:DescribeDBClusters`/`neptune:DescribeDBClusters`; `cfn-lint` W3037 và tài liệu AWS đều bác bỏ hai prefix đó. Không thêm action ghi.
3. Deploy backend + route trước. Smoke `/me`, `/findings`, `/history`, rồi `/inventory?scan_id=<uuid>&limit=1` phải trả 404 cho scan không thuộc tenant và không được trả dữ liệu tenant khác.
4. Chạy một scan nghiệm thu được phê duyệt. Xác minh `inventory_persisted`, count/type/region, PARTIAL/error và pagination; không kết luận complete khi có cap/permission/time error.
5. Publish frontend sau khi backend smoke đạt. Frontend mới vẫn fallback aggregate với 404/405, nhưng rollout backend-first tránh làm capability mới trông như scan legacy.

Preflight phải lưu artifact/template/config/assets revision trước, export mô tả bảng và PITR/TTL hiện tại, kiểm tra change set không replace bảng/UserPool và ước lượng write/read theo tối đa 100 identity/type/region. Không cần backup data migration vì không rewrite; production owner vẫn quyết định snapshot/on-demand backup trước release.

Rollback: publish lại web revision trước; redeploy Lambda artifact trước; nếu cần thì bỏ route `/inventory` bằng change set riêng. Item inventory additive được code cũ bỏ qua và tự hết hạn theo TTL, không xóa thủ công. Action mới `ecr:DescribeImages` có thể rollback sau khi collector cũ được khôi phục. Post-deploy smoke phải kiểm tra PKCE/login, tenant 404, scan current/history, inventory identity/aggregate legacy, feedback, PARTIAL disclosure, console error và viewport 320/390/768/1440.

## Release production có kiểm soát — chưa được tự động thực thi

Các lệnh dưới đây là runbook, không phải bằng chứng đã deploy. Chỉ chạy sau khi `aws sts get-caller-identity` khớp account được duyệt. Đặt rõ stack thực tế; không dựa vào default của script:

```bash
export PROFILE=guardian-lab REGION=ap-southeast-1
export STACK=cloud-resource-guardian
export TARGET_PROFILE=guardian-lab TARGET_ROLE_STACK=guardian-read-role-demo
export RELEASE_ID="$(date -u +%Y%m%dT%H%M%SZ)"
export BACKUP_DIR=".preflight/release-$RELEASE_ID"
export ARTIFACT=".preflight/task8-artifacts/task8-final.zip"
mkdir -p "$BACKUP_DIR"

aws sts get-caller-identity --profile "$PROFILE" --region "$REGION"
aws cloudformation describe-stacks --stack-name "$STACK" --profile "$PROFILE" --region "$REGION"
aws cloudformation get-template --stack-name "$STACK" --template-stage Processed \
  --query TemplateBody --output json --profile "$PROFILE" --region "$REGION" \
  > "$BACKUP_DIR/platform-template.json"
aws cloudformation get-template --stack-name "$TARGET_ROLE_STACK" --template-stage Processed \
  --query TemplateBody --output json --profile "$TARGET_PROFILE" --region "$REGION" \
  > "$BACKUP_DIR/target-role-template.json"

WEB_BUCKET="$(aws cloudformation describe-stacks --stack-name "$STACK" --profile "$PROFILE" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='WebBucket'].OutputValue | [0]" --output text)"
aws s3 sync "s3://$WEB_BUCKET/" "$BACKUP_DIR/web/" --profile "$PROFILE" --region "$REGION"
sha256sum "$ARTIFACT" template.yaml target-role.yaml web/target-role.yaml web/index.html web/styles.css web/app.js \
  > "$BACKUP_DIR/release-sha256.txt"
```

Nếu STS/stack/bucket trả sai hoặc backup lỗi thì dừng. Production owner quyết định tạo DynamoDB on-demand backup; source release này không rewrite bảng. Trước target-role update, tạo change set riêng và chỉ chấp nhận đúng một policy delta `ecr:DescribeImages`:

```bash
export TARGET_CHANGESET="guardian-read-role-$RELEASE_ID"
aws cloudformation create-change-set \
  --stack-name "$TARGET_ROLE_STACK" --change-set-name "$TARGET_CHANGESET" --change-set-type UPDATE \
  --template-body file://target-role.yaml --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=ApiPrincipal,UsePreviousValue=true \
    ParameterKey=ScanPrincipal,UsePreviousValue=true \
    ParameterKey=ExternalId,UsePreviousValue=true \
    ParameterKey=RoleSuffix,UsePreviousValue=true \
  --profile "$TARGET_PROFILE" --region "$REGION"
aws cloudformation wait change-set-create-complete \
  --stack-name "$TARGET_ROLE_STACK" --change-set-name "$TARGET_CHANGESET" \
  --profile "$TARGET_PROFILE" --region "$REGION"
aws cloudformation describe-change-set \
  --stack-name "$TARGET_ROLE_STACK" --change-set-name "$TARGET_CHANGESET" \
  --profile "$TARGET_PROFILE" --region "$REGION"
```

Sau khi reviewer duyệt change set role, executor mới chạy `execute-change-set` và chờ `stack-update-complete`. Tiếp theo lấy nguyên parameter hiện hữu để tạo platform change set bằng artifact đã pin:

```bash
DOMAIN_PREFIX="$(aws cloudformation describe-stacks --stack-name "$STACK" --profile "$PROFILE" --region "$REGION" \
  --query "Stacks[0].Parameters[?ParameterKey=='DomainPrefix'].ParameterValue | [0]" --output text)"
SENDER_EMAIL="$(aws cloudformation describe-stacks --stack-name "$STACK" --profile "$PROFILE" --region "$REGION" \
  --query "Stacks[0].Parameters[?ParameterKey=='SenderEmail'].ParameterValue | [0]" --output text)"
[ "$SENDER_EMAIL" = "None" ] && SENDER_EMAIL=""

.venv/bin/python deploy.py \
  --profile "$PROFILE" --region "$REGION" --stack "$STACK" \
  --domain-prefix "$DOMAIN_PREFIX" --sender-email "$SENDER_EMAIL" \
  --artifact "$ARTIFACT" --plan
```

`--plan` vẫn ghi artifact bucket và tạo change set. Reviewer phải xác nhận change set **không** replace `Data`, `UserPool`, `UserClient`, `UserDomain`, `WebBucket` hoặc tài nguyên stateful khác; thay đổi mong đợi ở platform là code của năm Lambda và route `GET /inventory`. Không execute nếu có `Replacement=True/Conditional` chưa giải thích. Sau execute và `stack-update-complete`, smoke `/me`, `/findings`, `/history`, `/inventory` với token thật đã redacted; dùng tenant thứ hai để xác nhận scan ID tenant thứ nhất trả 404.

Chỉ khi backend smoke đạt mới publish frontend:

```bash
aws s3 cp web/target-role.yaml "s3://$WEB_BUCKET/target-role.yaml" \
  --content-type application/yaml --cache-control no-store \
  --profile "$PROFILE" --region "$REGION"
.venv/bin/python publish.py --profile "$PROFILE" --region "$REGION" --stack "$STACK"
```

`publish.py` upload web và tạo invalidation. Chờ invalidation hoàn tất rồi smoke login/logout, connection, inventory/findings/history, feedback, console/network và 390/1440 px. Scan thật và SES send là hai approval riêng.

Rollback khi update chưa hoàn tất:

```bash
aws cloudformation rollback-stack --stack-name "$STACK" --profile "$PROFILE" --region "$REGION"
aws cloudformation wait stack-rollback-complete --stack-name "$STACK" --profile "$PROFILE" --region "$REGION"
```

Nếu update đã `UPDATE_COMPLETE`, tạo change set mới từ `platform-template.json` đã backup để phục hồi template/CodeUri cũ, review không replacement rồi execute; không dùng `rollback-stack` như rollback release đã hoàn tất. Khôi phục web trước bằng `aws s3 sync "$BACKUP_DIR/web/" "s3://$WEB_BUCKET/" --delete`, sau đó invalidate CloudFront. Target role rollback tương tự bằng `target-role-template.json`, nhưng chỉ sau khi backend collector cũ đã được phục hồi. Không xóa inventory page: code cũ bỏ qua và TTL tự dọn.

## Task 8 AWS harness

[tests/task8_aws_harness.py](tests/task8_aws_harness.py) có ba lệnh: `package` chạy local, `inspect` đọc AWS và ghi evidence local, `run` ghi fixture/gọi API và có thể đổi Lambda trên stack thử. Harness không tự tạo user, read role hay tài nguyên có phí.

Chuẩn bị hai Cognito user thực sự khác nhau; read role `GuardianReadRole-task8-alice` và `GuardianReadRole-task8-bob` dùng principal API/worker của stack thử, ExternalId riêng lấy từ `GET /me`. Token còn hạn chỉ đặt trong biến môi trường `CRG_TASK8_ALICE_TOKEN`, `CRG_TASK8_BOB_TOKEN`. Không dùng user/role/token của stack đang phục vụ người dùng.

Tạo ZIP Linux/Python 3.12 tại máy bằng Python có pip. Lệnh dưới không gọi AWS; pip có thể tải wheel từ package index. Chạy tại root repository sau khi cài môi trường theo README:

```powershell
@'
import pathlib, shutil, subprocess, sys, tempfile, zipfile
root = pathlib.Path.cwd()
destination = root / ".preflight/task8-build/lambda.zip"
destination.parent.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as directory:
    package = pathlib.Path(directory) / "package"
    shutil.copytree(root / "src", package, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
        "--only-binary=:all:", "--platform", "manylinux2014_x86_64", "--python-version", "3.12",
        "--implementation", "cp", "--abi", "cp312", "--target", str(package),
        "-r", str(root / "src/requirements.txt")], check=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(package))
print(destination)
'@ | .\.venv\Scripts\python.exe -X utf8 -B -
```

Review ZIP vừa tạo rồi tạo gói pin local:

```powershell
.\.venv\Scripts\python.exe tests/task8_aws_harness.py package `
  --artifact .preflight/task8-build/lambda.zip `
  --output-dir .preflight/task8-artifacts
```

Đầu ra gồm `task8-final.zip`, `task8-faults.zip` và `artifacts.json`. Deploy đúng `task8-final.zip`; gói fault chỉ dành cho scenario thử lỗi. `package`/`inspect` ghi nhận trạng thái source; `run` từ chối `src/` hoặc template chưa commit. Các bước kiểm tra artifact từ chối hash sai, ZIP cuối chứa wrapper hoặc đường dẫn không an toàn. Source trong ZIP phải khớp byte checkout; giữ nguyên EOL khi chuẩn bị artifact.

Tạo `.preflight/task8-environment.json` theo cấu trúc dưới; thay account/identities/role ARN, lấy hai hash từ `artifacts.json`. Các giá trị minh họa chưa dùng để chạy được:

```json
{
  "account_id": "123456789012",
  "region": "ap-southeast-1",
  "stack": "cloud-resource-guardian-task8-test",
  "reviewer": "reviewer-identity",
  "executor": "different-executor-identity",
  "final_zip_sha256": "replace-with-64-lowercase-hex-characters",
  "source_tree_sha256": "replace-with-64-lowercase-hex-characters",
  "users": [
    {
      "label": "alice",
      "token_env": "CRG_TASK8_ALICE_TOKEN",
      "role_arn": "arn:aws:iam::123456789012:role/GuardianReadRole-task8-alice",
      "regions": ["ap-southeast-1"]
    },
    {
      "label": "bob",
      "token_env": "CRG_TASK8_BOB_TOKEN",
      "role_arn": "arn:aws:iam::123456789012:role/GuardianReadRole-task8-bob",
      "regions": ["ap-southeast-1"]
    }
  ]
}
```

Kiểm tra stack và artifact qua AWS chỉ đọc:

```powershell
.\.venv\Scripts\python.exe tests/task8_aws_harness.py inspect `
  --profile guardian-lab --manifest .preflight/task8-environment.json `
  --artifact .preflight/task8-artifacts/task8-final.zip
```

Chạy từng scenario sau khi gate đã đủ; account phải khớp STS và manifest:

```powershell
$env:CRG_TASK8_AWS = '1'
.\.venv\Scripts\python.exe tests/task8_aws_harness.py run `
  --profile guardian-lab --manifest .preflight/task8-environment.json `
  --artifact .preflight/task8-artifacts/task8-final.zip `
  --scenario smoke --allow-mutations --confirm-account 123456789012
```

| Scenario | Bằng chứng cần kiểm tra |
|---|---|
| `smoke` | Scan thật hai tenant, tenant kia đọc scan ID trả 404; RESULT/HISTORY đúng mỗi region |
| `schedule` | Tick EventBridge thật, trigger scheduled và metric/log tương ứng; không invoke thay tick |
| `race` | Manual tranh chấp với hai scheduler được invoke; chỉ một scan được nhận |
| `duplicate` | Worker trùng không sửa terminal; recovery partial batch đúng; envelope recovery của ca này là synthetic |
| `reconnect` | Connection mới không đọc/ghi kết quả job cũ; ghi rõ nếu inventory quá nhanh để chứng minh worker đang chạy |
| `orphan` | Marker thử quá hạn được tick reconciler thật đóng TIMED_OUT và lưu history |
| `transient` | Worker lỗi lần đầu, async retry thật chạy thành công với ít nhất hai request ID |
| `exhausted` | Ba request ID, OnFailure thật có RetriesExhausted/invoke count 3, FAILED/RETRIES_EXHAUSTED bền vững |
| `hard-timeout` | Wrapper invocation và platform timeout cùng request ID, rồi TIMED_OUT và failure delivery thật |
| `consumer` | Recovery liên tục lỗi, message thật vào OperationsDeadLetters; giữ message làm evidence |
| `final-smoke` | Tất cả function đã về ZIP/handler chuẩn, sau đó smoke hai tenant đạt |

Các ca fault cần thêm `--fault-zip .preflight/task8-artifacts/task8-faults.zip`. Chạy tuần tự; `schedule` mặc định đợi tối đa 4.200 giây, `consumer` có thể khoảng 40 phút. Harness chỉ điều chỉnh fixture của tenant thử, kiểm tra connection/lease và từ chối reset khi marker còn hoạt động.

Harness cố khôi phục ZIP/handler/môi trường chuẩn trong `finally`; tiến trình bị kill hoặc mất quyền có thể ngăn việc này. Phải xác minh khôi phục hash/config và chạy `final-smoke` trước khi kết luận nghiệm thu. Không đưa wrapper vào `src/` hoặc artifact phát hành.

## AWS E2E cho rule và web

[tests/test_aws_e2e.py](tests/test_aws_e2e.py) là suite khác harness điều phối. Chuẩn bị năm biến `CRG_AWS_E2E_API_URL`, `CRG_AWS_E2E_ACCESS_TOKEN`, `CRG_AWS_E2E_SECOND_ACCESS_TOKEN`, `CRG_AWS_E2E_MANIFEST`, `CRG_AWS_E2E_EVIDENCE`; đọc schema/side effect trong test trước khi bật. Suite ghi kết nối/cấu hình và tạo scan thật.

Manifest rule E2E có đúng năm key `role_arn`, `regions`, `settings`, `required_findings`, `optional_findings`; cấu trúc từng finding được kiểm tra trong `AwsEndToEnd._validate_manifest()` của test. Không tái sử dụng manifest `task8-environment.json` của harness điều phối vì hai schema khác nhau.

Suite luôn `PUT /connection`, vì vậy tạo connection version mới và bắt đầu lại observation EBS/EIP. Nó kiểm tra scan/history/isolation và finding theo type/region/resource ID cùng `allowed_levels` của manifest; không tự xác minh toàn bộ evidence hoặc buộc EBS/EIP đã thành REVIEW. Sau suite, giữ nguyên kết nối và quét tiếp qua UI/API để lấy bằng chứng đủ cửa sổ thật; chạy lại suite sẽ reset cửa sổ. Với harness điều phối, `reconnect` cũng đổi version; hoàn tất ca này trước khi bắt đầu đo cửa sổ hoặc đo lại sau đó.

```powershell
$env:CRG_AWS_E2E = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_aws_e2e.py' -v
```

Kết thúc phiên AWS E2E, đặt `$env:CRG_AWS_E2E = '0'` trước khi chạy discover local. Phần evidence còn lại và các thao tác web dưới đây cần kiểm tra riêng; không suy ra chúng đã được suite tự động bao phủ.

Kiểm tra web với evidence đủ chín loại, first/last, đã xem, giữ/bỏ giữ, bỏ qua/bỏ ignore, refresh/scan tiếp và history. Feedback mới không sửa snapshot lịch sử; dữ liệu thiếu không thành zero. Chạy AWS E2E có chủ đích, không bật chỉ để hoàn tất suite local.

## Recovery runbook

- Đọc Outputs/physical resource ID thực tế, trạng thái từng region, scan ID, connection version và log/request ID. Phân biệt retry đang chạy, `PARTIAL`, `FAILED` và `TIMED_OUT`; queue rỗng hoặc alarm OK không chứng minh hệ thống khỏe.
- Worker timeout 300 giây, run lease 330 giây, deadline job 900 giây; async retry tối đa 2, event age 600 giây. EventBridge gọi scheduler mỗi giờ; reconciler đối soát mỗi 5 phút. Terminal write ràng buộc tenant/connection/scan; worker thêm guard `run_token`, recovery/reconciler chỉ ghi terminal khi không còn lease hoạt động. RESULT + HISTORY được ghi nguyên tử.
- `DeadLetters` là OnFailure destination có Recovery Lambda consumer; message không xử lý được sẽ redrive sang `OperationsDeadLetters`. Recovery/reconciler chỉ sửa trạng thái platform, không đọc hay sửa tài nguyên account đích.
- Kiểm tra Errors/Throttles, async drops/destination failures, EventBridge delivery và SQS backlog/age cùng log. SQS metric xấp xỉ; DynamoDB TTL xóa bất đồng bộ. Không xóa marker, sửa lease trực tiếp, purge queue hoặc replay hàng loạt để làm hết lỗi.
- Sau khi sửa nguyên nhân, scan mới qua UI/API vẫn tuân thủ cooldown 15 phút. Với fault test, khôi phục đúng ZIP/handler/environment của stack thử, xác minh CodeSha256 và final-smoke trước scenario tiếp theo.
- Khi cần rollback release, xác minh không có người khác vừa cập nhật rồi dùng CloudFormation rollback hoặc artifact/config/assets đã backup đúng phạm vi. Read role luôn chỉ đọc; không mở quyền sửa tài nguyên để khắc phục lỗi AssumeRole.

Evidence và backup cục bộ đặt trong `.preflight/` bị Git ignore, loại secrets trước khi chia sẻ. Kết quả kiểm tra báo trong phần bàn giao của lượt thực hiện; không cần tạo thêm nhật ký Markdown theo plan. Theo dõi chi phí bằng inventory và Billing của account được cấp quyền; không suy chi phí platform hoặc tiền tiết kiệm từ số finding.
