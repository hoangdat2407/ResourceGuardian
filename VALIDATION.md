# Validation matrix

## Task 8 — bàn giao local và harness, 27/10/2026

**Hoàn tất phạm vi local + harness theo lựa chọn của người dùng; AWS acceptance chưa chạy.** Nhánh `codex/task-8-scheduling-recovery`, nền `767f32ad3da911f803f221ff271631a51ed66809`. Revision bàn giao là head của PR Task 8; SHA nền không đại diện cho thay đổi Task 8. PR đặt base `duc` trong khi PR Task 7 chưa merge vào `main`, để diff chỉ bao gồm Task 8. `AGENTS.md` có sẵn và vẫn giữ untracked. Xem [hợp đồng/ma trận/runbook Task 8](TASK8.md) và [quy trình harness AWS](TASK8-AWS.md).

Thay đổi gồm admission/worker lease có điều kiện theo tenant/connection, RESULT + HISTORY nguyên tử, lịch theo tenant được cô lập lỗi và phân trang, giới hạn thời gian trước STS/từng trang collector, SQS recovery và đối soát deadline. SAM thêm recovery/reconcile, DLQ vận hành, đường lỗi delivery/async, IAM theo bảng/queue và alarm. `deploy.py --artifact` dùng nguyên byte ZIP đã review; validation tùy chọn này và mọi thử nghiệm deploy trong unittest đều dùng SDK mock, không upload AWS.

### Điểm chặn Task 8 và điều kiện gỡ

**Không còn blocker code/local đã xác minh trong phạm vi bàn giao. Task 8 vẫn chưa được nghiệm thu AWS.** Các mục B1–B4 dưới đây chặn việc chạy hoặc công nhận bằng chứng cloud tương ứng; D1 là phụ thuộc tích hợp vào `main`, không chặn review Task 8 ở base `duc`.

| ID / điểm chặn | Trạng thái và bằng chứng | Phần bị chặn | Điều kiện gỡ |
|---|---|---|---|
| B1 — Phiên AWS và account lab | **THIẾU ĐẦU VÀO.** Kiểm tra môi trường ngày 26/10/2026 không có named profile/credentials khả dụng; người dùng chọn bàn giao local + harness trước. Chưa xác minh lại phiên AWS live trong lượt bổ sung tài liệu này | Thực thi kiểm thử AWS | Chuẩn bị phiên AWS hợp lệ tại máy, xác nhận danh tính bằng STS, account lab, region `ap-southeast-1` và quyền executor trong phạm vi stack thử |
| B2 — Stack và fixture nghiệm thu | **CHƯA XÁC MINH.** Chưa có bằng chứng live cho stack Task 8, hai Cognito subject và hai read role riêng, IAM/SES hoặc ZIP đang triển khai. Không kết luận các tài nguyên này chưa tồn tại | Điều kiện đầu vào của AWS E2E | Xác minh stack `cloud-resource-guardian-task8-test`, hai user/role riêng và manifest; review change set/IAM theo release gate hiện có; SES tắt; cả năm Lambda dùng đúng handler và `CodeSha256` của ZIP đã pin |
| B3 — Luồng AWS và artifact cuối | **CHƯA CHẠY.** Các kết quả PASS hiện là local/mock/Moto/browser fixture/offline, chưa có evidence AWS Task 8 | Kết luận Task 8 hoàn tất AWS và phát hành revision này | Lưu evidence đạt cho tick EventBridge thật, manual/race/duplicate/reconnect, retry transient/exhausted, hard timeout, OnFailure → SQS → recovery, consumer redrive/DLQ và orphan reconciliation; bỏ wrapper, xác minh hash/config rồi chạy `final-smoke` trên artifact cuối |
| B4 — Coverage cloud chưa tự động hóa đầy đủ | **CHƯA CÓ EVIDENCE** cho các ca nêu trong [harness AWS](TASK8-AWS.md): STS/service denial thật, dừng tiến trình đúng điểm dispatch, DynamoDB throttling/conflict thật, reconnect chắc chắn khi worker đang đọc, và destination alarm thực sự phát sinh. Local regression không thay thế evidence này | Việc công nhận các tiêu chí cloud tương ứng đã được kiểm chứng; không tự biến tất cả thành gate bắt buộc mới | Khi nghiệm thu phần tương ứng, bổ sung kịch bản manual được review hoặc mở rộng harness; ghi kết quả/evidence hoặc lý do ngoài phạm vi rõ ràng, không đổi ca chưa chạy thành PASS |
| D1 — Phụ thuộc PR Task 7 #3 | **PHỤ THUỘC TÍCH HỢP VÀO MAIN.** PR Task 8 #4 đang đặt base `duc`; PR #3 chứa nền Task 7 chưa merge vào `main` tại thời điểm kiểm tra | Tích hợp Task 8 vào `main` theo chuỗi PR hiện tại | Merge PR #3 trước, chuyển base PR #4 sang `main`, rồi rà lại diff, dependency và kết quả kiểm tra. Đây không phải xung đột hoặc lỗi chặn review ở `duc` |

**Giới hạn khác:** GitHub hiện chưa có check runs/commit statuses cho commit Task 8; không ghi là CI PASS hay CI FAIL và chưa có bằng chứng required-check gate. Alarm chưa có SNS/người nhận tự động là giới hạn thông báo vận hành đã công bố; chỉ chặn khi phạm vi nghiệm thu bao gồm gửi thông báo tự động. Không có cloud mutation trong lượt bổ sung blocker này.

### Bằng chứng local đã đạt

| Kiểm tra trên source bàn giao | Kết quả và giới hạn |
|---|---|
| Toàn bộ backend, Python 3.12.14 | **194 test: 193 PASS, 1 AWS E2E SKIPPED**, 0 failure/error, 35.016 giây. Gồm 28 regression Task 8, 9 collector budget, 6 template invariant và 17 harness/deploy offline mới; giữ các suite rule/API/workflow hiện có |
| SDK trong artifact cuối | **111/111 PASS**, 67.735 giây: API/workflow/Task 8/collector budget dùng boto3 1.43.111 và botocore 1.43.118 giải nén từ ZIP cuối; source được đối chiếu byte với ZIP. AWS vẫn mock/Moto, không phải chạy Lambda thật |
| Bốn regression trước sửa | 2 FAIL + 2 ERROR trên nền: history transaction chưa có, terminal race vẫn đọc AWS, STS denial thiếu metadata/history, profile lỗi chặn scheduler. Sau sửa đều PASS |
| UI smoke | PASS bằng Chrome headless trên máy: polling, feedback, cấu hình, history, mobile, phiên hết hạn |
| UI fixture acceptance | PASS: trạng thái queued/running/failed/timed-out/partial/success-zero, lỗi/cooldown/phục hồi, 320/390/768/1440 px; đã xem ảnh timeout desktop và overview mobile |
| Template | `cfn-lint template.yaml target-role.yaml --regions ap-southeast-1` PASS; 6 invariant PASS |
| SAM transform offline | Reviewer dùng aws-sam-translator 1.115.0 trong môi trường công cụ riêng: PASS, 50 resource, không cycle trong đồ thị dependency. Thay CodeUri trong RAM bằng URI giả, không gọi AWS |
| Review độc lập app/SAM | APPROVE sau khi đóng lỗi claim connection race, lease release khi GetItem lỗi, metadata/history, IAM DeleteItem và metric EventBridge |
| Review độc lập harness/deploy | Không còn phát hiện actionable local/static; 17 offline tests PASS. Hard timeout phải có log runtime khớp request ID; exhausted phải có retry/condition/error code đúng; không lấy hết tuổi sự kiện làm bằng chứng hard timeout |
| JavaScript/AST/docs/whitespace | `node --check web/app.js`, AST Python liên quan, checker Markdown và `git diff --check` PASS |
| AWS | **CHƯA CHẠY**, không có cloud mutation. Không có profile/credentials khả dụng; người dùng chọn bàn giao local + harness trước |

Lệnh backend cuối đã chạy với `CRG_AWS_E2E=0` trong tiến trình kiểm thử; log có AccessDenied/Throttling là dữ liệu mock có chủ đích. Bằng chứng cục bộ bị gitignore: `.preflight/task8/backend-final.txt`, `backend-final.json`, `artifact-sdk-tests.txt`, `artifact-sdk-tests.json`, `local-validation.json`; ảnh dưới `.preflight/task8/ui-smoke/` và `ui-fixture/`. Playwright bundled Chromium chưa được cài nên lần launch đầu không chạy được; chạy lại thành công bằng `CHROMIUM_EXECUTABLE=C:\Program Files\Google\Chrome\Application\chrome.exe`.

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -c "import os,unittest; os.environ['CRG_AWS_E2E']='0'; r=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover('tests')); raise SystemExit(not r.wasSuccessful())"
$env:CHROMIUM_EXECUTABLE = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$env:UI_QA_DIR = '.preflight/task8/ui-smoke'
.\.venv\Scripts\python.exe -X utf8 -B tests/ui_smoke.py
$env:UI_QA_DIR = '.preflight/task8/ui-fixture'
.\.venv\Scripts\python.exe -X utf8 -B tests/ui_redesign.py
.\.venv\Scripts\cfn-lint.exe template.yaml target-role.yaml --regions ap-southeast-1
node --check web/app.js
node .agents/skills/resourceguardian-delivering-task/scripts/check-doc-links.mjs
git diff --check
```

Artifact đã đóng gói cho Python 3.12/Linux x86_64 từ `src/requirements.txt`, dùng Python runtime có pip vì `.venv` hiện không có pip. Gói cuối `.preflight/task8-artifacts/task8-final.zip`, **16.774.834 byte**, không chứa fault wrapper. Gói gây lỗi riêng chỉ thêm `task8_faults.py`. `artifacts.json` lưu snapshot tại thời điểm đóng gói trước commit: từng source hash, Git SHA nền, cờ `source_dirty=true`, tree hash và cả hai ZIP hash. Khi bàn giao commit, đối chiếu source tree/ZIP dưới đây với head PR:

```text
source_tree_sha256: 3d17a178a82f7811967c1443167ad28039c19c5723e4d20d3e39b9b7f665c1e6
final_zip_sha256:   e059c4785ff216819ae4125780b6bcd19846e7b0278f017df0a6dd91cdcf1c50
fault_zip_sha256:   e646b4d11767428462ecec829f3a9a03628d783e9d092a9036f519fd3db5073d
```

Khi có môi trường cloud: commit source đã review trước nghiệm thu, xác nhận account/stack test/region và hai user/role riêng, deploy đúng ZIP hash qua change set đã review, chạy đủ scenario và smoke lại artifact cuối sau khi loại wrapper. Harness từ chối AWS acceptance nếu source/template chưa commit. SHA commit có thể đổi sau bàn giao nhưng source tree/ZIP phải vẫn khớp manifest. Bộ kiểm tra local và artifact tồn tại không xác nhận IAM enforcement, tick EventBridge, async retry, hard timeout, SQS/redrive hoặc isolation trên AWS thật.

## Task 7 — nghiệm thu chín loại hiện có, 26/10/2026

**Hoàn tất ở lớp code và kiểm thử local trong phạm vi người dùng đã chốt:** EC2, EBS volume, EIP, EBS snapshot, S3 multipart, RDS instance, NAT Gateway, ALB và NLB. Kiểm tra trên nhánh `duc`, sau commit nền `d9a3b26`, bằng Python 3.12.14; commit bàn giao và head được xác nhận trong PR. Kết quả này thay thế snapshot local cũ bên dưới khi đánh giá hành vi hiện tại.

Theo PDF trang 17, Task 7 là luật đánh giá và bằng chứng, nhận dữ liệu từ Task 6. Báo cáo định hướng sáu nhóm dịch vụ và đối chiếu chi phí; chín loại đang có thuộc bốn nhóm. **THIẾU ĐẦU VÀO / chưa triển khai:** collector cho nhóm AI/analytics, giám sát/tích hợp, các dịch vụ khác chưa có trong bốn nhóm và billing/cost. Cần Task 6 bàn giao dữ liệu/quan hệ/quyền đọc cùng bộ rule được chốt trước khi nghiệm thu các phần này. Dashboard hiển thị đầy đủ evidence thuộc Task 9, ngoài phạm vi backend đã chốt cho lượt này. Xem [RULES.md](RULES.md) để biết hợp đồng chi tiết.

| Tiêu chí Task 7 | Kết quả và bằng chứng hiện tại | Lớp xác minh |
|---|---|---|
| Evaluator và finding cho đủ chín loại | Mỗi finding có rule ID, lý do, khuyến nghị, ngưỡng, account/region/mốc scan; metric có đơn vị, statistic, cửa sổ và counts. `test_all_nine_types_have_context_thresholds_and_persisted_explanations` đối chiếu collector → worker → API/scan status/history | Unit + mock/Moto PASS |
| Metric lỗi không dẫn đến ít hoạt động | Âm, boolean, sai kiểu, None, NaN/infinity, số nguyên cực lớn và aggregate overflow trả insufficient với diagnostics JSON hợp lệ; không lưu mẫu lỗi thô. Mẫu zero thật vẫn hợp lệ | `test_rules.py`, `test_workflows.py` PASS |
| Độ phủ và ngưỡng đúng | Mỗi metric đủ 20/24 hoặc 135/168 mẫu; kiểm tra trước/bằng/sau ngưỡng, p95 nearest-rank, mean và NAT/EC2 trung bình riêng hai chiều. Tài nguyên mới/thiếu ngày tạo trả insufficient, không gọi CloudWatch | Unit + mock/Moto PASS |
| Chất lượng timestamp và pagination | Giữ zero, lọc `[start,end)`, khử trùng timestamp; từ chối duplicate xung đột, sai status/ID/shape, token lặp và timestamp lệch lưới giờ. 24 điểm zero trong 24 phút không được coi là 24 giờ; test riêng năm namespace, phần dịch vụ hợp lệ vẫn được giữ | Mock/Moto PASS |
| EBS/EIP và snapshot/S3 | Tách observation theo type/connection/region, migrate key cũ chỉ khi native ID nhận diện được loại; kiểm tra reset khi dùng lại, gap >48 giờ, expiry/clock rollback. Snapshot bỏ AMI tham chiếu, AMI disabled và AWS Backup; lỗi/truncation AMI không tạo review. Multipart đúng 7 ngày chưa stale | Unit + mock/Moto PASS |
| Ngoại lệ và phục hồi finding | Tag suppression cho sáu loại có tag đầu vào; phản hồi nội bộ dùng ID ổn định cho mọi finding. Private candidates giữ finding bị feedback ẩn qua scan để clear/expiry có thể hiện lại; acknowledged/kept/ignore độc lập; lịch sử bất biến; API không lộ candidates | API + mock/Moto PASS |
| Lỗi, giới hạn và lưu trữ | Lỗi theo dịch vụ tạo PARTIAL, giữ phần kết quả có bằng chứng. Cap 100 tài nguyên/loại, 50 hiển thị, 100 candidates và result JSON 300 KiB; truncation ghi rõ PARTIAL/CANDIDATE_LIMIT và giới hạn số đếm | Mock/Moto PASS |
| Isolation và quyền đọc | Auth/tenant/connection/region, feedback ownership, observation và legacy migration được regression; hai bản target role được test invariant chỉ đọc | API + mock/Moto + static PASS |

**Kết quả chạy trên source cuối:** 134 test, **133 PASS, 1 SKIPPED**, 0 failure/error; gồm 57 rule, 25 API, 49 workflow, 2 read-only contract và 1 AWS E2E bị tắt. Số lượng là phương thức test, chưa tính các subtest. Log AccessDenied/Throttling trong suite là dữ liệu mock của ca lỗi/retry có chủ đích.

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -c "import os, unittest; os.environ['CRG_AWS_E2E'] = '0'; suite = unittest.defaultTestLoader.discover('tests'); result = unittest.TextTestRunner(verbosity=1).run(suite); raise SystemExit(not result.wasSuccessful())"
```

AST parse của sáu file Python sửa đổi PASS; `git diff --check` PASS. Checker tài liệu offline kiểm tra 13 file, không có link hỏng. Review độc lập đọc diff ba module, kiểm tra oracle regression và chạy riêng 82 test rule/API PASS; verdict APPROVE, không còn phát hiện actionable trong phạm vi được giao.

**CHƯA CHẠY:** AWS E2E với CloudWatch/inventory thật, Cognito/STS và deployment. Không có cloud mutation trong lượt này. Không chạy lại UI/browser hoặc SAM build vì không sửa UI/hạ tầng; kết quả UI cũ ở dưới là bằng chứng lịch sử. Local/mock/Moto không chứng minh hoàn tất release hoặc toàn bộ sáu nhóm của PDF.

### Điểm chặn và điều kiện gỡ

Không còn lỗi chặn đã biết đối với commit/push và review code trong phạm vi chín loại đã chốt. Các mục dưới đây chặn nghiệm thu AWS hoặc toàn bộ phạm vi PDF; không chuyển chúng thành PASS từ kết quả local.

| Mục | Trạng thái / phạm vi bị chặn | Điều kiện gỡ |
|---|---|---|
| Revision Task 7 trên AWS | CHƯA XÁC MINH — release AWS của bản thay đổi này | Reviewer và executor khác nhau xác nhận commit, account/region/stack, template/IAM diff, UserPool không bị replace, Cognito admin-only và <=5 user, allowlist chỉ đọc; executor triển khai đúng revision đã review theo manual release gate bên dưới |
| Finding thật và luồng tích hợp | CHƯA CHẠY — nghiệm thu rule trên AWS | Chạy harness sau deploy với hai tenant và manifest hợp lệ; có finding thật EC2/EBS/EIP/snapshot/S3 multipart, đủ thời gian quan sát/metric. RDS/NAT/ALB/NLB có evidence hoặc lý do skip chính xác `RESOURCE_NOT_AVAILABLE`/`COST_NOT_APPROVED`. Xác minh sai ExternalId, isolation, lỗi quyền PARTIAL và metric thiếu không thành REVIEW; các ca lỗi không do harness tự kiểm tra cần bằng chứng manual riêng. Lưu bằng chứng đã loại secrets |
| Dịch vụ và chi phí còn thiếu trong PDF | THIẾU ĐẦU VÀO — nghiệm thu toàn bộ sáu nhóm/cost | Task 6 bổ sung collector, schema, quan hệ, quyền đọc và dữ liệu cost cho phần chưa hỗ trợ; sau đó chốt rule/ngưỡng, triển khai và kiểm thử tương ứng |

Task 9 (dashboard hiển thị/thao tác đầy đủ) nằm ngoài phạm vi backend Task 7 đã chốt, cần nghiệm thu riêng. Tag chưa được đọc cho ALB/NLB/S3 multipart và việc chỉ phục hồi ứng viên còn giữ sau truncation là giới hạn đã công bố trong [RULES.md](RULES.md), không phải tính năng đã xác minh trên AWS.

[DEPLOYMENT.md](DEPLOYMENT.md) và [HANDOFF.md](HANDOFF.md) có lịch sử triển khai/quét AWS trước đây; inventory rỗng hoặc bằng chứng của revision cũ không xác minh rule mới hay finding thật của lượt Task 7 này. Không lấy các vấn đề trong preflight cũ (ví dụ reserved concurrency đã được bỏ) làm blocker code hiện tại.

## Gia cố metric RDS/NAT/ALB/NLB — 26/10/2026

Phạm vi: kiểm tra tính hợp lệ của mẫu, độ phủ, ngưỡng và công thức NAT trong helper thuần, cùng đường collector → worker → DynamoDB mô phỏng. Không đổi API, UI, IAM hoặc triển khai AWS.

- **Trước sửa:** tái hiện RDS CPU âm và NLB flow âm bị `REVIEW`; ALB nhận NaN trả `OK` với evidence NaN; mẫu `None`/chuỗi/số nguyên cực lớn có thể gây lỗi tính toán. NAT có 24 mẫu source và 20 mẫu destination, mỗi mẫu 0.48 MiB, bị tính thành 1.056 thay vì 0.96 MiB/giờ.
- **Regression mới:** 13 phương thức test rule và 2 phương thức test workflow, dùng subtest cho từng metric, dữ liệu âm/boolean/None/chuỗi/dict/NaN/±infinity/số nguyên gây overflow; mẫu lỗi vẫn bị từ chối khi đã có đủ mẫu hợp lệ. Kiểm tra zero thật, từng chuỗi ở mốc 19/20 mẫu trong 24 giờ và 134/135 mẫu trong 168 giờ, ngưỡng trước/bằng/sau, p95 RDS, mean ALB/NLB và overflow tổng.
- **NAT:** trung bình từng chiều theo số mẫu thực đo, cộng rồi đổi MiB/giờ. Test cả hoán đổi số mẫu hai chiều và trường hợp ở dưới/bằng/trên ngưỡng.
- **Workflow mock/Moto:** 14 lượt scan cho dữ liệu lỗi ở bốn loại, cùng 2 lượt scan NAT 24/20 và 20/24 mẫu. Finding lỗi metric được lưu là `INSUFFICIENT_DATA`; kết quả không có NaN/infinity khi serialize bằng `json.dumps(..., allow_nan=False)`.
- **Suite backend local:** chạy 112 test, **111 PASS, 1 SKIPPED** (AWS E2E bị tắt có chủ đích), 0 failure/error. Số test phương thức không bao gồm số lượng subtest bên trong.
- **Review độc lập:** đối chiếu diff/caller và kiểm tra thêm bằng snippet rule thuần; không phát hiện lỗi chặn trong phạm vi này.

Lệnh đã chạy từ root; `CRG_AWS_E2E` chỉ được đặt bằng `0` trong tiến trình test này:

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -c "import os, unittest; os.environ['CRG_AWS_E2E'] = '0'; suite = unittest.defaultTestLoader.discover('tests'); result = unittest.TextTestRunner(verbosity=1).run(suite); raise SystemExit(not result.wasSuccessful())"
```

Đây là bằng chứng local/mock/Moto, chưa xác minh CloudWatch metrics hoặc scan trên AWS thật. Các trạng thái AWS E2E bên dưới vẫn chưa được nâng thành PASS. Không chạy lại UI/SAM vì không thay đổi các lớp đó.

## Mục 7 & Nhánh main — luật đánh giá, collectors và bằng chứng, 18/10/2026

Kiểm tra tích hợp giữa nhánh `duc` (luật đánh giá, lịch quét, xử lý lỗi, dashboard) và nhánh `origin/main` (API, collectors chỉ đọc AWS, feedback lifecycle, IAM và kiểm thử mở rộng). Toàn bộ dữ liệu AWS đọc và SES được mock; DynamoDB được mô phỏng bằng Moto. Không gọi AWS thật, không triển khai hoặc thay đổi tài nguyên cloud.

Các kiểm tra tại môi trường phát triển:
- **Toàn bộ backend:** 95/95 unittest PASS (36 rule tests, 21 API tests, 33 workflow tests, 2 contract tests, 1 test AWS E2E skipped).
- **Rule & Collectors:** Có collector cho 9 loại tài nguyên (EC2, EBS, EIP, Snapshot, RDS, NAT, ALB, NLB, S3 multipart). Bản ghi tổng hợp cũ này không chứng minh mọi helper mở rộng đã xử lý đầy đủ mẫu không hợp lệ hoặc NAT đã tính riêng từng chiều; các regression và sửa lỗi tương ứng được xác minh tại mục 26/10/2026 ở trên. Các kiểm tra khác gồm snapshot/AMI IncludeDisabled, rule_id và recommendation.
- **Feedback & Ngoại lệ:** Feedback lifecycle (/feedback GET & PUT), acknowledged, kept, ignoreUntil; tương thích ngược API /keep và /ignore nội bộ; tag guardian:keep=true.
- **Cấu hình số lớn:** Ngưỡng nhận ±10**400 bị từ chối bằng ValueError/HTTP 400, không ghi DynamoDB, không gây OverflowError; window_hours hỗ trợ 24–168 giờ.
- **UI smoke:** PASS với demo cục bộ (dashboard, filters, feedback hide/list/clear, ignore, settings 24/168 giờ, email, mobile 390px, session expired).
- **UI acceptance:** PASS với fixture cục bộ (ui_redesign.py).

Status vocabulary:

- `LOCAL MOCK`: exercised locally with mocked target-account AWS reads and Moto DynamoDB.
- `AWS E2E`: exercised against a deployed stack and real target-account resources.
- `SKIPPED`: permitted only for optional AWS scanners, with an approved exact reason.
- `NOT RUN`: no evidence exists; never equivalent to pass.

## Current branch evidence

| Surface | Status | Evidence / limit |
|---|---|---|
| Pure rules and settings bounds | LOCAL MOCK | `tests/test_rules.py`; includes 80% coverage boundary, real zero, missing series and strict S3 age |
| Tenant/auth/API/feedback/pagination | LOCAL MOCK | `tests/test_api.py`, `tests/test_workflows.py`; mocked JWT claims and Moto DynamoDB, not real Cognito/API Gateway |
| EC2/EBS/EIP/Snapshot collectors | LOCAL MOCK | Inventory, metric, observation, cap, partial and time-budget paths use mocked target-account clients |
| S3 multipart collector | LOCAL MOCK | Bucket/upload pagination, structured upload identity and >7 day rule use direct S3 mocks |
| RDS/NAT/ALB/NLB collectors | LOCAL MOCK | Missing metrics, real zeros, REVIEW and denied-service isolation use mocked clients |
| Read-only IAM/API invariant | LOCAL MOCK | `tests/test_read_only.py` parses both target-role templates and `template.yaml` semantically |
| Browser feedback workflow | LOCAL MOCK | `tests/ui_smoke.py` exercises hide, GET feedback, clear and reappearance against `demo.py` |
| Cognito admin-only, <=5 users | NOT RUN | Template is checked locally; actual UserPool change set and `ListUsers` require manual release gate |
| EC2 real finding | NOT RUN | Required before release |
| EBS real finding | NOT RUN | Required before release |
| EIP real finding | NOT RUN | Required before release |
| Snapshot real finding | NOT RUN | Required before release |
| Stale S3 multipart real finding | NOT RUN | Required before release; initiating or aborting an upload is an AWS mutation |
| RDS real finding | NOT RUN | May become `SKIPPED` only with `RESOURCE_NOT_AVAILABLE` or `COST_NOT_APPROVED` |
| NAT Gateway real finding | NOT RUN | May become `SKIPPED` only with `RESOURCE_NOT_AVAILABLE` or `COST_NOT_APPROVED` |
| ALB real finding | NOT RUN | May become `SKIPPED` only with `RESOURCE_NOT_AVAILABLE` or `COST_NOT_APPROVED` |
| NLB real finding | NOT RUN | May become `SKIPPED` only with `RESOURCE_NOT_AVAILABLE` or `COST_NOT_APPROVED` |
| Wrong ExternalId and two-tenant isolation on AWS | NOT RUN | Required manual evidence; local mocks are insufficient |
| Denied service gives PARTIAL on AWS | NOT RUN | Required manual evidence |
| Missing AWS metric is not REVIEW | NOT RUN | Required manual evidence; empty inventory does not prove this rule |
| SES | NOT RUN | Default off, optional, and excluded from the release gate |

## Local branch gate

Run from the repository root:

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests demo.py
node --check web/app.js
cfn-lint template.yaml target-role.yaml web/target-role.yaml
cmp target-role.yaml web/target-role.yaml
sam validate --lint --region ap-southeast-1
sam build
python tests/ui_smoke.py
```

The AWS harness is skipped by default. It requires all five inputs plus explicit enablement:

```bash
CRG_AWS_E2E=1 python -m unittest discover -s tests -p 'test_aws_e2e.py' -v
```

Required variables: `CRG_AWS_E2E_API_URL`, `CRG_AWS_E2E_ACCESS_TOKEN`, `CRG_AWS_E2E_SECOND_ACCESS_TOKEN`, `CRG_AWS_E2E_MANIFEST`, `CRG_AWS_E2E_EVIDENCE`.

## Manual release gate

A reviewer records commit, stack/account/region, exact template and IAM diff, UserPool replacement assessment, Cognito user count <=5, and the read-only action allowlist. A different authorized executor deploys that reviewed change set and runs `tests/test_aws_e2e.py`. Preserve sanitized scan IDs, timestamps, account, regions, responses/log references and distinct reviewer/executor identities. Never preserve passwords, OTPs, access tokens, access keys, session credentials or presigned URLs.

Release cannot pass without real evidence for EC2, EBS, EIP, Snapshot and stale S3 multipart. RDS/NAT/ALB/NLB may be `SKIPPED` only for `RESOURCE_NOT_AVAILABLE` or `COST_NOT_APPROVED`. Do not create paid resources solely for evidence without separate approval. Do not update `DEPLOYMENT.md` or `HANDOFF.md` until the executor has actual results.
