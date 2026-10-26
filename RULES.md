# Task 7 — Luật đánh giá và bằng chứng

## 1. Phạm vi nghiệm thu

Phạm vi người dùng đã chốt: toàn bộ rule/evidence cho **chín loại tài nguyên có collector hiện tại**: EC2, EBS volume, Elastic IP, EBS snapshot, S3 multipart upload, RDS instance, NAT Gateway, ALB và NLB. Đây là phạm vi backend Task 7; việc hiển thị đủ evidence và thao tác trên dashboard thuộc Task 9.

Báo cáo PDF định hướng sáu nhóm dịch vụ và đối chiếu dữ liệu chi phí. Chín loại trên nằm trong bốn nhóm `compute`, `storage`, `database`, `network`; chưa bao phủ mọi dịch vụ trong bốn nhóm, hai nhóm AI/analytics và giám sát/tích hợp, hoặc dữ liệu billing/cost. Các phần này cần collector/input của Task 6 và bộ rule được chốt tiếp; không được đánh dấu hoàn tất theo toàn bộ phạm vi PDF.

`src/rules.py` chứa helper/evaluator thuần, không gọi AWS, database hoặc đồng hồ hệ thống. `src/collectors.py` đọc inventory/metrics, gọi đúng evaluator và bổ sung ngữ cảnh. `src/app.py` quản lý observation, tenant/connection, ngoại lệ, giới hạn và persistence. Rule tạo ứng viên cần người dùng xác minh, không tự dừng/xóa/sửa tài nguyên AWS.

## 2. Danh mục rule và ngưỡng

| Loại / rule_id | Điều kiện và phép tính | Kết quả |
|---|---|---|
| EC2 / `EC2_LOW_UTILIZATION` | Running, tồn tại từ đầu cửa sổ; CPU hourly Maximum → p95 và NetworkIn/Out hourly Sum → trung bình riêng từng chiều | Cả hai dưới ngưỡng: `REVIEW`; thiếu/lỗi dữ liệu hoặc chưa đủ tuổi: `INSUFFICIENT_DATA` |
| EBS / `EBS_UNATTACHED` | Volume available, attachments rỗng; thời gian không dùng từ chuỗi observation | Trước `orphan_hours`: `OBSERVING`; đạt hoặc vượt: `REVIEW` |
| EIP / `EIP_UNASSOCIATED` | Có AllocationId, không AssociationId; chuỗi observation | Trước `orphan_hours`: `OBSERVING`; đạt hoặc vượt: `REVIEW` |
| Snapshot / `SNAPSHOT_OLD_UNREFERENCED` | Completed, tuổi >= `snapshot_days`, không được AMI inventory đầy đủ tham chiếu, không có dấu hiệu AWS Backup | `REVIEW`; không đủ điều kiện thì không tạo finding |
| S3 multipart / `S3_STALE_MULTIPART` | Upload dang dở có tuổi **lớn hơn** 7 ngày | `REVIEW`; đúng 7 ngày chưa cảnh báo; thời điểm khởi tạo thiếu/lỗi: `INSUFFICIENT_DATA` |
| RDS / `RDS_LOW_UTILIZATION` | Available, đủ tuổi cửa sổ; CPUUtilization và DatabaseConnections hourly Maximum → nearest-rank p95 | Cả hai dưới ngưỡng: `REVIEW`; dữ liệu/tuổi chưa đủ: `INSUFFICIENT_DATA` |
| NAT / `NAT_LOW_UTILIZATION` | Available, đủ tuổi; BytesInFromSource và BytesInFromDestination hourly Sum → trung bình riêng mỗi chiều | Tổng MiB/giờ dưới ngưỡng: `REVIEW`; dữ liệu/tuổi chưa đủ: `INSUFFICIENT_DATA` |
| ALB / `ALB_LOW_UTILIZATION` | Active, đủ tuổi; RequestCount hourly Sum → trung bình giờ thực đo | Dưới ngưỡng: `REVIEW`; dữ liệu/tuổi chưa đủ: `INSUFFICIENT_DATA` |
| NLB / `NLB_LOW_UTILIZATION` | Active, đủ tuổi; NewFlowCount hourly Sum → trung bình giờ thực đo | Dưới ngưỡng: `REVIEW`; dữ liệu/tuổi chưa đủ: `INSUFFICIENT_DATA` |

Các rule metric so sánh **thấp hơn** ngưỡng, không dùng giá trị đã làm tròn để quyết định. Bằng ngưỡng trả `OK` nội bộ; evaluator trả `None` khi `OK`, trạng thái không áp dụng, hoặc ngoại lệ tag chặn rule. Collector không công bố finding `OK`.

| Cấu hình | Mặc định | Khoảng cho phép |
|---|---:|---:|
| `cpu_percent` | 5 | 1–50 |
| `network_mib_hour` | 1 | 0.1–100 |
| `window_hours` | 24 | 24–168, nguyên |
| `orphan_hours` | 24 | 1–168, nguyên |
| `snapshot_days` | 30 | 7–365, nguyên |
| `interval_hours` | 6 | 1–24, nguyên |
| `rds_cpu_percent` | 5 | 1–50 |
| `rds_connections` | 1 | 1–1000, nguyên |
| `nat_mib_hour` | 1 | 0.1–10000 |
| `alb_requests_hour` | 1 | 1–1000000, nguyên |
| `nlb_new_flows_hour` | 1 | 1–1000000, nguyên |

`config(value, base=None)` merge partial update trên defaults và cấu hình cũ; từ chối trường lạ, boolean, kiểu sai, NaN/infinity, số nguyên cực lớn hoặc ngoài giới hạn trước persistence. Ngưỡng S3 multipart là 7 ngày cố định, chưa phải cấu hình người dùng.

## 3. Hợp đồng metric và chất lượng dữ liệu

Các helper `idle`, `rds_idle`, `nat_idle`, `alb_idle`, `nlb_idle` đều trả `(status, evidence)`. **Evidence luôn là dictionary**, kể cả `INSUFFICIENT_DATA`; hợp đồng cũ trả `None` ở các helper mở rộng đã được thay thế. Giữ các khóa giá trị tổng hợp cũ khi tính được.

| Trường evidence chung | Ý nghĩa |
|---|---|
| `window_hours`, `thresholds` | Cửa sổ và ngưỡng thực tế dùng để quyết định |
| `metric_units` | Đơn vị đầu vào: CPU `Percent`, network `Bytes`, connections/requests/flows `Count` |
| `sample_counts` | Số mẫu **hợp lệ** của từng metric |
| `received_sample_counts`, `invalid_sample_counts` | Số mẫu đầu vào và số mẫu lỗi; không lưu giá trị lỗi thô |
| `required_samples` | `ceil(window_hours * 0.8)` |
| `missing_metrics` | Metric có số mẫu hợp lệ dưới yêu cầu |
| `invalid_metrics` | Metric có mẫu lỗi hoặc tham gia phép tổng bị overflow |
| `coverage` | Tỷ lệ mẫu hợp lệ nhỏ nhất / số giờ cửa sổ, làm tròn ba chữ số |
| `calculation_errors` | `AGGREGATE_OVERFLOW` khi tổng/trung bình không tính được an toàn; bình thường rỗng |
| `data_issues` | Vấn đề tài nguyên, ví dụ `RESOURCE_TOO_YOUNG`, `MISSING_CREATION_TIME`; bình thường rỗng |

Tên metric: EC2 `cpu/netin/netout`; RDS `cpu/connections`; NAT `source/destination`; ALB `requests`; NLB `flows`.

- Mỗi metric bắt buộc phải đủ mẫu riêng: 20 mẫu cho 24 giờ, 135 mẫu cho 168 giờ. Zero thật là hợp lệ. Không bù giờ thiếu bằng zero.
- Mẫu âm, boolean, None, sai kiểu, NaN/±infinity và số nguyên gây overflow khi kiểm tra hữu hạn là dữ liệu lỗi. Có **bất kỳ** mẫu lỗi nào thì cả rule trả `INSUFFICIENT_DATA`, kể cả khi các mẫu còn lại đã đủ 80%. Không bỏ mẫu lỗi rồi tiếp tục phân loại.
- Giá trị lỗi thô không đi vào evidence; các giá trị tổng hợp NaN/infinity không được công bố. Trạng thái insufficient vẫn có counts, thresholds và lý do chất lượng dữ liệu.
- p95 là phần tử thứ `ceil(0.95 * count)` của dãy tăng dần. Cửa sổ dùng giờ UTC hoàn tất `[start, end)`; instance tạo sau start chưa đủ tuổi dù các metric thấp. Thiếu thời điểm tạo cũng không được kết luận idle.
- Network EC2 và NAT lấy trung bình trên số mẫu thực đo **riêng từng chiều**, cộng rồi chia 1048576. Ví dụ 24 mẫu source và 20 mẫu destination, mỗi mẫu 0.48 MiB, cho 0.96 MiB/giờ. Cách tính không khẳng định các giờ thiếu có mức dùng tương tự.

Khóa giá trị khi tính được: EC2 `cpu_p95`, `network_mib_hour`; RDS `cpu_p95`, `connections_p95`; NAT `nat_mib_hour`; ALB `requests_hour`; NLB `new_flows_hour`.

## 4. Finding và collector

Mỗi finding mới có `finding_id`, `type`, `resource_id`, `region`, `account_id`, `evaluated_at`, `level`, `reason`, `evidence`, `rule_id`, `recommendation`. Collector bổ sung account/region/evaluated_at vào evidence để bằng chứng có thể kiểm tra độc lập. Thời gian là ISO 8601 có timezone UTC, lấy cùng mốc scan, không do evaluator tự đọc đồng hồ.

`finding_id` là SHA-256 của JSON có cấu trúc `[type, region, stable_identity]`, ổn định qua các lượt quét và không phụ thuộc metric/thời gian. Identity dùng ID/ARN theo collector; S3 multipart dùng `[bucket, key, upload_id]`. Tenant và connection được ràng buộc ở partition/key ứng dụng; `resource_id` để hiển thị, không thay thế khóa feedback.

| Loại | Evidence đặc thù bổ sung |
|---|---|
| Các rule metric | `observation_start/end`, `metric_period_seconds=3600`, `metric_statistics`; thời điểm tạo `launch_time` hoặc `created_at` |
| EBS | `size_gib`, `observed_hours`, `threshold_hours`, thresholds orphan |
| EIP | `observed_hours`, `threshold_hours`, thresholds orphan |
| Snapshot | `age_days`, `snapshot_days`, `snapshot_started_at`, `volume_id`, `logical_volume_gib`, `relationships_complete`, `relationship_scope` |
| S3 multipart | `bucket`, `key`, `upload_id`, `initiated_at`, `age_days` khi tính được, `threshold_days=7`, thresholds multipart |
| RDS/NAT/LB | Metadata engine/instance class, VPC/subnet hoặc scheme, cùng diagnostics và giá trị metric tương ứng |

Không gán cửa sổ metric cho EBS/EIP hoặc tuổi snapshot/upload. Thời gian observation không đồng nghĩa tuổi tài nguyên; `logical_volume_gib` không phải dung lượng snapshot tính phí hoặc tiền tiết kiệm.

Chữ ký evaluator thuần:

```python
evaluate_ec2(instance, (cpu, netin, netout), cfg, window_start)
evaluate_ebs(volume, observed_hours, cfg)
evaluate_eip(address, observed_hours, cfg)
evaluate_snapshot(snapshot, referenced_snapshot_ids, relationships_complete, cfg, now)
evaluate_rds(instance, (cpu, connections), cfg, window_start)
evaluate_nat_gateway(gateway, (source, destination), cfg, window_start)
evaluate_load_balancer(load_balancer, (requests_or_flows,), cfg, window_start)
evaluate_s3_multipart(bucket, upload, now)
```

Collector phải gọi các evaluator này, không tự sao chép điều kiện rule. Nó đọc hết các trang metric, khử trùng timestamp, lọc `[start,end)` và giữ zero. Mẫu trong cửa sổ phải nằm trên lưới giờ tính từ start; nhiều điểm trong cùng giờ không được tính thành nhiều giờ quan sát. Response/result ID/status sai, mảng timestamps/values không khớp, timestamp không hợp lệ hoặc lệch lưới giờ, duplicate xung đột và token lặp tạo lỗi theo phạm vi `PARTIAL`; không đổi thành inventory rỗng hay mẫu hợp lệ giả. Mẫu numeric lỗi đi tới evaluator để có diagnostics. Resource còn mới/thiếu thời điểm tạo không cần gọi CloudWatch để biết chưa đủ điều kiện.

Snapshot chỉ được kết luận không tham chiếu khi đọc đủ AMI thuộc account, bao gồm `DescribeImages(Owners=["self"], IncludeDisabled=True)`. Lỗi hoặc truncation AMI gây `PARTIAL` và không tạo snapshot review. Dấu hiệu AWS Backup được bỏ qua; chưa phải kiểm tra đầy đủ retention, mọi quan hệ phụ thuộc hay khả năng khôi phục.

## 5. Ngoại lệ và observation

### Tag và phản hồi nội bộ

- `guardian:keep=true` (giá trị không phân biệt hoa thường) chặn finding ở các collector đang có dữ liệu tag: EC2, EBS, EIP, snapshot, RDS, NAT. ALB/NLB chưa gọi DescribeTags; S3 multipart chưa đọc tag bucket, nên không quảng bá tag suppression cho ba loại này. Giữ lại/bỏ qua nội bộ vẫn áp dụng cho mọi finding có ID.
- `PUT /feedback` nhận `region`, `finding_id`, và subset `acknowledged`/`kept`/`ignoreUntil`. Cờ là boolean; ignore là RFC3339 UTC trong 30 ngày tới hoặc null để bỏ. API kiểm tra ownership của finding trong result/candidate/feedback thuộc tenant, region và connection hiện hành.
- Đã xem vẫn hiện kèm `acknowledged`; kept/ignore còn hạn bị ẩn khỏi `/findings`. Tắt keep không tắt ignore hoặc tag; expiry xét timestamp dù TTL chưa xóa.
- Worker giữ private candidates trước feedback để clear keep/ignore hoặc hết hạn có thể hiện lại ngay sau một lượt quét. `/findings` overlay theo trạng thái hiện hành; `/scans/{id}` và `/history` trả snapshot đã lưu, không viết lại lịch sử theo phản hồi mới. Private candidates không xuất hiện trên API/history.
- Legacy `/keep` và `/ignore` dùng resource ID, áp dụng từ scan sau; không dùng thay `/feedback` cho ARN/S3 URI. Chúng còn trong code tương thích nội bộ, nhưng template HTTP API hiện dùng `/feedback`. Không suy ra route cloud chỉ từ handler tồn tại.

### EBS/EIP

Quan sát cập nhật trước khi ẩn finding bởi tag/keep/ignore/feedback. Không dùng tuổi volume/IP làm thời gian không attach/associate. Lần đầu bắt đầu từ 0; sử dụng lại reset; khoảng trống **trên** 48 giờ reset, đúng 48 giờ tiếp tục. Hết hạn observation hoặc đồng hồ quay ngược bắt đầu cửa sổ mới. Không thể biết chắc trạng thái thay đổi giữa hai lần quét.

Key observation: `OBS#<connection_version>#<region>#<type>#<resource_id>`, trong partition tenant. Kết nối mới không dùng observation/ngoại lệ cũ. Key cũ chưa có type chỉ được migrate khi native ID xác định được chủ sở hữu (`vol-` cho EBS, `eipalloc-` cho EIP); không trộn hai loại có cùng ID.

## 6. Giới hạn, tương thích và nghiệm thu

- Tối đa 100 tài nguyên/loại/region, 50 finding hiển thị; tối đa 100 private candidates, ưu tiên 50 finding đang hiện. Toàn bộ result JSON UTF-8 trước persistence giới hạn 300 KiB. Khi cắt pool do số lượng/kích thước, trả `PARTIAL` + `FINDING/CANDIDATE_LIMIT`; không khẳng định quét đầy đủ.
- `finding_count` đếm finding nhìn thấy trong pool còn lưu trước cap hiển thị 50; khi pool bị cắt đây là số đếm trong phần còn giữ, không phải tổng toàn account. `total_candidate_count` là tổng trước retention. Finding bị loại do retention cần scan mới để phục hồi.
- Trường mới là bổ sung; finding lịch sử có thể thiếu chúng và không được tự tính lại. Reason cũ được giữ cho các trạng thái cũ. Contract helper insufficient đã đổi sang evidence dict; caller và test phải dùng hợp đồng mới.
- Test cần chứng minh mọi rule/state/boundary/quality/exception và evidence qua collector → worker → API/history, isolation, lỗi/truncation và giới hạn. Kết quả thực tế tại [VALIDATION.md](VALIDATION.md).
- Local unit/mock/Moto chứng minh logic và hợp đồng trong phạm vi chín loại. AWS E2E cần credentials/fixtures/quan sát theo thời gian và bằng chứng riêng; UI đầy đủ thuộc Task 9. Không coi thiếu collector Task 6 hoặc cloud chưa chạy là PASS.
