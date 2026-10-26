# Mục 7 — Luật đánh giá và bằng chứng

Phần hợp đồng giai đoạn đầu bên dưới mô tả EC2, EBS volume, Elastic IP và EBS snapshot. Checkout hiện tại có thêm collector S3 multipart, RDS, NAT Gateway, ALB và NLB; mục “Rule metric mở rộng” đặc tả phần gia cố RDS/NAT/ALB/NLB. Các loại đang có chưa bao phủ toàn bộ nhóm dịch vụ và dữ liệu chi phí trong báo cáo. Finding là đề nghị xem xét kèm bằng chứng, không phải quyết định dừng hoặc xóa tài nguyên.

`src/rules.py` chứa các hàm thuần, không gọi AWS, đọc/ghi DynamoDB hay lấy thời gian hệ thống. Worker trong `src/app.py` thu thập dữ liệu, truyền cấu hình/thời điểm, quản lý quan sát và áp dụng ngoại lệ. Mục 6 bàn giao collector theo hợp đồng bên dưới; mục 5 phối hợp API; mục 9 dùng finding và API phản hồi để hoàn thiện dashboard. Scheduler/retry và collector mới nằm ngoài phần thay đổi này.

## 1. Danh mục rule

| `rule_id` | Đầu vào và điều kiện | Kết quả |
|---|---|---|
| `EC2_LOW_UTILIZATION` | Instance `running`, tồn tại từ đầu cửa sổ; CPU p95 và tổng NetworkIn/Out trung bình theo giờ đều **thấp hơn** ngưỡng; cả ba metric đủ mẫu hợp lệ | `REVIEW` nếu ít hoạt động; `INSUFFICIENT_DATA` nếu instance còn mới hoặc dữ liệu thiếu/không hợp lệ |
| `EBS_UNATTACHED` | Volume `available`, danh sách attachment rỗng | `OBSERVING` trước `orphan_hours`, `REVIEW` khi đạt hoặc vượt ngưỡng |
| `EIP_UNASSOCIATED` | Có `AllocationId`, không có `AssociationId` | `OBSERVING` trước `orphan_hours`, `REVIEW` khi đạt hoặc vượt ngưỡng |
| `SNAPSHOT_OLD_UNREFERENCED` | Snapshot `completed`, tuổi đạt `snapshot_days`, không được AMI đã đọc tham chiếu; danh sách AMI đầy đủ; không có dấu hiệu AWS Backup | `REVIEW` |

Tag `guardian:keep=true` (giá trị không phân biệt hoa thường) chặn finding ở cả bốn rule. Snapshot có chuỗi `aws:backup` trong description hoặc key tag bắt đầu bằng `aws:backup` được bỏ qua. Đây chỉ là dấu hiệu để tránh cảnh báo nhầm, chưa kiểm tra đầy đủ backup/retention hoặc mọi quan hệ phụ thuộc AWS.

Không đủ điều kiện tạo finding thì evaluator trả `None`. `idle()` có thể trả `OK` nội bộ; worker không công bố `OK` trong danh sách findings. EC2 có CPU hoặc network **bằng** ngưỡng không được coi là ít hoạt động.

### Cấu hình và dữ liệu EC2

| Trường | Mặc định | Khoảng cho phép |
|---|---:|---:|
| `cpu_percent` | 5 | 1–50 |
| `network_mib_hour` | 1 | 0.1–100 |
| `window_hours` | 24 | 24–168, số nguyên |
| `orphan_hours` | 24 | 1–168, số nguyên |
| `snapshot_days` | 30 | 7–365, số nguyên |
| `interval_hours` | 6 | 1–24, số nguyên |

`config()` áp dụng giá trị mặc định cho trường không được truyền; từ chối trường lạ, boolean, số không hữu hạn và giá trị ngoài giới hạn. Cấu hình đã lưu còn trong giới hạn tiếp tục có hiệu lực.

Mỗi metric cần ít nhất `ceil(window_hours × 0.8)` mẫu: 20 mẫu cho 24 giờ, 135 mẫu cho 168 giờ. Zero thật là mẫu hợp lệ; mẫu thiếu, NaN, infinity, số âm, boolean hoặc kiểu không phải số không được thay bằng zero. Có bất kỳ mẫu không hợp lệ nào thì kết quả là `INSUFFICIENT_DATA`, kể cả các mẫu còn lại đã đạt độ phủ.

CPU dùng `Maximum` mỗi giờ, lấy p95 theo phần tử thứ `ceil(0.95 × số mẫu)` trong dãy tăng dần. NetworkIn/Out dùng `Sum` mỗi giờ; tính trung bình riêng cho từng chiều theo số mẫu hợp lệ của chiều đó, rồi cộng hai trung bình và chia `1048576` để ra MiB/giờ:

```text
network_mib_hour = (sum(NetworkIn) / count(NetworkIn)
                  + sum(NetworkOut) / count(NetworkOut)) / 1048576
```

Chỉ tính khi cả ba metric đạt độ phủ yêu cầu và không có mẫu lỗi. Ví dụ, 20 giờ đo được đều có NetworkIn 1.1 MiB/giờ trong cửa sổ 24 giờ, NetworkOut bằng 0, vẫn được tính là 1.1 MiB/giờ; bốn giờ thiếu không kéo trung bình xuống như zero. Nếu số mẫu hai chiều khác nhau, mỗi chiều dùng mẫu số riêng. Đây là trung bình của các giờ thực đo, không khẳng định lưu lượng trong các giờ thiếu. Điều kiện đủ 80% không có nghĩa đủ mọi giờ; bằng chứng luôn công bố số mẫu thực tế. Instance mới hơn đầu cửa sổ có `INSUFFICIENT_DATA`, không kết luận ít hoạt động. Kết quả lịch sử đã lưu không được tính lại; công thức sửa áp dụng cho lượt quét mới.

### Rule metric mở rộng: RDS, NAT Gateway, ALB và NLB

`src/collectors.py` gọi trực tiếp `rds_idle`, `nat_idle`, `alb_idle`, `nlb_idle` trong `src/rules.py`. Các helper giữ hợp đồng trả `(status, evidence)`; trạng thái là `REVIEW`, `OK` hoặc `INSUFFICIENT_DATA`. Worker không công bố finding `OK`.

Mỗi chuỗi metric bắt buộc cần ít nhất `ceil(window_hours × 0.8)` mẫu hợp lệ: 20 mẫu cho 24 giờ, 135 mẫu cho 168 giờ. Mẫu hợp lệ là `int`/`float` hữu hạn, không âm và không phải boolean; zero thật vẫn hợp lệ. Có bất kỳ mẫu âm, sai kiểu (kể cả `None`), boolean, NaN/infinity hoặc số nguyên quá lớn không chuyển được sang float thì cả rule trả `INSUFFICIENT_DATA`, ngay cả khi các mẫu còn lại đã đủ độ phủ. Không thay mẫu lỗi/thiếu bằng zero hoặc bỏ mẫu lỗi rồi tiếp tục phân loại.

| Helper | Metric và phép tính | Điều kiện `REVIEW` |
|---|---|---|
| `rds_idle` | CPUUtilization và DatabaseConnections, hourly Maximum rồi p95 theo nearest rank | Cả CPU p95 và connections p95 thấp hơn `rds_cpu_percent` và `rds_connections` |
| `nat_idle` | BytesInFromSource và BytesInFromDestination, hourly Sum; trung bình riêng từng chiều rồi cộng, đổi sang MiB/giờ | Nhỏ hơn `nat_mib_hour` |
| `alb_idle` | RequestCount, hourly Sum rồi trung bình theo số giờ thực đo | Nhỏ hơn `alb_requests_hour` |
| `nlb_idle` | NewFlowCount, hourly Sum rồi trung bình theo số giờ thực đo | Nhỏ hơn `nlb_new_flows_hour` |

Giá trị bằng ngưỡng trả `OK`; quyết định dùng giá trị trước làm tròn. Mặc định các ngưỡng lần lượt là CPU RDS 5%, connections 1, NAT 1 MiB/giờ, ALB 1 request/giờ và NLB 1 new flow/giờ; cấu hình được validate bằng `config()`.

```text
nat_mib_hour = (sum(BytesInFromSource) / count(BytesInFromSource)
              + sum(BytesInFromDestination) / count(BytesInFromDestination)) / 1048576
```

Ví dụ 24 mẫu source và 20 mẫu destination, mỗi mẫu tương ứng 0.48 MiB, cho tổng 0.96 MiB/giờ. Không chia tổng hai chiều cho số mẫu nhỏ hơn và không coi bốn giờ thiếu là zero. Cả hai chuỗi vẫn phải đạt độ phủ riêng; phép tính chỉ phản ánh các giờ đã đo, không khẳng định các giờ thiếu có mức sử dụng tương tự.

Thiếu/lỗi metric hoặc phép tổng/trung bình bị overflow trả `("INSUFFICIENT_DATA", None)`; không đưa NaN/infinity vào evidence. Khi đủ dữ liệu, giữ các trường evidence hiện có: RDS có `cpu_p95`, `connections_p95`, `coverage`; NAT có `nat_mib_hour`, `coverage`; ALB/NLB có `requests_hour`/`new_flows_hour`, `coverage`. Collector có thể bổ sung metadata tài nguyên. Thay đổi công thức áp dụng cho lượt quét mới; không tính lại snapshot lịch sử đã lưu.

## 2. Finding và hợp đồng collector

Các trường cũ giữ nguyên: `type`, `resource_id`, `region`, `level`, `reason`, `evidence`. Evaluator trả finding chưa có `region`; worker gắn region khi lưu. Chuỗi `reason` hiện có giữ để tương thích bản dịch frontend. Hai trường bổ sung:

- `rule_id`: một trong bốn mã ổn định ở bảng trên.
- `recommendation`: tiếng Việt, hướng dẫn kiểm tra chủ sở hữu, mục đích sử dụng và lưu giữ trước khi cân nhắc xử lý tài nguyên.

Bằng chứng theo rule:

| Loại | Trường `evidence` |
|---|---|
| EC2 | `window_hours`, `thresholds` (`cpu_percent`, `network_mib_hour`), `sample_counts` (`cpu`, `netin`, `netout`), `required_samples`, `missing_metrics`, `invalid_metrics`, `coverage`, `observation_start`, `launch_time`; thêm `cpu_p95`, `network_mib_hour` khi đủ dữ liệu hợp lệ |
| EBS | `size_gib`, `observed_hours`, `threshold_hours` |
| EIP | `observed_hours`, `threshold_hours` |
| Snapshot | `age_days`, `snapshot_days`, `volume_id`, `logical_volume_gib`, `relationships_complete` |

`sample_counts` đếm mẫu hợp lệ, `missing_metrics` liệt kê metric chưa đạt số mẫu yêu cầu, `invalid_metrics` liệt kê metric có mẫu lỗi. `coverage` là tỷ lệ nhỏ nhất giữa số mẫu hợp lệ của ba metric và số giờ cửa sổ, làm tròn ba chữ số thập phân. Giá trị metric và thời lượng đã làm tròn dùng cho hiển thị; quyết định rule dùng giá trị trước làm tròn. `logical_volume_gib` là kích thước volume nguồn, không phải dung lượng snapshot tính phí hoặc ước tính tiết kiệm.

Chữ ký tích hợp:

```python
evaluate_ec2(instance, metric_values, cfg, window_start)
evaluate_ebs(volume, observed_hours, cfg)
evaluate_eip(address, observed_hours, cfg)
evaluate_snapshot(snapshot, referenced_snapshot_ids, relationships_complete, cfg, now)
```

Hợp đồng collector cho mục 6:

1. Truyền resource dict theo hình dạng AWS SDK: EC2 cần `InstanceId`, `State.Name`, `LaunchTime`; EBS cần `VolumeId`, `State`, `Attachments`, `Size`; EIP cần `AllocationId` và `AssociationId` nếu có; snapshot cần `SnapshotId`, `StartTime`, `State`, `VolumeSize`, cùng `VolumeId`/`Description` nếu có. Cả bốn có thể có `Tags`.
2. `cfg` là cấu hình đã qua `config()`. Datetime có timezone UTC. `window_start` là đầu cửa sổ EC2; worker chọn giờ UTC tròn làm điểm cuối và xét mẫu trong `[start, end)`.
3. `metric_values` là ba danh sách theo đúng thứ tự `(cpu, netin, netout)`. Collector lấy hết các trang CloudWatch, khử trùng theo timestamp từng metric, giữ zero thật, lọc timestamp ngoài cửa sổ. Không bù mẫu thiếu, thay dữ liệu lỗi bằng zero hoặc đếm lặp timestamp để đạt 80%. Trạng thái API lỗi phải được báo về worker, không tạo mẫu hợp lệ giả.
4. `observed_hours` là thời gian theo dõi không sử dụng được worker lưu qua các lần quét, không phải tuổi tài nguyên. Collector chỉ cung cấp trạng thái attach/associate thực tế; không quyết định thời gian quan sát bằng tag hoặc ngoại lệ.
5. `referenced_snapshot_ids` là tập SnapshotId từ `BlockDeviceMappings[].Ebs.SnapshotId` của các AMI thuộc account đã đọc. Collector gọi `DescribeImages(Owners=["self"], IncludeDisabled=True)` để không bỏ sót tham chiếu từ AMI bị vô hiệu hóa. `relationships_complete` chỉ được `True` khi đã đọc đủ trang trong phạm vi này và không bị lỗi/cắt. `False` không tạo finding snapshot; lỗi hoặc cắt dữ liệu phải đồng thời đánh dấu lượt quét `PARTIAL`. Worker hiện bỏ cả phần snapshot khi API AMI lỗi, giữ các kết quả dịch vụ khác.
6. Worker chịu trách nhiệm phân trang, giới hạn tài nguyên, lưu dữ liệu, tenant/connection, ngoại lệ và trạng thái `PARTIAL`. Bốn evaluator không thực hiện I/O. Khi bổ sung nhóm dịch vụ, cần bổ sung collector, rule ID, bằng chứng và test tương ứng trước khi công bố hỗ trợ.

Kết quả hiện tại và lịch sử lưu nguyên các trường finding bổ sung. Finding cũ có thể chưa có `rule_id`/`recommendation`; frontend đang dựa trên các trường cũ vẫn đọc được.

## 3. Giữ lại, bỏ qua và cửa sổ quan sát

### API giữ lại nội bộ

```http
PUT /keep
Authorization: Bearer <Cognito access token>
Content-Type: application/json

{"region":"ap-southeast-1","resource_id":"vol-0123456789abcdef0","enabled":true}
```

Thành công trả HTTP 200 với `{"kept":true}`. Truyền `enabled:false` trả `{"kept":false}`; gọi lặp cùng trạng thái cho cùng tài nguyên có cùng hiệu lực. `enabled` bắt buộc là JSON boolean, không nhận chuỗi hoặc số.

API Gateway xác minh JWT và Lambda kiểm tra access token. Tenant chỉ lấy từ claim `sub`, không lấy user ID trong body. Cần có `role_arn` và `connection_version` hiện hành; region phải thuộc các region kết nối đã chọn. Resource ID là chuỗi 1–80 ký tự chữ ASCII, số hoặc dấu `-`. Kiểm tra cú pháp ID không chứng minh tài nguyên tồn tại trong AWS. Body sai, chưa kết nối hoặc region/ID không hợp lệ trả HTTP 400.

DynamoDB lưu trong partition tenant với sort key `KEEP#<connection_version>#<region>#<resource_id>` và trường `enabled`. Bỏ giữ lại cập nhật `enabled=false`, không cần quyền xóa bản ghi. Kết nối mới có version khác nên không dùng lại ngoại lệ của kết nối cũ.

Giữ lại nội bộ, tag giữ lại và `PUT /ignore` là ba điều kiện độc lập: bất kỳ điều kiện nào còn hiệu lực đều chặn phát finding. API keep chỉ đổi giữ lại nội bộ; `enabled=false` không vô hiệu hóa tag hoặc ignore còn hạn. Ngoại lệ áp dụng ở lần quét tiếp theo; kết quả/lịch sử đã lưu không được viết lại ngay. Mục 9 sẽ nối thao tác giữ lại với giao diện.

`PUT /ignore` nhận `region`, `resource_id`, `days` nguyên 1–30 (mặc định 7). Worker xét `expires > thời điểm bắt đầu quét`; ignore hết hạn không còn chặn finding dù DynamoDB TTL chưa xóa item.

### Quan sát EBS/EIP

Worker cập nhật trạng thái quan sát trước khi ẩn finding do tag, keep hoặc ignore. Tài nguyên đang không sử dụng bắt đầu từ 0 giờ ở lần quan sát đầu; các lần sau giữ thời điểm đầu nếu khoảng cách giữa hai lần quan sát không quá 48 giờ. Gắn volume/liên kết EIP lại sẽ xóa quan sát cũ; khoảng trống **trên** 48 giờ bắt đầu cửa sổ mới. Đúng 48 giờ vẫn tiếp tục cửa sổ. Đổi kết nối dùng key observation mới.

Ẩn cảnh báo không chứng minh tài nguyên được sử dụng lại. Ngược lại, chuyển trạng thái giữa hai lần quét có thể không được thấy; thời gian quan sát là bằng chứng có giới hạn, cần người dùng xác nhận.

## 4. Kiểm thử và bàn giao

Test rule kiểm tra mốc 80%, zero thật, dữ liệu thiếu/lỗi, bằng ngưỡng, spike CPU, network cao, instance mới, cửa sổ 24/168 giờ; mốc thời gian EBS/EIP và snapshot; quan hệ AMI, backup và tag. Test API/workflow kiểm tra keep/ignore, tách tenant/kết nối, observation khi ẩn cảnh báo, đọc lại finding trong kết quả/lịch sử, phân trang metric và lượt quét `PARTIAL`.

Chạy theo các lệnh trong README với Python 3.12 và dependencies đã pin; thêm UI smoke để kiểm tra form lưu 168 giờ và chặn ngoài giới hạn, kiểm tra cú pháp Python/JavaScript và lint template sau khi thêm route. Kết quả thực tế, số test và giới hạn môi trường được ghi riêng trong [VALIDATION.md](VALIDATION.md). Unit/Moto/UI cục bộ không thay thế xác thực Cognito, IAM, CloudWatch, dữ liệu và tác động AWS thật; chỉ công bố cloud pass khi có bằng chứng chạy thực tế.
