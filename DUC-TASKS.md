# Task 7–9 của Phạm Sỹ Đức: baseline và hợp đồng triển khai

## 1. Phạm vi và revision

Ngày đối chiếu: **29/10/2026**. Baseline mã nguồn: `main` tại `a2201f5d8261d453d0de3e9873b9072773545848`; nhánh tài liệu Plan 01: `codex/duc-plan-01-baseline`. Đây là baseline checkout cục bộ, chưa phải xác nhận revision đang chạy trên AWS hoặc trạng thái remote mới nhất.

Nhánh triển khai hiện tại là **codex/task-7-finding-observations**. Plan 01–07 đã triển khai local và commit theo tính năng, chi tiết tại VALIDATION.md. Persistence helper/IAM và tích hợp worker/API dùng chung từ Plan 02–03; không phát hành riêng helper Plan 02. Kết quả local mới nhất không xác nhận triển khai AWS.

Nguồn yêu cầu: **Nhóm 9 - Report 2.pdf**, trang 10 (phạm vi MVP), 15–16 (finding, dữ liệu và isolation), 18 (bằng chứng cloud ban đầu), 20 (phân công Task 7–9); cùng các quyết định người dùng đã chốt trong kế hoạch triển khai. Bản báo cáo là nguồn yêu cầu, không tự cấp quyền triển khai hoặc tạo fixture trả phí.

Chỉ thực hiện **Task 7, 8, 9**. Task 13 báo cáo/slide/kịch bản demo được hoãn theo yêu cầu người dùng. Đồng bộ demo local cho thao tác mới trong Plan 06–07 và QA tích hợp Plan 09 thuộc kiểm thử chức năng Task 9.

| Task | Phần việc | Giờ Đức theo Report 2 | Phối hợp theo báo cáo |
|---|---|---:|---|
| 7 | Luật đánh giá, chất lượng dữ liệu và evidence | 28 | Hải 4 giờ |
| 8 | Lịch quét và xử lý lỗi | 24 | Hạ tầng/phiên AWS cần phối hợp người vận hành |
| 9 | Dashboard, bộ lọc, evidence, lịch sử và phản hồi | 24 | Hải 4 giờ QA |
| Tổng | Phạm vi Task 7–9 | **76** | Không phải số giờ còn lại |

MVP gồm **EC2, EBS, EIP, SNAPSHOT, S3_MULTIPART, RDS, NAT_GATEWAY, ALB, NLB** trong bốn nhóm `compute`, `storage`, `database`, `network`. `ELB` là tên thao tác collector, không phải loại finding thứ mười. Mở rộng dịch vụ/cost thuộc kế hoạch tiếp theo của Task 6. Giữ giao diện hiện tại, Lambda Invoke async, SQS failure destination; không bật SES trong đợt nghiệm thu này.

## 2. Checklist yêu cầu, hiện trạng và nghiệm thu

`CÓ CODE` chỉ xác nhận implementation trong baseline. `LOCAL PASS` chỉ áp dụng kiểm thử local/mock/Moto đã chạy ở [VALIDATION.md](VALIDATION.md). Tính năng mới chưa triển khai không được nhận bằng chứng PASS từ test của baseline.

| ID / nguồn yêu cầu | Hiện trạng baseline | Phần còn làm / plan | Điều kiện nghiệm thu và lớp bằng chứng |
|---|---|---|---|
| T7-01 — Report 2 tr. 10, 17, 20: chín loại MVP | CÓ CODE: evaluator thuần, collector và evidence cho chín loại | Giữ contract [RULES.md](RULES.md); phối hợp Task 6 khi thiếu input, không viết lại bộ rule | Local rule/workflow PASS; AWS từng loại theo manifest, Plan 11 |
| T7-02 — tr. 15–17: thiếu dữ liệu, lỗi quyền và truncation | CÓ CODE: không bù zero; metric lỗi/thiếu thành INSUFFICIENT_DATA; lỗi/cắt dữ liệu thành PARTIAL | Rà regression khi thêm timestamp, Plan 02–03 và 09 | Biên ngưỡng, zero/thiếu/lỗi, coverage, cap và isolation; AWS denial/missing metric cần evidence riêng |
| T7-03 — tr. 15: thời điểm đầu/gần nhất quan sát | CHƯA CÓ registry finding chung; hiện có evaluated_at và OBS EBS/EIP riêng | Lưu registry 30 ngày và bổ sung hai trường API, Plan 02–03 | Retry, gap 30 ngày, reconnect, nhiều batch, stale worker, byte cap; sau đó xác minh trên AWS |
| T8-01 — tr. 12–16, 20: manual/scheduled scan, khóa và thời hạn | CÓ CODE: admission, scheduler, lease/run_token, cooldown và deadline | Revalidate bản tích hợp và chạy AWS, Plan 09–10, 12 | Local Task 8 PASS; tick EventBridge thật, duplicate/race/reconnect có RESULT/HISTORY đúng |
| T8-02 — tr. 14–16, 20: lỗi, retry và SQS failure destination | CÓ CODE: RESULT + HISTORY nguyên tử, recovery/reconcile, queue/redrive | Nghiệm thu retry/timeout/recovery trên stack thử riêng, Plan 12 | Oracle runtime/log/SQS theo [TASK8-AWS.md](TASK8-AWS.md); phục hồi artifact cuối và final-smoke |
| T9-01 — tr. 7–9, 20: phạm vi, bộ lọc, cấu hình | UI có bốn loại và 6/11 setting; chưa gửi service_groups | Bốn group, chín type, đủ 11 setting, region/level/ack filter, Plan 04 | Save/reload đúng, filter kết hợp, PARTIAL không bị hiểu là quét đủ; browser fixture rồi AWS |
| T9-02 — tr. 8–9, 15: lý do, bằng chứng và khuyến nghị | API có rule/recommendation/evidence; UI mới trình bày một phần | Detail dùng chung findings/history, Plan 05 | Đủ chín loại, số 0 thật, dữ liệu cũ/thiếu và ID dài; mốc mới chỉ hiện khi có |
| T9-03 — tr. 7–9, 18, 20: đã xem/giữ/bỏ qua | Backend đủ cờ; UI chỉ bỏ qua 7 ngày; feedback thiếu nhãn resource | Metadata do backend lấy và thao tác đầy đủ, Plan 06–07 | Refresh/scan tiếp/clear/expiry, cờ độc lập, candidate còn lưu, history không đổi; web thật Plan 11 |
| T9-04 — tr. 16, 20: danh sách có phân trang và lịch sử | API có cursor; UI chỉ lấy trang history đầu và chưa quản lý feedback | Tải thêm, retry và detail scan, Plan 07–08 | Hơn 20 history/feedback, nhiều region, không trùng hàng, giữ dữ liệu khi trang sau lỗi |
| T9-05 — tr. 20: QA | Có demo và browser fixture; demo chưa đủ chín loại/ack/pagination/reconnect | Đồng bộ demo, fixture và kiểm tra độc lập, Plan 09 | Desktop 1440, tablet 768, mobile 390/320; keyboard/focus/loading/error và ảnh QA |

Report 2 trang 18 chỉ ghi nhận EBS OBSERVING ngày 26/10 và nêu các ca REVIEW/Keep/Un-ignore chưa kiểm chứng. Đó là bằng chứng lịch sử do nhóm cung cấp, không xác nhận AWS acceptance của baseline này hoặc các tính năng chưa triển khai.

## 3. Hợp đồng timestamps chốt cho Plan 02–03

**Baseline chưa có; Plan 02–03 đã có persistence helper/IAM và tích hợp worker/API, chưa triển khai AWS.** Nguồn implementation là [src/app.py](src/app.py) và IAM trong [template.yaml](template.yaml); collector/rule giữ nguyên. Evaluator trong [src/rules.py](src/rules.py) tiếp tục thuần. Worker gắn timestamps vào finding trước feedback/cap; API trả ISO UTC cho kết quả quét mới, không backfill history cũ.

- Registry dùng `pk = TENANT#<sub>`, `sk = OBSF#<connection_version>#<region>#<finding_id>`; lưu `first_seen_at`, `last_seen_at` dạng epoch UTC và `expires = last_seen_at + 30 * 86400`. API finding trả hai trường cùng tên dạng ISO UTC; không tạo endpoint mới và không công bố registry thô.
- Mốc lấy từ `evaluated_at` của finding thực sự thu thập, gồm REVIEW/OBSERVING/INSUFFICIENT_DATA, trước legacy feedback/suppression tại app và trước cap candidate/result. Deduplicate finding_id trước đọc/ghi. Collector không tạo candidate vì OK hoặc tag suppression thì không làm mới mốc finding.
- Khi chưa có registry hoặc `expires <= observed_at`, khởi tạo cả hai mốc từ observation mới. Nếu còn hạn, giữ first và đặt last bằng `max(old_last, observed_at)`. Vắng finding, scan lỗi/PARTIAL, Keep/Ignore không xóa/reset registry; không có observation mới thì không gia hạn TTL. First có thể cũ hơn 30 ngày nếu finding vẫn được quan sát; 30 ngày là khoảng không quan sát, không phải tuổi tối đa của first.
- Connection mới dùng key mới. Không backfill HISTORY hoặc suy first từ tuổi tài nguyên, observation window hay lịch sử cũ. Registry bắt đầu từ observation đầu sau triển khai; dữ liệu cũ thiếu trường hiển thị **Chưa có dữ liệu**, kèm giải thích mốc chưa được ghi nhận trong detail Plan 05.
- Registry này khác `OBS#...` của EBS/EIP: giữ nguyên cửa sổ orphan, reset khi sử dụng lại/gap trên 48 giờ và TTL observation hiện tại. Timestamp finding không chứng minh tài nguyên idle liên tục hoặc tạo từ thời điểm đó.
- BatchGet tối đa 100 key, strong read; retry hữu hạn cho UnprocessedKeys theo cấu hình SDK hiện có và time budget. Nếu còn key chưa đọc được, truyền lỗi để retry scan, không coi chúng là record mới.
- Mỗi transaction ghi tối đa 98 registry item cùng hai ConditionCheck: marker RUNNING đúng scan/version/run_token, lease/deadline còn hạn; profile còn đúng connection/region. Kiểm tra time budget trước từng batch; mất ownership thì dừng worker cũ. Có thể cần nhiều hơn hai batch khi collector tạo trên 100 finding.
- Quyền đọc bổ sung là `dynamodb:BatchGetItem` chỉ trên bảng platform cho **ScanRole**, policy `guardian-worker` (tên resource thực tế của worker role). Không mở quyền target role hoặc thêm production dependency.
- Registry ghi nhận observation đã thu thập; batch đã commit vẫn hợp lệ nếu batch sau hoặc terminal commit lỗi. Giữ RESULT + HISTORY nguyên tử và guard hiện có; timestamps phải được tính trong cap 300 KiB, 100 candidate/50 hiển thị vẫn áp dụng.

Interface Plan 02: `record_finding_observations(marker, findings, time_check)` nhận marker đang RUNNING đã có scan/version/token/lease/deadline và danh sách finding có evaluated_at aware UTC; trả map finding_id → first/last epoch, `{}` khi không có finding, `None` khi mất ownership. Registry CAS conflict còn ownership và lỗi hạ tầng truyền ClientError để caller retry; lỗi dữ liệu đầu vào/registry bị từ chối bằng ValueError. Plan 03 phải dừng worker khi nhận None, không công bố kết quả thiếu ownership; không được lấy `{}` làm tín hiệu mất quyền. Snapshot read/write conflict được xử lý bằng retry toàn scan, đọc lại dữ liệu mới.

BatchGet retry UnprocessedKeys tối đa 3 request/batch, backoff 0.1/0.2 giây; time_check trước request, sau backoff và trước từng write transaction. Registry đã đọc cần CAS đủ first/last/expires; record hết hạn còn tồn tại không được coi là missing, và TTL xóa giữa đọc/ghi phải dẫn đến retry. Lượt đọc sau lỗi không để lại write sớm vì helper đọc hết trước khi ghi. Test dùng 205 ID để kiểm tra ít nhất ba batch đọc/ghi.

Regression bắt buộc: hai scan/đổi level, finding vắng rồi trở lại, boundary đúng 30 ngày và TTL chưa dọn, reconnect/tenant/region, dedup và nhiều batch, UnprocessedKeys còn sót, timeout giữa batch, worker cũ, retry/terminal failure và last không lùi.

## 4. Hợp đồng feedback/evidence dùng chung backend, demo và UI

### API feedback và metadata hiển thị

Nguồn hiện hành: [src/app.py](src/app.py) và [RULES.md](RULES.md). Metadata backend và thao tác current finding đã triển khai trong **Plan 06**; khu vực quản lý feedback, bỏ giữ/hủy bỏ qua và phân trang UI đã có trong **Plan 07**. Các mốc này đạt code/local, chưa nghiệm thu AWS.

| Thành phần | Hợp đồng |
|---|---|
| PUT /feedback | Body có region, finding_id và ít nhất một trường acknowledged, kept, ignoreUntil; cờ boolean nghiêm ngặt; không nhận metadata tự khai từ browser |
| Thời hạn ignore | Request ignoreUntil là RFC3339 UTC kết thúc Z, tương lai và tối đa 30 ngày; null để clear. Response/storage ignore_until là Unix seconds, 0 sau clear |
| Cờ thiếu | UI/demo đọc acknowledged hoặc kept chưa có như false; không đổi tên trường wire hiện tại |
| Metadata mới | Backend lấy type, resource_id, account_id, rule_id từ candidate đã xác minh. Giữ metadata cũ nếu candidate không còn; record legacy thiếu metadata dùng finding_id + region, không tự bịa nhãn resource |
| Ownership | JWT sub, connection_version, region và finding_id; finding lạ trả 404. Không dùng resource_id thay identity và không dùng route /keep, /ignore legacy cho UI mới |
| Đã xem | Vẫn hiện kèm acknowledged; cập nhật cờ không tự thay kept/ignore |
| Giữ/bỏ qua | kept hoặc ignore còn hạn ẩn ngay khỏi GET /findings; từng cờ độc lập; hết hạn xét timestamp, không đợi TTL |
| Clear và cap | Chỉ khôi phục candidate còn lưu, trong giới hạn 50 hiển thị/100 candidate/300 KiB; chưa hiện lại thì giải thích giới hạn hoặc cần scan mới, không báo đã khôi phục chắc chắn |
| History | GET /history và /scans/{id} giữ snapshot; phản hồi mới không viết lại evidence cũ; candidates luôn riêng tư |
| Phân trang | GET /history và /feedback dùng limit 1–100, mặc định 20; response results và next_token. UI giữ cursor opaque, reset khi đổi connection/tải lại; dedup history bằng scan_id + region, feedback bằng region + finding_id; lỗi trang sau giữ hàng đã tải và cho retry |

### Evidence và catalog UI

- Dùng các field hiện có: type/resource_id/account_id/region/finding_id/rule_id/level/reason/recommendation/evaluated_at và evidence. Metric evidence giữ window/thresholds/units/sample counts/required samples/coverage/data issues; collector đã bổ sung observation_start/end/period/statistics. Hai mốc mới chỉ được dùng sau Plan 03.
- Detail chung cho current finding và history: không biến evaluated_at hoặc observation window thành first/last, không thay unknown bằng 0, hiển thị text an toàn khi ID/reason dài. Dữ liệu history cũ thiếu trường vẫn đọc được.
- Catalog: compute → EC2; storage → EBS/SNAPSHOT/S3_MULTIPART; database → RDS; network → EIP/NAT_GATEWAY/ALB/NLB. Một account hiện tại/user, không tự tạo UI nhiều account.
- Mười một setting và bounds/type lấy từ [RULES.md](RULES.md) và LIMITS trong rules.py; window_hours áp dụng chung EC2/RDS/NAT/ALB/NLB. S3 multipart giữ ngưỡng cố định trên 7 ngày, không thêm setting thứ mười hai.
- [demo.py](demo.py) và fixture phải mô phỏng cùng semantics acknowledge/keep/ignore/clear/expiry, cursor trên 20 item, service_groups và reconnect đổi version. UI chỉ báo thành công sau API thành công; refresh/scan tiếp vẫn nhất quán. Demo/fixture là bằng chứng local, không thay AWS.

## 5. Thứ tự các lượt thực hiện

**Mỗi lượt chọn một plan, hoàn tất thì báo cáo tóm tắt và dừng; phải có yêu cầu mới trực tiếp từ người dùng mới thực hiện plan tiếp theo.** Người dùng đã yêu cầu Plan 07; không tự chuyển sang Plan 08 khi Plan 07 xong. Plan 01 chỉ thay tài liệu kỹ thuật; Plan 02–03 dùng chung nhánh và chỉ phát hành khi cả hai đạt. Plan 01 không thực hiện code/cloud của các plan sau.

**Quy ước commit người dùng yêu cầu ngày 30/10/2026:** sau mỗi phần quan trọng đã hoàn tất và qua kiểm tra liên quan, tạo commit theo phạm vi trước khi bàn giao; không để dồn nhiều plan chưa commit. Kiểm tra staged paths và giữ riêng thay đổi cục bộ không thuộc task. Commit là thao tác local; push/PR theo yêu cầu riêng. Các Plan 01–05 đã tích lũy được bàn giao bằng hai commit code và một commit tài liệu; xem mốc commit ở [VALIDATION.md](VALIDATION.md). Quy ước chờ yêu cầu trước plan tiếp theo giữ nguyên.

Tên commit mô tả hành vi/tính năng, không thêm số Plan hoặc hậu tố tên Plan theo yêu cầu mới của người dùng. Không đổi lại commit cũ.

| Plan | Đầu ra | Phụ thuộc | Trạng thái tại Plan 01 |
|---|---|---|---|
| 01 | Baseline, checklist và hợp đồng trong tài liệu này; validation tương ứng | Không | Đã đối chiếu; kiểm tra tài liệu ghi ở VALIDATION.md |
| 02 | Registry DynamoDB và regression ownership/retention/batch | 01 | ĐÃ CÓ persistence helper + IAM; kiểm chứng local ở VALIDATION.md, chưa phát hành |
| 03 | Worker/API first_seen_at, last_seen_at; tương thích history | 02 | ĐÃ TÍCH HỢP; kết quả kiểm thử local ở VALIDATION.md, chưa deploy |
| 04 | Phạm vi, chín loại, đủ setting và bộ lọc | 01 | ĐÃ TÍCH HỢP UI/demo scope; kiểm thử local ở VALIDATION.md, chưa deploy |
| 05 | Chi tiết evidence dùng chung | 03–04 | ĐÃ TÍCH HỢP cho current/history; kiểm thử local ở VALIDATION.md, chưa deploy |
| 06 | Thao tác phản hồi và metadata backend | 05 | ĐÃ TÍCH HỢP UI/backend/demo; kiểm thử local ở VALIDATION.md, chưa deploy |
| 07 | Quản lý phản hồi ẩn, clear và phân trang | 06 | ĐÃ TÍCH HỢP UI/demo; API hiện có được kiểm chứng bằng regression local, chưa deploy |
| 08 | History phân trang và chi tiết scan | 05 | CHƯA TRIỂN KHAI |
| 09 | Đồng bộ demo/fixture và QA tích hợp | 03–08 | CHƯA CHẠY cho tính năng mới |
| 10 | Artifact đã pin, manifest, review và triển khai stack thử | 09 | CHƯA XÁC MINH đầu vào AWS |
| 11 | Rule và web thật trên hai tenant | 10 | CHƯA CHẠY AWS |
| 12 | Scheduler/retry/timeout/recovery và final-smoke | 10 | CHƯA CHẠY AWS |

Thứ tự phụ thuộc: 01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 12. Dù kỹ thuật cho phép một số phần song song, chỉ bắt đầu plan khác sau yêu cầu của người dùng. Plan 11 chạy trước 12 để fault injection không ảnh hưởng evidence rule/UI.

## 6. Bằng chứng và điều kiện cloud

Bằng chứng mới của Plan 01 và trạng thái B1–B4/D1 nằm ở [VALIDATION.md](VALIDATION.md); hợp đồng điều phối ở [TASK8.md](TASK8.md), scenario/oracle ở [TASK8-AWS.md](TASK8-AWS.md). Không suy phiên AWS hiện tại từ snapshot credentials ngày 26/10, cũng không suy deployment từ merge commit.

- EC2/EBS/EIP/snapshot/S3 multipart cần evidence AWS thật; RDS/NAT/ALB/NLB chỉ SKIPPED với RESOURCE_NOT_AVAILABLE hoặc COST_NOT_APPROVED. EBS/EIP REVIEW phải đủ thời gian quan sát theo cấu hình, mặc định 24 giờ; không chỉnh timestamp để ký nghiệm thu rule.
- Stack fault riêng cloud-resource-guardian-task8-test, ap-southeast-1; hai user/read role và SES tắt. Reviewer/executor, change set, artifact hash và phạm vi tài nguyên theo release gate hiện có. Không tạo tài nguyên trả phí ngoài phạm vi được duyệt.
- Tick thật, timeout, exhausted retry, SQS/recovery/redrive có oracle từng ca. Sau fault phải khôi phục hash/handler, kiểm tra cấu hình và final-smoke trên artifact cuối không wrapper. Ca manual chưa chạy giữ trạng thái riêng.
- Phân biệt PASS, FAIL, CHƯA CHẠY, THIẾU ĐẦU VÀO, CHƯA XÁC MINH và SKIPPED. Không gọi test local là CI hoặc AWS E2E; không đánh dấu toàn bộ Task 7–9 hoàn tất từ Plan 01.

## 7. Điều kiện đóng Plan 01

- [x] Ghi baseline SHA/branch và giữ nguyên AGENTS.md cục bộ; source/runtime/template không đổi.
- [x] Checklist Task 7–9 ánh xạ Report 2, code hiện tại, phần cần làm và lớp bằng chứng; Task 13 được hoãn.
- [x] Chốt hợp đồng timestamps, feedback, evidence và tương thích backend/demo/UI; đánh dấu phần chưa triển khai.
- [x] Gỡ D1 chờ merge theo Git, giữ B1–B4 ở trạng thái cloud thực tế chưa xác minh/chưa chạy.
- [x] Chạy baseline backend, kiểm tra tài liệu gồm file mới, JS/template/whitespace; review tài liệu độc lập và kết quả ghi tại VALIDATION.md.

**Plan 01 hoàn tất ở lớp tài liệu kỹ thuật và baseline local.** Kết quả Plan 02 cập nhật ở mục dưới; chưa đóng nghiệm thu tính năng mới hoặc AWS của Task 7–9.

## 8. Bàn giao Plan 02

Đây là snapshot lúc bàn giao Plan 02; trạng thái tích hợp mới ở mục Plan 03 bên dưới.

- Tại mốc Plan 02, helper persistence và IAM nằm cùng nhánh dành cho Plan 02–03; chưa gọi từ worker, API, collector hoặc demo.
- Regression ở [tests/test_finding_observations.py](tests/test_finding_observations.py) kiểm tra retention, isolation, batch/retry, CAS và time budget; [tests/test_task8_template.py](tests/test_task8_template.py) khóa quyền batch-read chỉ ScanRole/bảng platform.
- Kết quả chạy và hash working tree nằm ở [VALIDATION.md](VALIDATION.md). Plan 03 tiếp tục nối helper trước suppression/cap, gắn ISO timestamps, kiểm tra byte cap và snapshot/API tương thích; chỉ phát hành khi cả Plan 02–03 đạt.
- Task 13 tiếp tục hoãn. AWS B1–B4 chưa được xác minh/chạy trong lượt Plan 02, không suy deployment từ mã/helper/IAM đã có.

**Plan 02 đạt phạm vi persistence local:** 24 regression registry và invariant IAM mới đạt trong full suite 241 test (240 PASS, 1 AWS E2E SKIPPED). Kết quả này không chứng minh worker/API đã trả timestamps. Bước tiếp theo là Plan 03 trên cùng nhánh.

## 9. Bàn giao Plan 03

- Worker gọi registry ngay sau collector, trước legacy suppression/feedback và cap; nhận None thì dừng, còn map rỗng vẫn cho phép kết quả scan rỗng hợp lệ. Findings được sao chép trước khi thêm first_seen_at/last_seen_at ISO UTC, không sửa dữ liệu collector hoặc backfill history.
- Budget registry chừa 10 giây cho finalization, khác ngưỡng collector dự trữ 60 giây; PARTIAL có dữ liệu ở ngưỡng 59 giây vẫn lưu được mốc. Không còn budget thì terminal TIMED_OUT/TIME_BUDGET bằng guard run_token; lỗi hạ tầng/CAS truyền ra để retry.
- Marker legacy thiếu deadline_at được claim với mốc cố định từ marker gốc, không kéo dài khi retry. Registry đã commit giữ được first nếu terminal RESULT + HISTORY lỗi; transaction terminal không đổi.
- Regression tích hợp ở [tests/test_finding_observation_workflow.py](tests/test_finding_observation_workflow.py), cùng test chín loại/cap/API/notification hiện có. Kết quả cuối và hash working tree ở [VALIDATION.md](VALIDATION.md); local không thay AWS acceptance.
- Chưa thực hiện UI mới, metadata feedback, artifact/deployment hoặc Task 13. Sau khi bàn giao Plan 03, **dừng và chờ người dùng yêu cầu Plan 04**.

**Plan 03 đạt phạm vi tích hợp local:** full suite 255 test (254 PASS, 1 AWS E2E SKIPPED), có 14 regression tích hợp mới và các kiểm tra chín loại/API/byte cap/notification. Plan 02–03 chưa commit/push hoặc deploy; không lấy kết quả local làm AWS acceptance.

## 10. Bàn giao Plan 04

- Giao diện chọn/lưu một đến bốn service group, hiển thị nhóm trong account scope; catalog chín loại và sáu control lọc kết hợp AND. Bộ lọc không xóa cảnh báo PARTIAL/lỗi/unknown khi kết quả rỗng.
- Form có đủ 11 setting, bounds/type trùng backend, decimal step=any và integer step=1; nhãn cửa sổ chung năm loại metric, không thêm ngưỡng S3. Save/reload lấy trạng thái từ API.
- Demo đồng bộ group validation/filter/counts, lưu cấu hình và reset phiên kết nối/version/pending/history/feedback đúng phạm vi. Bộ dữ liệu vẫn bốn loại, không quảng bá demo đã có đủ chín loại; phần đó thuộc Plan 09.
- Chặn response findings/history của kết nối cũ về sau scope mới bằng generation guard; bỏ cả success/error cũ, xóa history/filter và hủy poll khi init mới. Review đã tái hiện lỗi trước sửa và kiểm tra lại sau sửa.
- Regression ở [tests/ui_scope_filters.py](tests/ui_scope_filters.py), fixture hiện có [tests/ui_redesign.py](tests/ui_redesign.py), demo smoke và [tests/test_demo_scope.py](tests/test_demo_scope.py). Evidence, ảnh và hash bản kiểm thử ở [VALIDATION.md](VALIDATION.md); không chạy AWS hoặc đổi backend schema/IAM trong Plan 04.
- Detail evidence, các nút feedback mới, history pagination và Task 13 chưa thực hiện. **Dừng sau Plan 04 và chờ yêu cầu trực tiếp cho Plan 05.**

**Plan 04 đạt phạm vi local:** full suite 263 test (262 PASS, 1 AWS E2E SKIPPED); demo smoke, UI fixture trạng thái và UI fixture scope/filter đều PASS trên bản cuối. Fixture chín loại kiểm tra 11 setting, sáu bộ lọc, reconnect/stale response và 320/390/768/1440px, không có page/fixture error. Ảnh, giới hạn demo và hash đã kiểm thử ở [VALIDATION.md](VALIDATION.md). Chưa commit/push/deploy hoặc đóng nghiệm thu AWS.

## 11. Bàn giao Plan 05

- Nút Xem chi tiết từ tổng quan, findings và history mở chung native dialog. Thông tin identity/rule/reason/recommendation/evaluated_at/first/last và evidence chín loại lấy từ snapshot đã chọn; không dùng profile/settings hiện tại để điền lịch sử.
- Metric evidence có window/start/end/period, ngưỡng, đơn vị/thống kê, sample counts/coverage/diagnostics. EBS/EIP dùng thời gian quan sát; snapshot có phạm vi đối chiếu AMI và dung lượng logic; S3 hiển thị bucket/key/upload ID và ngưỡng lớn hơn bảy ngày.
- Dữ liệu thiếu hiện Chưa có dữ liệu; giữ số 0, boolean false và ý nghĩa array rỗng. Không sửa/backend backfill snapshot cũ hoặc thay đổi schema. Demo bốn loại thiếu metadata tiếp tục đọc được.
- Nội dung dài wrap trong dialog, phần bảng tóm tắt ba dòng. Hỗ trợ Escape/keyboard; focus quay về finding hiện tại sau polling thay opener hoặc control phù hợp nếu finding không còn. Tự đóng khi navigation/init/reconnect/logout/401.
- Regression ở [tests/ui_finding_details.py](tests/ui_finding_details.py); [ui_smoke.py](tests/ui_smoke.py) chọn nút ignore theo tên vì bảng có thêm nút chi tiết. Kết quả/ảnh/hash local ở [VALIDATION.md](VALIDATION.md); không sửa backend/demo/IAM hoặc chạy AWS trong lượt này.
- Task 13 tiếp tục hoãn. **Dừng sau Plan 05, chờ yêu cầu trực tiếp cho Plan 06; chưa thực hiện các nút feedback mới.**

**Plan 05 đạt phạm vi local:** fixture chi tiết PASS với 10 nhóm kiểm tra/25 request/0 page hoặc fixture error và 12 ảnh; ba bộ UI smoke/trạng thái/scope đều PASS trên bản cuối. Review độc lập đóng lỗi focus bằng 6 Chrome probe. Không chạy lại full backend vì không đổi backend/demo/template; bằng chứng và hash ở [VALIDATION.md](VALIDATION.md). Chưa commit/push/deploy hoặc nghiệm thu AWS.

## 12. Bàn giao Plan 06

- Finding hiện tại/priority có Đánh dấu đã xem/Bỏ đã xem, Giữ lại, Bỏ qua 1–30 ngày mặc định 7. Ack vẫn hiện; keep/ignore ẩn sau thành công. Payload chỉ identity + một cờ, không gửi metadata và không sửa history.
- Pending/error/ngày chọn dùng chung theo finding ID/region, giữ qua polling; khóa thao tác trùng và hỗ trợ thử lại khi PUT lỗi. Save thành công nhưng tải lại lỗi được báo riêng. Loại GET cũ sau save và PUT/error cũ sau reconnect; hết phiên về login, không báo lưu thành công giả.
- Backend enrich bốn metadata từ candidate đã xác minh, giữ metadata cũ khi thiếu/mất candidate; legacy vẫn dùng ID/region. Demo dùng candidate snapshot/overlay, validate payload, ID theo region; không thêm metadata giả hoặc mở scope chín loại mẫu.
- Full suite **287 test: 286 PASS, 1 AWS E2E SKIPPED**; có 12 metadata + 12 demo regression mới. Browser feedback **11 nhóm PASS/107 request/34 PUT**, 0 page/fixture error; bốn bộ UI hiện có đều PASS, tám ảnh feedback tại bốn chiều rộng. Review độc lập không còn blocker local.
- Code đã commit theo tính năng; SHA, hash và bằng chứng ở [VALIDATION.md](VALIDATION.md). Chưa push/deploy/AWS/CI, Task 13 tiếp tục hoãn. **Dừng sau Plan 06; cần yêu cầu trực tiếp để làm Plan 07.**

## 13. Bàn giao Plan 07

- Khu vực Đang giữ và bỏ qua nằm dưới danh sách findings, lấy GET /feedback theo trang 20 record, cursor opaque, dedup theo region/finding ID. Có thể tải hơn 20 feedback; trang toàn ack-only không bị coi là hết các finding đang ẩn khi còn cursor.
- Bỏ giữ chỉ gửi kept:false, hủy bỏ qua chỉ gửi ignoreUntil:null, đổi hạn 1–30 ngày chỉ gửi ignoreUntil mới. Các cờ khác/acknowledged giữ nguyên; history không bị viết lại. Record legacy thiếu metadata dùng finding ID và region.
- Fresh GET /findings xác minh hiển thị sau clear; còn cờ ẩn thì giải thích cờ còn lại, không thấy finding thì báo cần quét mới/có thể vượt giới hạn. Không suy chắc candidate đã mất hoặc tự tạo candidate.
- Pending/retry dùng chung theo identity; lỗi trang sau giữ các trang đã tải và cursor. Request/revision/generation guard ngăn GET cũ khôi phục cờ sau PUT hoặc trộn scope cũ. Keyboard giữ focus khi load-more bị ẩn/disabled hoặc control của record bị thay.
- Demo pagination ràng buộc cursor với route/kết nối/identity, reset sau reconnect; chỉ mở feedback pagination, chưa mở history pagination. Không sửa backend/API/IAM của production.
- Full suite **302 test: 301 PASS, 1 AWS E2E SKIPPED**; có 6 backend-contract + 9 demo-pagination regression mới. Sáu bộ browser PASS; fixture quản lý **14 nhóm/101 request/13 PUT**, 0 page/fixture error, 6 ảnh. Hai lỗi P2 từ review (selector cùng identity, focus trang cuối) đã đóng và có regression.
- Commit feature, bằng chứng và hash tại [VALIDATION.md](VALIDATION.md). Chưa push/deploy/AWS/CI; Task 13 vẫn hoãn. **Dừng sau Plan 07, chờ yêu cầu Plan 08.**
