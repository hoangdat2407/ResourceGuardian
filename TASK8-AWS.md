# Task 8: harness và nghiệm thu AWS

Harness [tests/task8_aws_harness.py](tests/task8_aws_harness.py) đã được chuẩn bị cho **stack kiểm thử riêng** `cloud-resource-guardian-task8-test`, region `ap-southeast-1`. Có harness và test local không phải bằng chứng đã chạy AWS. Ngày 26/10/2026, kiểm tra boto3 tại máy phát triển trả `available_profiles=[]`, `credential_source=null`; AWS CLI/SAM không có trên `PATH`. Vì thiếu phiên AWS, các ca cloud trong tài liệu này **CHƯA CHẠY**.

Phạm vi ở đây là điều phối, lưu trạng thái/history và đường phục hồi Task 8. Inventory rỗng vẫn có thể chứng minh luồng điều phối; nghiệm thu các rule trên tài nguyên thật thực hiện riêng theo [VALIDATION.md](VALIDATION.md). SES luôn tắt trên stack thử.

## Điều kiện trước khi chạy

1. Hoàn tất local validation, review code/template/IAM và commit revision đã review. Harness từ chối nghiệm thu khi `src/` hoặc `template.yaml` còn thay đổi chưa commit; `AGENTS.md` cục bộ không ảnh hưởng kiểm tra này.
2. Xác nhận account lab bằng `sts:GetCallerIdentity`, stack/region và phạm vi chi phí. Tuân thủ reviewer/executor trong [manual release gate](VALIDATION.md#manual-release-gate). Hai tên trong manifest là biên bản do người vận hành khai báo, không phải cơ chế xác thực danh tính reviewer.
3. Executor tạo hoặc cập nhật **stack thử riêng**, dùng đúng ZIP cuối được pin hash bên dưới; không cập nhật stack đang dùng. Rà change set trước khi execute, UserPool không bị replace ngoài dự kiến, Cognito admin-only và tối đa 5 user. Xem [DEPLOYMENT.md](DEPLOYMENT.md) trước mọi thao tác AWS. `deploy.py --plan` upload artifact/tạo change set, không phải kiểm tra offline.
4. Chuẩn bị hai Cognito user thực sự khác nhau và hai read role `GuardianReadRole-task8-alice`, `GuardianReadRole-task8-bob` trong account lab. Tạo trust từ [target-role.yaml](target-role.yaml), dùng principal API/worker **của stack thử** và ExternalId riêng của từng user lấy từ `GET /me`. Không dùng role hoặc token của stack đang dùng. Harness không tạo user, role hay tài nguyên có phí để tạo finding.
5. Cấp phiên AWS cho executor. Các lệnh cần quyền đọc CloudFormation, Cognito, Lambda, CloudWatch Logs/metrics, DynamoDB và SQS; các ca `run` thêm quyền gọi API/Lambda, sửa fixture DynamoDB. Ca fault thêm quyền cập nhật code/config **hai Lambda worker/recovery của stack thử**. Không cấp quyền sửa tài nguyên được quét cho read role.
6. Cấp access token còn hạn của hai user qua biến môi trường `CRG_TASK8_ALICE_TOKEN`, `CRG_TASK8_BOB_TOKEN` trong phiên vận hành. Không lưu token/password/OTP/access key vào manifest, source, transcript hoặc evidence. Token hết hạn trong lúc chờ tick/timeout thì lấy phiên mới trước khi chạy lại ca đó; không chuyển lỗi xác thực thành PASS.

`inspect` chỉ đọc AWS và ghi evidence cục bộ. `run` chủ động sửa fixture test, gọi API quét và có thể đổi gói Lambda trong ca fault. Phải đặt đồng thời `CRG_TASK8_AWS=1`, `--allow-mutations`, `--confirm-account` đúng manifest. Harness chỉ chấp nhận tên stack/region cố định nói trên, hai user/role/token-env khác nhau, account đúng và source/artifact hash khớp. Các gate này bổ sung kiểm tra vận hành, không tự cấp quyền deploy.

## Gói cuối và gói gây lỗi

Tạo ZIP deployment theo luồng đóng gói của dự án, giữ đủ ba file nguồn và dependency từ `src/requirements.txt`. Có thể đóng gói **offline đối với AWS** bằng PowerShell tại repository; pip vẫn có thể tải wheel từ package index:

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

.\.venv\Scripts\python.exe -X utf8 -B tests/task8_aws_harness.py package `
  --artifact .preflight/task8-build/lambda.zip `
  --output-dir .preflight/task8-artifacts
```

Lệnh `package` không gọi AWS. Kết quả gồm `task8-final.zip`, `task8-faults.zip`, `artifacts.json` dưới `.preflight/task8-artifacts/` (thư mục bị gitignore). Manifest artifact lưu Git SHA, trạng thái source chưa commit, hash từng file `src/*.py`, requirements/template, hash tree và hai ZIP. ZIP cuối bị từ chối nếu chứa wrapper, có entry trùng/đường dẫn không an toàn, tên cấu hình/key nhạy cảm thường gặp (`.env*`, `.aws`, `credentials`, private SSH keys) hoặc source không khớp checkout. Kiểm tra tên file không thay thế review source/dependency để phát hiện secret được đặt dưới tên khác. ZIP fault chỉ được khác ZIP cuối ở một file `task8_faults.py`; source và mọi dependency phải giữ nguyên byte.

Executor phải deploy **chính `task8-final.zip`**, không build lại một ZIP khác sau khi pin hash. Mọi function của template dùng chung artifact. Sau deploy, `inspect` so `CodeSha256` của API, scheduler, worker, recovery và reconciler với hash ZIP, so handler chuẩn và kiểm tra timeout/retry/queue/Cognito/SES. [deploy.py](deploy.py) có tùy chọn `--artifact` để dùng đúng byte ZIP đã review, kiểm tra source trước mọi AWS call và từ chối wrapper test. Khi không truyền tùy chọn này, luồng tự đóng gói hiện có vẫn được giữ.

Sau khi xác nhận quyền cloud theo gate, executor có thể tạo change set cho stack thử bằng lệnh dưới; đây là **AWS mutation**, không nằm trong bước package/local validation. Dùng Cognito domain prefix riêng đã được review:

```powershell
.\.venv\Scripts\python.exe -X utf8 -B deploy.py `
  --profile guardian-lab --region ap-southeast-1 `
  --stack cloud-resource-guardian-task8-test `
  --domain-prefix crg-task8-reviewed-unique-prefix `
  --artifact .preflight/task8-artifacts/task8-final.zip --plan
```

Lưu hash in ra cùng change set, rà IAM/resources/UserPool, rồi executor execute đúng change set đã được reviewer duyệt. Không lấy hash ZIP được build lại làm bằng chứng cho ZIP đã deploy.

Gói fault chỉ xuất hiện khi operator chủ động chạy ca lỗi trên stack thử. Harness tạm đổi handler worker/recovery sang wrapper, giữ môi trường ban đầu, rồi trong `finally` upload lại ZIP cuối, khôi phục handler/môi trường và kiểm tra hash/config thực tế. Nếu tiến trình bị kill hoặc mất quyền AWS khi khôi phục, `finally` không bảo đảm hoàn tất: vận hành phải kiểm tra và khôi phục thủ công trước ca tiếp theo. Không đưa wrapper vào `src/` hoặc artifact phát hành.

## Manifest và lệnh chạy

Tạo `.preflight/task8-environment.json` sau khi có account/hash thật. Đây là cấu trúc mẫu; thay các giá trị minh họa, lấy hai hash từ `artifacts.json`:

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

Kiểm tra trước, dùng tên profile đã xác thực (có thể bỏ `--profile` nếu dùng credential chain đã được chuẩn bị):

```powershell
.\.venv\Scripts\python.exe -X utf8 -B tests/task8_aws_harness.py inspect `
  --profile guardian-lab `
  --manifest .preflight/task8-environment.json `
  --artifact .preflight/task8-artifacts/task8-final.zip
```

Chạy từng ca riêng, giữ console và phiên AWS hoạt động. Thay account minh họa bằng account đã được xác minh:

```powershell
$env:CRG_TASK8_AWS = '1'
.\.venv\Scripts\python.exe -X utf8 -B tests/task8_aws_harness.py run `
  --profile guardian-lab `
  --manifest .preflight/task8-environment.json `
  --artifact .preflight/task8-artifacts/task8-final.zip `
  --scenario smoke --allow-mutations --confirm-account 123456789012
```

Đổi `--scenario` theo bảng dưới. Ca fault cần thêm `--fault-zip .preflight/task8-artifacts/task8-faults.zip`. `schedule` mặc định đợi tối đa 4.200 giây để bao phủ tick một giờ; có thể đổi bằng `--schedule-wait`. Các ca khác thường dưới 20 phút; `consumer` có thể khoảng 40 phút vì phải chờ retry và tối đa 5 lần nhận SQS với visibility 180 giây. Chạy tuần tự, không để hai operator đổi Lambda/fixture cùng lúc.

| Scenario | Thao tác và tiêu chí | Lớp bằng chứng |
|---|---|---|
| `smoke` | Hai user được Cognito xác thực, manual scan từng user qua API; user kia đọc scan ID trả 404. Result bền vững, đúng một history/region, thời gian và TTL đủ 30 ngày | API/Cognito/STS/Lambda/DynamoDB thật; không xác nhận rule trên inventory rỗng |
| `schedule` | Đặt profile thử đến hạn, chỉ quan sát tick thật; không invoke scheduler trực tiếp. Scan có `trigger=scheduled`, result/history bền vững và metric `AWS/Events/Invocations` của rule trong cửa sổ quan sát | EventBridge thật; giữ log reference scheduler để đối chiếu event/time |
| `race` | Gửi manual cùng hai invoke scheduler; chỉ một scan mới được nhận và lưu history | Cạnh tranh AWS thật; hai scheduler được harness invoke, không gọi đó là hai tick EventBridge |
| `duplicate` | Giao trùng worker khi đang quét và sau khi terminal; terminal không đổi. Gọi recovery với một envelope terminal và một JSON sai để kiểm tra partial batch response | Worker/recovery thật; envelope recovery ở riêng ca này là synthetic, ca fault chứng minh OnFailure thật |
| `reconnect` | Đổi connection ngay sau enqueue, gọi lại job connection cũ; API không lộ kết quả cũ và version đổi | API/worker/isolation thật; nếu inventory quá nhanh, chưa chứng minh worker cũ còn chạy đúng lúc reconnect |
| `orphan` | Ghi marker QUEUED quá deadline vào tenant thử, không dispatch/invoke worker/reconciler; chờ lịch reconcile 5 phút tự tạo TIMED_OUT/history | Fixture DynamoDB có chủ đích + scheduled reconciliation thật; không mô phỏng kill process API |
| `transient` | Wrapper worker fail trước scan ở lần đầu, lần sau chạy code thật; ít nhất hai request ID worker và result/history thành công | Lambda async retry thật; số lần gọi AWS collector không bị giả lập |
| `exhausted` | Wrapper luôn ném lỗi; đủ ba request ID worker, OnFailure thật có `RetriesExhausted`/invoke count 3, lưu FAILED/history với `RETRIES_EXHAUSTED` | Retry/destination/SQS/consumer thật; dispatch failure không được coi là hết retry |
| `hard-timeout` | Wrapper chặn collector sau khi worker có lease, để runtime timeout thật 300 giây; phải có wrapper invocation và platform `Task timed out` hoặc `REPORT Status: timeout` **cùng request ID**, rồi TIMED_OUT bền vững và failure delivery thật | Hard timeout và phục hồi thật; event hết tuổi trước khi worker được gọi không thể PASS ca này |
| `consumer` | Worker gây lỗi thật; recovery wrapper liên tục trả failure cho message của tenant thử; message thực tế vào OperationsDeadLetters, giữ nguyên không xóa | Redrive SQS thật; reconciler vẫn có thể đóng marker độc lập |
| `final-smoke` | Sau toàn bộ ca fault, xác minh mọi function dùng hash/handler ZIP cuối rồi chạy lại smoke hai user | Bắt buộc cho artifact cuối không có wrapper |

Harness chỉ reset `last_queued` **của tenant thử** để rút ngắn chờ giữa các ca; giữ condition theo connection version và từ chối reset khi marker còn hoạt động. Với manual, fixture còn nằm ngoài khoảng cooldown 15 phút nhưng chưa đến lịch; với `schedule`/`race`, fixture được đặt quá 24 giờ. Đây là thao tác kiểm thử, không phải thay đổi API/cooldown của sản phẩm. Sau `reconnect`/`consumer`, có thể phải đợi reconciler đóng marker cũ trước ca tiếp theo. `prepare` không tự xóa marker hoặc giải phóng khóa đang chạy.

## Evidence và điều kiện nghiệm thu

Mỗi lệnh tạo một file JSON có tên riêng trong `.preflight/task8-evidence/`. `--evidence` cho phép đặt đường dẫn khác nhưng từ chối ghi đè file có sẵn. JSON ghi SHA/tree/ZIP, account/stack/region, reviewer/executor, scenario, thời điểm, scan ID, request ID API/Lambda, trạng thái cuối, history count và tham chiếu log. Projection result không lưu finding/resource ID, raw error, profile, token hay request/envelope body. Log chỉ lưu group/stream/event ID và các trường chẩn đoán wrapper nằm trong allowlist.

`PASS` trong một file chỉ áp dụng **scenario đó**. Tổng hợp nghiệm thu cần đủ file PASS cho các ca bắt buộc và `final-smoke` trên cùng revision/tree/ZIP. Không gộp `inspect`, test offline, envelope synthetic hoặc trạng thái timeout suy ra từ API thành PASS AWS. Polling kiểm tra RESULT trực tiếp bằng consistent read và history, vì API có thể hiển thị TIMED_OUT trước khi trạng thái được lưu.

Các ca chưa được tự động hóa đầy đủ: STS AccessDenied bằng thay đổi trust/deny được review; lỗi theo từng dịch vụ trên role thật; mất dispatch đúng tại điểm process dừng; DynamoDB throttling/transaction conflict trên tài nguyên thật; worker chắc chắn đang đọc AWS khi reconnect; cảnh báo DestinationDeliveryFailures thực sự phát sinh. Local regression bao phủ logic tương ứng nhưng không thay thế cloud evidence. Đánh dấu `CHƯA CHẠY` hoặc `THIẾU ĐẦU VÀO` cho từng ca còn thiếu; không đổi cấu hình production để tạo lỗi cho các ca này.

## Runbook queue/timeout và khôi phục

1. Chọn scan ID, account/stack/region và connection version từ evidence; đọc RESULT và HISTORY của **đúng tenant** bằng consistent read. Phân biệt timeout chỉ hiển thị ở API với `TIMED_OUT` đã lưu, và kiểm tra deadline/lease/attempt count trước khi can thiệp.
2. Đối chiếu log worker, recovery, reconciler theo scan ID và request ID. Kiểm tra `DestinationDeliveryFailures` của worker, alarm backlog OperationsDeadLetters, EventBridge delivery DLQ và scheduler async destination. Không copy toàn bộ message hoặc log có dữ liệu phiên vào evidence.
3. Nếu còn lease hợp lệ, để worker/recovery tiếp tục. Nếu deadline đã qua, chờ tối đa tick reconcile tiếp theo khi hạ tầng hoạt động; kiểm tra trạng thái và history cùng xuất hiện. Với lỗi DynamoDB kéo dài, sửa hạ tầng/quyền trước khi kết luận job đã được đóng.
4. Khi message vào OperationsDeadLetters, lấy `MessageId`, condition, scan ID và log references. Harness đọc với visibility 0 và **không xóa** message. Vận hành không redrive mù toàn bộ DLQ: xác định envelope worker hay sự kiện điều phối, trạng thái scan, connection hiện tại và lỗi consumer trước khi xử lý message cụ thể. Recovery terminal/stale là idempotent; quét lại bằng scan mới qua API theo cooldown, không replay job cũ để tạo lượt quét.
5. Nếu fault restore thất bại hoặc console bị kill: dừng ca thử mới; kiểm tra worker/recovery `Handler`, `CodeSha256` và env `TASK8_*`. Executor upload lại **đúng ZIP cuối đã pin**, đặt handler `app.worker`/`app.recovery`, khôi phục env lưu trước test; không sửa `TABLE`, principal, destination hay timeout. Chạy `inspect` rồi `final-smoke` và lưu bằng chứng mới. Không xóa DLQ/evidence để che lỗi.
6. Chỉ sau khi đủ evidence trên artifact cuối mới ghi Task 8 hoàn tất. Phát hành stack đang dùng là một bước riêng với change set/gate tương ứng; các lệnh trong tài liệu này không phát hành production.

Kiểm tra local harness (không gọi AWS):

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s tests -p test_task8_harness.py -v
.\.venv\Scripts\python.exe -X utf8 -B tests/task8_aws_harness.py --help
```
