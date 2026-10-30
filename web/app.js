'use strict';
const $=id=>document.getElementById(id);
let cfg,profile,results=[],historyRows=[],token=sessionStorage.getItem('crg-token'),pollTimer,pollCount=0,loadingResults=true,resultsError=false,scanPending=false,scopeGeneration=0,detailFocus=null;
let findingsRevision=0;
const feedbackState=new Map(),feedbackDays=new Map();
const pages={overview:['Tổng quan tài nguyên','Tập trung vào tài nguyên cần bạn kiểm tra.'],findings:['Tài nguyên cần kiểm tra','Mỗi cảnh báo đi kèm lý do và bằng chứng.'],history:['Lịch sử quét','Theo dõi kết quả theo thời gian trong từng region.'],connection:['Kết nối tài khoản AWS','Cấp quyền đọc bằng IAM Role và ExternalId riêng.'],settings:['Cấu hình & cảnh báo','Điều chỉnh ngưỡng phát hiện và lịch quét.']};
const regions=['ap-southeast-1','ap-southeast-2','ap-northeast-1','us-east-1','us-west-2','eu-west-1'];
const serviceGroups={compute:{label:'Tính toán',types:['EC2']},storage:{label:'Lưu trữ và sao lưu',types:['EBS','SNAPSHOT','S3_MULTIPART']},database:{label:'Cơ sở dữ liệu',types:['RDS']},network:{label:'Mạng',types:['EIP','NAT_GATEWAY','ALB','NLB']}};
const resourceGroups=Object.fromEntries(Object.entries(serviceGroups).flatMap(([group,value])=>value.types.map(type=>[type,group])));
const fields={cpu_percent:['Ngưỡng CPU EC2 (%)',1,50,'any'],network_mib_hour:['Ngưỡng network EC2 (MiB/giờ)',.1,100,'any'],window_hours:['Cửa sổ metrics (giờ)',24,168,1],orphan_hours:['Theo dõi EBS / EIP (giờ)',1,168,1],snapshot_days:['Tuổi snapshot (ngày)',7,365,1],interval_hours:['Khoảng quét (giờ)',1,24,1],rds_cpu_percent:['Ngưỡng CPU RDS (%)',1,50,'any'],rds_connections:['Ngưỡng kết nối RDS',1,1000,1],nat_mib_hour:['Ngưỡng NAT (MiB/giờ)',.1,10000,'any'],alb_requests_hour:['Ngưỡng ALB (request/giờ)',1,1000000,1],nlb_new_flows_hour:['Ngưỡng NLB (flow mới/giờ)',1,1000000,1]};
const stateLabels={REVIEW:'Cần kiểm tra',OBSERVING:'Đang quan sát',INSUFFICIENT_DATA:'Thiếu dữ liệu',QUEUED:'Đang chờ',RUNNING:'Đang quét',SUCCEEDED:'Hoàn tất',PARTIAL:'Chưa đầy đủ',FAILED:'Lỗi',TIMED_OUT:'Quá hạn'};
const reasons={'Low CPU and network; confirm intended workload':'CPU và network thấp; kiểm tra mục đích sử dụng.','Missing CloudWatch metrics; not classified as idle':'Thiếu metrics CloudWatch; chưa thể kết luận ít hoạt động.','Instance younger than observation window':'Instance mới hơn cửa sổ quan sát.','Unattached volume; validate data retention':'Volume chưa gắn vào instance; kiểm tra nhu cầu giữ dữ liệu.','Unassociated public IPv4; may be intentionally reserved':'Elastic IP chưa liên kết; có thể đang được giữ có chủ đích.','Old snapshot not referenced by listed AMIs; backup purpose requires review':'Snapshot cũ, không được các AMI đã đọc tham chiếu; kiểm tra mục đích sao lưu.'};
const evidenceFields={
 EC2:[['cpu_p95','CPU p95','%'],['network_mib_hour','Network trung bình','MiB/giờ'],['launch_time','Thời điểm khởi chạy','time']],
 EBS:[['size_gib','Dung lượng volume','GiB'],['observed_hours','Theo dõi chưa gắn','giờ'],['threshold_hours','Ngưỡng theo dõi','giờ']],
 EIP:[['observed_hours','Theo dõi chưa liên kết','giờ'],['threshold_hours','Ngưỡng theo dõi','giờ']],
 SNAPSHOT:[['age_days','Tuổi snapshot','ngày'],['snapshot_days','Ngưỡng tuổi snapshot','ngày'],['volume_id','Volume nguồn'],['logical_volume_gib','Dung lượng logic của volume','GiB'],['relationships_complete','Đã đọc đầy đủ quan hệ AMI'],['snapshot_started_at','Thời điểm tạo snapshot','time'],['relationship_scope','Phạm vi đối chiếu AMI']],
 S3_MULTIPART:[['bucket','Bucket'],['key','Object key'],['upload_id','Upload ID'],['age_days','Tuổi upload','ngày'],['threshold_days','Ngưỡng tuổi upload','ngày'],['initiated_at','Thời điểm bắt đầu upload','time']],
 RDS:[['cpu_p95','CPU p95','%'],['connections_p95','Kết nối p95','kết nối'],['engine','Engine'],['instance_class','Instance class'],['created_at','Thời điểm tạo','time']],
 NAT_GATEWAY:[['nat_mib_hour','Lưu lượng NAT trung bình','MiB/giờ'],['vpc_id','VPC ID'],['subnet_id','Subnet ID'],['created_at','Thời điểm tạo','time']],
 ALB:[['requests_hour','Request trung bình','request/giờ'],['scheme','Scheme'],['created_at','Thời điểm tạo','time']],
 NLB:[['new_flows_hour','Flow mới trung bình','flow mới/giờ'],['scheme','Scheme'],['created_at','Thời điểm tạo','time']]
};
const thresholdFields={EC2:['cpu_percent','network_mib_hour'],EBS:['orphan_hours'],EIP:['orphan_hours'],SNAPSHOT:['snapshot_days'],S3_MULTIPART:['multipart_days'],RDS:['rds_cpu_percent','rds_connections'],NAT_GATEWAY:['nat_mib_hour'],ALB:['alb_requests_hour'],NLB:['nlb_new_flows_hour']};
const thresholdLabels={cpu_percent:['CPU EC2','%'],network_mib_hour:['Network EC2','MiB/giờ'],orphan_hours:['Theo dõi không sử dụng','giờ'],snapshot_days:['Tuổi snapshot','ngày'],multipart_days:['Tuổi multipart upload (lớn hơn)','ngày'],rds_cpu_percent:['CPU RDS','%'],rds_connections:['Kết nối RDS','kết nối'],nat_mib_hour:['Lưu lượng NAT','MiB/giờ'],alb_requests_hour:['Request ALB','request/giờ'],nlb_new_flows_hour:['Flow mới NLB','flow mới/giờ']};
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function status(text,error=false){$('status').hidden=!text;$('status').textContent=text;$('status').className=error?'error':'';}
function badge(s){return node('span',stateLabels[s]||s,'badge '+(s==='REVIEW'?'review':s==='FAILED'||s==='PARTIAL'||s==='TIMED_OUT'?'error':s==='SUCCEEDED'?'good':'observing'));}
function date(t){return t?new Date(t*1000).toLocaleString('vi-VN'):'Chưa có thời gian';}
function b64(b){return btoa(String.fromCharCode(...b)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');}
function random(){const b=new Uint8Array(32);crypto.getRandomValues(b);return b64(b);}
async function login(){if(!cfg)return;if(cfg.demo){token='demo-local-only';sessionStorage.setItem('crg-token',token);await run(init);return;}const verifier=random(),state=random();sessionStorage.setItem('crg-verifier',verifier);sessionStorage.setItem('crg-state',state);const challenge=b64(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(verifier))));location.assign(cfg.auth+'/oauth2/authorize?'+new URLSearchParams({client_id:cfg.clientId,response_type:'code',scope:'openid email aws.cognito.signin.user.admin',redirect_uri:cfg.redirect,state,code_challenge:challenge,code_challenge_method:'S256'}));}
function logout(){closeFindingDetail();clearTimeout(pollTimer);sessionStorage.removeItem('crg-token');token=null;if(cfg.demo){location.reload();return;}location.assign(cfg.auth+'/logout?'+new URLSearchParams({client_id:cfg.clientId,logout_uri:cfg.redirect}));}
async function api(path,method='GET',data){const r=await fetch(cfg.api+path,{method,headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},...(data!==undefined?{body:JSON.stringify(data)}:{})});let v;try{v=await r.json();}catch{throw Error('Máy chủ trả phản hồi không hợp lệ.');}if(r.status===401){closeFindingDetail();clearTimeout(pollTimer);token=null;sessionStorage.removeItem('crg-token');$('app').hidden=true;$('welcome').hidden=false;$('login').textContent='Đăng nhập';$('login').onclick=login;}if(!r.ok)throw Error(friendlyError(v.error||v.message||'HTTP '+r.status));return v;}
async function run(fn,button){if(button)button.disabled=true;try{await fn();}catch(e){status(friendlyError(e.message),true);}finally{if(button){const feedback=$(button.id+'-feedback');if(feedback){feedback.hidden=$('status').hidden;feedback.textContent=$('status').textContent;feedback.className='inline-feedback '+$('status').className;}}if(button)button.disabled=button.dataset.saved==='true';if(button===$('scan')&&profile)render();}}
function showPage(page){if(!profile)return;closeFindingDetail();if(!pages[page])page='overview';for(const key of Object.keys(pages))$('page-'+key).hidden=key!==page;document.querySelectorAll('nav button').forEach(b=>{b.classList.toggle('active',b.dataset.page===page);if(b.dataset.page===page)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});$('page-title').textContent=pages[page][0];$('page-subtitle').textContent=pages[page][1];$('breadcrumb').textContent=document.querySelector('[data-page="'+page+'"]').textContent.replace(/[\d—]+$/,'').trim();document.title=pages[page][0]+' | Cloud Guardian';if(page==='history')run(loadHistory);}
function detailValue(value,unit){
 if(value===undefined||value===null||value==='')return 'Chưa có dữ liệu';
 if(unit==='time'){
  if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)||!Number.isFinite(Date.parse(value)))return 'Chưa có dữ liệu';
  return new Date(value).toISOString().replace('T',' ').replace(/\.000Z$/,' UTC').replace(/Z$/,' UTC');
 }
 if(typeof value==='number'&&!Number.isFinite(value))return 'Chưa có dữ liệu';
 if(unit==='coverage')return typeof value==='number'?Number((value*100).toFixed(1))+'%':'Chưa có dữ liệu';
 if(typeof value==='boolean')return value?'Có':'Không';
 if(Array.isArray(value))return value.length?value.map(item=>detailValue(item)).join(' · '):'Không ghi nhận';
 if(typeof value==='object')return Object.keys(value).length?Object.entries(value).map(([key,item])=>key+': '+detailValue(item)).join(' · '):'Không ghi nhận';
 return String(value)+(unit?' '+unit:'');
}
function detailSection(container,title,rows){
 const section=node('section',undefined,'finding-detail-section'),list=node('dl',undefined,'finding-detail-grid');section.append(node('h3',title));
 for(const [key,label,value,unit] of rows){const item=node('div');item.dataset.field=key;item.append(node('dt',label),node('dd',detailValue(value,unit)));list.append(item);}
 section.append(list);container.append(section);return section;
}
function closeFindingDetail(){detailFocus=null;if($('finding-dialog').open)$('finding-dialog').close();$('finding-detail-content').replaceChildren();}
function restoreFindingFocus(){
 const previous=detailFocus;detailFocus=null;if(!previous||previous.element?.isConnected||$('app').hidden)return;
 const container=$(previous.container),replacement=container&&[...container.querySelectorAll('.finding-open')].find(button=>button.dataset.findingId===previous.id&&button.dataset.region===previous.region&&button.dataset.resourceId===previous.resource);
 const fallback=previous.container==='findings-list'?$('search'):previous.container==='history-detail'?$('refresh-history'):$('refresh');
 (replacement||fallback)?.focus();
}
function openFindingDetail(f,history=false,opener=document.activeElement){
 detailFocus={element:opener,container:opener.closest('[id]')?.id,id:String(f.finding_id??''),region:String(f.region??''),resource:String(f.resource_id??'')};
 const v=f.evidence&&typeof f.evidence==='object'?f.evidence:{},content=$('finding-detail-content');content.replaceChildren();
 $('finding-detail-context').textContent=history?'Snapshot lịch sử đã lưu. Phản hồi và cấu hình hiện tại không thay đổi bằng chứng này.':'Bằng chứng đã lưu của finding tại lần đánh giá này. Kiểm tra mục đích sử dụng trước khi xử lý tài nguyên.';
 detailSection(content,'Thông tin finding',[
  ['type','Loại tài nguyên',f.type],['resource_id','Resource ID',f.resource_id],['account_id','AWS account',f.account_id??v.account_id],['region','Region',f.region??v.region],['finding_id','Finding ID',f.finding_id],['rule_id','Rule',f.rule_id],['level','Mức cảnh báo',stateLabels[f.level]||f.level],['reason','Lý do',reasons[f.reason]||f.reason],['recommendation','Khuyến nghị',f.recommendation]
 ]);
 const times=detailSection(content,'Mốc quan sát finding',[
  ['first_seen_at','Quan sát lần đầu',f.first_seen_at,'time'],['last_seen_at','Quan sát gần nhất',f.last_seen_at,'time'],['evaluated_at','Thời điểm đánh giá',f.evaluated_at??v.evaluated_at,'time']
 ]);
 times.append(node('p','Mốc first/last ghi nhận các lần ứng dụng quan sát finding; không chứng minh tài nguyên ít hoạt động liên tục. Lịch sử cũ thiếu mốc chưa được ghi nhận, không suy từ tuổi tài nguyên hoặc cửa sổ metrics.','footnote'));
 detailSection(content,'Evidence '+(f.type||''),(evidenceFields[f.type]||[]).map(([key,label,unit])=>[key,label,v[key],unit]));
 const thresholds=thresholdFields[f.type]||Object.keys(v.thresholds||{}),legacy={orphan_hours:v.threshold_hours,snapshot_days:v.snapshot_days,multipart_days:v.threshold_days};
 detailSection(content,'Ngưỡng tại lần đánh giá',thresholds.map(key=>['thresholds.'+key,thresholdLabels[key]?.[0]||key,v.thresholds?.[key]??legacy[key],thresholdLabels[key]?.[1]]));
 if(['EC2','RDS','NAT_GATEWAY','ALB','NLB'].includes(f.type)){
  detailSection(content,'Cửa sổ và độ phủ metrics',[
   ['window_hours','Cửa sổ metrics',v.window_hours,'giờ'],['observation_start','Bắt đầu cửa sổ',v.observation_start,'time'],['observation_end','Kết thúc cửa sổ',v.observation_end,'time'],['metric_period_seconds','Chu kỳ mẫu',v.metric_period_seconds,'giây'],['coverage','Độ phủ mẫu hợp lệ',v.coverage,'coverage'],['required_samples','Số mẫu tối thiểu mỗi metric',v.required_samples],['sample_counts','Số mẫu hợp lệ',v.sample_counts],['received_sample_counts','Số mẫu nhận được',v.received_sample_counts],['invalid_sample_counts','Số mẫu không hợp lệ',v.invalid_sample_counts],['metric_units','Đơn vị metric đầu vào',v.metric_units],['metric_statistics','Thống kê mỗi chu kỳ',v.metric_statistics]
  ]).append(node('p','Rule yêu cầu ít nhất 80% số mẫu theo giờ cho từng metric. Thiếu hoặc sai dữ liệu không được xem là giá trị 0.','footnote'));
 }else content.append(node('p',evidenceFields[f.type]?'Rule này dùng thời gian hoặc quan hệ tài nguyên; không áp dụng độ phủ CloudWatch.':'Chưa có dữ liệu về cửa sổ và độ phủ của loại tài nguyên này.','footnote'));
 const quality=['EC2','RDS','NAT_GATEWAY','ALB','NLB'].includes(f.type)?[['missing_metrics','Metric thiếu mẫu',v.missing_metrics],['invalid_metrics','Metric không hợp lệ',v.invalid_metrics],['calculation_errors','Lỗi tính toán',v.calculation_errors],['data_issues','Vấn đề dữ liệu',v.data_issues]]:v.data_issues!==undefined?[['data_issues','Vấn đề dữ liệu',v.data_issues]]:[];
 if(quality.length)detailSection(content,'Chất lượng dữ liệu',quality);
 if(f.type==='SNAPSHOT')content.append(node('p','Dung lượng logic của volume không phải dung lượng snapshot được tính phí. Không được AMI đã đọc tham chiếu chưa đủ để quyết định xóa bản sao lưu.','footnote'));
 if(f.type==='S3_MULTIPART')content.append(node('p','Rule đánh dấu upload có tuổi lớn hơn 7 ngày. Upload ID phân biệt các lượt upload cùng bucket và object key.','footnote'));
 $('finding-dialog').showModal();
}
function evidence(f){const v=f.evidence||{},lines=(evidenceFields[f.type]||[]).filter(([key,,unit])=>unit!=='time'&&v[key]!==undefined&&v[key]!==null).slice(0,3).map(([key,label,unit])=>label+': '+detailValue(v[key],unit));if(v.coverage!==undefined&&v.coverage!==null)lines.push('Độ phủ: '+detailValue(v.coverage,'coverage'));return lines.join(' · ')||'Chưa có dữ liệu';}
function findings(){return results.flatMap(r=>(r.findings||[]).map(f=>({...f,region:r.region})));}
function feedbackKey(f){return JSON.stringify([f.region,f.finding_id]);}
function feedbackFocus(container){
 const active=document.activeElement,group=active.closest('.finding-feedback');
 if(!group||!container.contains(active))return null;
 return {key:group.dataset.feedbackKey,selector:['feedback-ack','feedback-keep','feedback-ignore','feedback-days','feedback-status'].find(name=>active.classList.contains(name))||'feedback-status'};
}
function restoreFeedbackFocus(container,previous){
 if(!previous||$('app').hidden)return;
 const group=[...container.querySelectorAll('.finding-feedback')].find(item=>item.dataset.feedbackKey===previous.key),control=group?.querySelector('.'+previous.selector),target=control&&!control.disabled?control:group?.querySelector('.feedback-status');
 (target||(container.id==='findings-list'?$('search'):$('refresh')))?.focus();
}
async function saveFindingFeedback(f,patch,generation){
 const key=feedbackKey(f);if(generation!==scopeGeneration||feedbackState.get(key)?.pending)return;
 const operation={pending:true,message:'Đang lưu…',error:false};feedbackState.set(key,operation);render();
 let saved=false;
 try{
  const record=await api('/feedback','PUT',{region:f.region,finding_id:f.finding_id,...patch});
  if(generation!==scopeGeneration||!token)return;
  saved=true;findingsRevision++;
  results=results.map(row=>{
   if(row.region!==f.region)return row;
   const items=(row.findings||[]).flatMap(item=>item.finding_id!==f.finding_id?[item]:record.kept||record.ignore_until>Date.now()/1000?[]:[{...item,acknowledged:record.acknowledged===true}]);
   return {...row,findings:items};
  });
  operation.pending=false;operation.message='acknowledged' in patch?(record.acknowledged?'Đã đánh dấu đã xem.':'Đã bỏ trạng thái đã xem.'):'kept' in patch?'Đã giữ lại. Cảnh báo đã được ẩn.':'Đã bỏ qua '+feedbackDays.get(key)+' ngày. Cảnh báo đã được ẩn.';
  render();status(operation.message);
  await refresh();
 }catch(error){
  if(generation!==scopeGeneration||!token||feedbackState.get(key)!==operation)return;
  operation.pending=false;operation.error=true;operation.message=saved?'Phản hồi đã lưu, nhưng chưa tải được kết quả mới. Chọn Tải lại kết quả.':'Chưa lưu được phản hồi. '+friendlyError(error.message)+' Chọn thao tác để thử lại.';
  render();status(operation.message,true);
 }
}
function findingFeedback(f){
 const key=feedbackKey(f),generation=scopeGeneration,state=feedbackState.get(key),group=node('div',undefined,'finding-feedback');group.dataset.feedbackKey=key;
 const valid=typeof f.finding_id==='string'&&/^[a-f0-9]{64}$/.test(f.finding_id)&&(profile.regions||[]).includes(f.region);
 const ack=node('button',f.acknowledged?'Bỏ đã xem':'Đánh dấu đã xem','button secondary feedback-ack'),keep=node('button','Giữ lại','button secondary feedback-keep'),label=node('label','Bỏ qua trong'),days=node('select',undefined,'feedback-days'),ignore=node('button',undefined,'button secondary feedback-ignore');
 if(!feedbackDays.has(key))feedbackDays.set(key,7);
 for(let day=1;day<=30;day++)days.append(new Option(day+' ngày',day));days.value=feedbackDays.get(key);days.setAttribute('aria-label','Thời hạn bỏ qua cho '+f.resource_id);label.append(days);
 ignore.textContent='Bỏ qua '+days.value+' ngày';
 days.onchange=()=>{feedbackDays.set(key,Number(days.value));for(const other of document.querySelectorAll('.finding-feedback'))if(other.dataset.feedbackKey===key){other.querySelector('.feedback-days').value=days.value;other.querySelector('.feedback-ignore').textContent='Bỏ qua '+days.value+' ngày';}};
 ack.onclick=()=>saveFindingFeedback(f,{acknowledged:!f.acknowledged},generation);keep.onclick=()=>saveFindingFeedback(f,{kept:true},generation);
 ignore.onclick=()=>{const count=Number(days.value);if(!Number.isInteger(count)||count<1||count>30)return;saveFindingFeedback(f,{ignoreUntil:new Date(Date.now()+count*86400000).toISOString()},generation);};
 for(const button of [ack,keep,ignore])button.type='button';
 for(const control of [ack,keep,ignore,days])control.disabled=!valid||!!state?.pending;
 const note=node('p',!valid?'Cảnh báo cũ thiếu mã hợp lệ; cần quét mới để phản hồi.':state?.message||'','feedback-status'+(state?.error?' error':''));note.setAttribute('role','status');note.tabIndex=-1;
 group.append(ack,keep,label,ignore,note);return group;
}
function renderTable(container,items,allowIgnore=true){
 const previous=feedbackFocus(container);container.replaceChildren();if(!items.length){container.append(node('div','Không có tài nguyên phù hợp với danh sách này.','empty'));restoreFeedbackFocus(container,previous);return;}
 const wrap=node('div',undefined,'table-wrap'),table=node('table',undefined,'finding-table'+(allowIgnore?' with-actions':'')),thead=node('thead'),tr=node('tr');
 for(const h of ['Tài nguyên','Trạng thái & lý do','Bằng chứng',...(allowIgnore?['Thao tác']:[])]){const th=node('th',h);th.scope='col';tr.append(th);}thead.append(tr);table.append(thead);
 const body=node('tbody');
 for(const f of items){
  const row=node('tr'),resource=node('td');resource.append(node('div',f.type,'resource-type'),node('code',f.resource_id),node('small',f.region));
  const detail=node('td');detail.append(badge(f.level),node('p',reasons[f.reason]||f.reason));if(allowIgnore)detail.append(node('small',f.acknowledged?'Đã xem':'Chưa xem','acknowledged-state'));
  const proof=node('td',undefined,'evidence'),open=node('button','Xem chi tiết','text-button finding-open');open.type='button';open.dataset.findingId=f.finding_id??'';open.dataset.region=f.region??'';open.dataset.resourceId=f.resource_id??'';open.setAttribute('aria-label','Xem chi tiết '+f.resource_id);open.onclick=()=>openFindingDetail(f,!allowIgnore,open);proof.append(node('div',evidence(f)),open);row.append(resource,detail,proof);
  if(allowIgnore){const td=node('td');td.append(findingFeedback(f));row.append(td);}
  [...row.children].forEach((td,i)=>td.dataset.label=['Tài nguyên','Trạng thái & lý do','Bằng chứng','Thao tác'][i]);body.append(row);
 }
 table.append(body);wrap.append(table);container.append(wrap);restoreFeedbackFocus(container,previous);
}
function renderFindings(){
 const q=$('search').value.trim().toLowerCase(),type=$('filter-type').value,level=$('filter-level').value,group=$('filter-group').value,region=$('filter-region').value,ack=$('filter-acknowledged').value;
 const all=findings(),filtered=all.filter(f=>(!type||f.type===type)&&(!level||f.level===level)&&(!group||resourceGroups[f.type]===group)&&(!region||f.region===region)&&(!ack||(ack==='acknowledged'?f.acknowledged===true:f.acknowledged!==true))&&[f.resource_id,f.reason,reasons[f.reason]||''].some(s=>String(s||'').toLowerCase().includes(q)));
 const active=Boolean(q||type||level||group||region||ack),incomplete=loadingResults||resultsError||results.some(r=>['QUEUED','RUNNING','PARTIAL','FAILED','TIMED_OUT'].includes(r.status));
 $('findings-scope').textContent=filtered.length+' / '+all.length+' cảnh báo trong kết quả hiện có. '+(incomplete?resultMessage():'Chỉ bao gồm các region và nhóm dịch vụ đã chọn.');
 renderTable($('findings-list'),filtered);
 if(!filtered.length)emptyState($('findings-list'),active?'Không khớp bộ lọc':'Chưa có cảnh báo để hiển thị',active?'Thử xóa từ khóa hoặc chọn Tất cả.'+(incomplete?' '+resultMessage():''):resultMessage());
}

function render(){
 const fs=findings(),measured=results.some(r=>Object.keys(r.counts||{}).length>0&&['SUCCEEDED','PARTIAL'].includes(r.status));
 const busy=scanPending||results.some(r=>['QUEUED','RUNNING'].includes(r.status));
 $('total').textContent=measured?results.reduce((sum,r)=>sum+Object.values(r.counts||{}).reduce((a,b)=>a+b,0),0):'—';
 for(const [id,level] of [['review','REVIEW'],['observing','OBSERVING'],['insufficient','INSUFFICIENT_DATA']])$(id).textContent=measured?fs.filter(f=>f.level===level).length:'—';
 $('nav-count').textContent=measured?fs.filter(f=>f.level==='REVIEW').length:'—';
 $('account-name').textContent=profile.account_id||'Chưa kết nối AWS';$('account-regions').textContent=(profile.regions||[]).join(' / ');
 $('account-service-groups').textContent='Nhóm dịch vụ: '+(profile.service_groups||Object.keys(serviceGroups)).map(group=>serviceGroups[group]?.label||group).join(' / ');
 $('account-badge').textContent=profile.role_arn?'Đã kết nối':'Chưa kết nối';$('account-badge').className='badge '+(profile.role_arn?'good':'');
 for(const id of ['scan','first-scan']){$(id).disabled=!profile.role_arn||busy;$(id).textContent=busy?'Đang quét…':'Quét ngay';}
 $('first-scan-note').textContent=!profile.role_arn?'Lưu kết nối ở bước 2 để bắt đầu quét.':busy?'Yêu cầu quét đã được nhận. Xem tổng quan để theo dõi từng region.':'Kết nối đã sẵn sàng. Chọn Quét ngay, rồi xem tổng quan; kết quả tự cập nhật mỗi 5 giây khi đang quét.';
 const panel=$('overview-state');panel.replaceChildren();panel.className='state-panel';
 const bad=results.some(r=>['FAILED','TIMED_OUT'].includes(r.status)),partial=results.some(r=>r.status==='PARTIAL');
 const title=loadingResults?'Đang tải kết quả':resultsError?'Không tải được kết quả mới':!profile.role_arn?'Bắt đầu bằng kết nối AWS':busy?'Đang kiểm tra tài nguyên của bạn':!results.length?'Sẵn sàng cho lần quét đầu tiên':bad?'Có region chưa quét thành công':partial?'Đã có kết quả, phạm vi chưa đầy đủ':'Kết quả đã sẵn sàng để xem xét';
 if(bad||resultsError)panel.classList.add('error');else if(partial)panel.classList.add('warning');
 panel.append(node('h2',title),node('p',resultMessage()));
 if(!profile.role_arn){const b=node('button','Kết nối AWS','button primary');b.onclick=()=>navigate('connection');panel.append(b);}
 $('scan-summary').replaceChildren();if(!results.length)$('scan-summary').append(node('p',resultMessage(),'muted'));
 for(const r of results){const div=node('div',undefined,'scan-row');div.append(node('span',r.region),badge(r.status));$('scan-summary').append(div,node('small',date(r.completed_at||r.started_at),'muted'));appendResultNotes($('scan-summary'),r);}
 renderTable($('priority-list'),fs.filter(f=>f.level==='REVIEW').slice(0,5));
 if(!fs.some(f=>f.level==='REVIEW'))emptyState($('priority-list'),'Chưa có ứng viên cần kiểm tra',resultMessage());renderFindings();
}

async function refresh(){
 const generation=scopeGeneration,revision=findingsRevision;
 try{const reply=await api('/findings');if(generation!==scopeGeneration||revision!==findingsRevision)return;results=reply.results;resultsError=false;loadingResults=false;render();
 if(results.some(r=>['QUEUED','RUNNING'].includes(r.status))&&pollCount<185){clearTimeout(pollTimer);pollTimer=setTimeout(()=>{pollCount++;run(refresh);},5000);}else clearTimeout(pollTimer);
 }catch(e){if(generation!==scopeGeneration||revision!==findingsRevision)return;loadingResults=false;resultsError=true;clearTimeout(pollTimer);render();throw e;}
}

async function loadHistory(){
 const generation=scopeGeneration;
 const c=$('history-list');c.replaceChildren(node('p','Đang tải lịch sử…','muted'));$('history-detail').replaceChildren();
 try{const reply=await api('/history');if(generation!==scopeGeneration)return;historyRows=reply.results;c.replaceChildren();
 if(!historyRows.length){emptyState(c,'Chưa có lịch sử quét','Chạy lần quét đầu tiên. Lịch sử chỉ chứa kết quả của kết nối hiện tại trong 30 ngày gần nhất.');return;}
 const wrap=node('div',undefined,'table-wrap'),t=node('table'),thead=node('thead'),head=node('tr'),labels=['Thời gian','Region','Trạng thái','Cần kiểm tra','Chi tiết'];
 for(const x of labels){const th=node('th',x);th.scope='col';head.append(th);}thead.append(head);t.append(thead);const body=node('tbody');
 for(const r of historyRows){const tr=node('tr'),st=node('td'),action=node('td'),b=node('button','Xem','button secondary');st.append(badge(r.status));b.setAttribute('aria-label','Xem kết quả '+r.region+' '+date(r.completed_at));
 b.onclick=()=>{const detail=$('history-detail');detail.replaceChildren(node('h3','Kết quả '+date(r.completed_at)+' / '+r.region),badge(r.status));appendResultNotes(detail,r);const content=node('div');renderTable(content,(r.findings||[]).map(f=>({...f,region:r.region})),false);if(!(r.findings||[]).length)emptyState(content,'Không có cảnh báo được lưu',r.status==='SUCCEEDED'?'Không phát hiện ứng viên trong phạm vi lần quét này.':'Lần quét chưa hoàn tất đầy đủ; không thể kết luận không có ứng viên.');detail.append(content);detail.focus();};
 action.append(b);tr.append(node('td',date(r.completed_at)),node('td',r.region),st,node('td',['SUCCEEDED','PARTIAL'].includes(r.status)?String((r.findings||[]).filter(f=>f.level==='REVIEW').length):'—'),action);[...tr.children].forEach((td,i)=>td.dataset.label=labels[i]);body.append(tr);}
 t.append(body);wrap.append(t);c.append(wrap);
 }catch(e){if(generation!==scopeGeneration)return;emptyState(c,'Không tải được lịch sử','Chọn Tải lại để thử lại. '+friendlyError(e.message));throw e;}
}

async function init(){
 closeFindingDetail();const generation=++scopeGeneration;feedbackState.clear();feedbackDays.clear();findingsRevision=0;clearTimeout(pollTimer);const nextProfile=await api('/me');if(generation!==scopeGeneration)return;profile=nextProfile;historyRows=[];$('history-list').replaceChildren();$('history-detail').replaceChildren();$('app').hidden=false;$('welcome').hidden=true;$('login').textContent='Đăng xuất';$('login').onclick=logout;renderPrincipals();$('role').value=profile.role_arn||'';
 $('region-options').replaceChildren();for(const r of regions){const l=node('label'),i=node('input');i.type='checkbox';i.value=r;i.checked=(profile.regions||['ap-southeast-1']).includes(r);const text=node('span',regionNames[r]);text.append(node('small',r));l.append(i,text);$('region-options').append(l);}
 $('service-group-options').replaceChildren();for(const [group,value] of Object.entries(serviceGroups)){const l=node('label'),i=node('input');i.type='checkbox';i.value=group;i.checked=(profile.service_groups||Object.keys(serviceGroups)).includes(group);const text=node('span',value.label);text.append(node('small',value.types.join(' / ')));l.append(i,text);$('service-group-options').append(l);}
 $('filter-type').replaceChildren(new Option('Tất cả',''),...Object.keys(resourceGroups).map(type=>new Option(type,type)));
 $('filter-group').replaceChildren(new Option('Tất cả',''),...Object.entries(serviceGroups).map(([group,value])=>new Option(value.label,group)));
 $('filter-region').replaceChildren(new Option('Tất cả',''),...(profile.regions||[]).map(region=>new Option((regionNames[region]||region)+' — '+region,region)));
 for(const id of ['search','filter-level','filter-acknowledged'])$(id).value='';
 $('settings-fields').replaceChildren();for(const [k,[label,min,max,step]] of Object.entries(fields)){const l=node('label',label),i=node('input');i.id=k;i.type='number';i.required=true;i.min=min;i.max=max;i.step=step;i.value=profile.settings[k];l.append(i,node('small','Trong khoảng '+min+'–'+max));$('settings-fields').append(l);}
 $('email-enabled').checked=!!profile.notifications?.enabled;$('email-enabled').disabled=!profile.email_available;$('save-email').disabled=!profile.email_available;$('email-note').textContent=profile.email_available?(profile.notifications?.email?'Địa chỉ nhận: '+profile.notifications.email:'Sử dụng email Cognito đã xác minh. Nếu SES đang ở sandbox, email nhận cần được xác minh trong SES.'): 'Cảnh báo email chưa được bật cho website này. Bạn vẫn xem cảnh báo trên dashboard.';loadingResults=true;results=[];resultsError=false;render();showPage(location.hash.slice(1)||'overview');await refresh();if(generation!==scopeGeneration)return;status(cfg.demo?'Bạn đang dùng bản demo với dữ liệu mẫu.':'');
}
function navigate(page){if(location.hash.slice(1)===page)showPage(page);else location.hash=page;}
document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>navigate(b.dataset.page));document.querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>navigate(b.dataset.go));window.addEventListener('hashchange',()=>showPage(location.hash.slice(1)));for(const id of ['search','filter-type','filter-level','filter-group','filter-region','filter-acknowledged'])$(id).addEventListener('input',renderFindings);
$('connection-form').onsubmit=e=>{e.preventDefault();run(async()=>{
 let saved=false;const feedback=$('connection-feedback');feedback.hidden=false;feedback.className='';feedback.textContent='Đang xác minh quyền truy cập AWS…';$('connect').textContent='Đang kiểm tra…';
 try{const selected=[...document.querySelectorAll('#region-options input:checked')].map(i=>i.value);
 if(selected.length<1||selected.length>3)throw Error('Chọn từ 1 đến 3 region.');
 const groups=[...document.querySelectorAll('#service-group-options input:checked')].map(i=>i.value);
 if(groups.length<1||groups.length>4)throw Error('Chọn từ 1 đến 4 nhóm dịch vụ.');
 const arn=$('role').value.trim();if(!/^arn:aws:iam::\d{12}:role\/GuardianReadRole-[A-Za-z0-9+=,.@_-]{1,40}$/.test(arn))throw Error('Nhập RoleArn từ Outputs: arn:aws:iam::123456789012:role/GuardianReadRole-<suffix>. Không dùng principal ARN.');
 await api('/connection','PUT',{role_arn:arn,regions:selected,service_groups:groups});saved=true;await init();feedback.textContent='Đã xác minh và lưu kết nối AWS. Tiếp tục bước 3 để quét lần đầu.';status('Đã xác minh và lưu kết nối AWS.');
 }catch(e){feedback.className='error';feedback.textContent=(saved?'Kết nối đã lưu, nhưng chưa tải được dữ liệu mới. Tải lại trang để tiếp tục. ':'')+friendlyError(e.message);throw e;}finally{$('connect').textContent='Kiểm tra và lưu kết nối';}
 },$('connect'));};
$('settings-form').onsubmit=e=>{e.preventDefault();run(async()=>{const v={};for(const [key,[label,min,max,step]] of Object.entries(fields)){const value=$(key).valueAsNumber;if(!Number.isFinite(value)||value<min||value>max||(step===1&&!Number.isInteger(value)))throw Error('Kiểm tra giá trị: '+label+'.');v[key]=value;}profile.settings=await api('/settings','PUT',v);status('Đã lưu ngưỡng và lịch quét.');},$('save-settings'));};
$('save-email').onclick=()=>run(async()=>{profile.notifications=await api('/notifications','PUT',{enabled:$('email-enabled').checked});$('email-note').textContent=profile.notifications.enabled?'Địa chỉ nhận: '+profile.notifications.email:'Đã tắt cảnh báo email.';status('Đã lưu lựa chọn email.');},$('save-email'));
$('scan').onclick=()=>run(async()=>{scanPending=true;render();try{const r=await api('/scans','POST');sessionStorage.setItem('crg-last-scan',r.scan_id);pollCount=0;status('Đã nhận yêu cầu quét. Dashboard tự cập nhật mỗi 5 giây.');await refresh();}finally{scanPending=false;render();}},$('scan'));
$('first-scan').onclick=()=>{navigate('overview');$('scan').click();};
$('refresh').onclick=()=>run(async()=>{pollCount=0;await refresh();status('Đã tải lại kết quả.');},$('refresh'));$('refresh-history').onclick=()=>run(loadHistory,$('refresh-history'));
$('start').onclick=()=>run(login,$('start'));
$('close-finding-detail').onclick=()=>$('finding-dialog').close();
$('finding-dialog').onclose=restoreFindingFocus;

const regionNames={'ap-southeast-1':'Singapore','ap-southeast-2':'Sydney','ap-northeast-1':'Tokyo','us-east-1':'N. Virginia','us-west-2':'Oregon','eu-west-1':'Ireland'};
function friendlyError(message){const translations={
 'Wait 15 minutes between scans':'Chưa đủ 15 phút từ lần quét trước. Đợi đủ thời gian rồi chọn Quét ngay.',
 'Scan lease is active':'Một lần quét đang được xử lý. Chọn Tải lại kết quả để xem tiến độ.',
 'AWS request failed; check role permissions and CloudWatch logs':'AWS từ chối hoặc chưa xử lý được yêu cầu. Kiểm tra RoleArn, hai principal và ExternalId trong trust policy. Nếu vẫn lỗi, nhờ quản trị viên kiểm tra CloudWatch logs.',
 'Cannot access AWS; reconnect and check role permissions':'Không truy cập được AWS. Mở Kết nối AWS, kiểm tra role và xác minh lại kết nối.',
 'Scan did not complete within 15 minutes. Check Lambda failure queue and retry.':'Quét chưa hoàn tất sau 15 phút. Thử quét lại; nếu lặp lại, nhờ quản trị viên kiểm tra hàng đợi lỗi.',
 'Dispatch failed; try another scan later':'Chưa gửi được yêu cầu quét tới bộ xử lý. Thử quét lại sau 15 phút.',
 'Failed to fetch':'Không kết nối được máy chủ. Kiểm tra mạng rồi thử tải lại.',
 'Access token required':'Phiên đăng nhập đã hết hạn. Đăng nhập lại để tiếp tục.',
 'Unauthorized':'Phiên đăng nhập đã hết hạn. Đăng nhập lại để tiếp tục.'};return translations[message]||message;}
function emptyState(container,title,description){container.replaceChildren();const e=node('div',undefined,'empty');e.append(node('strong',title),node('p',description));container.append(e);}
function resultMessage(){
 if(loadingResults)return 'Đang lấy kết quả của kết nối hiện tại. Chưa có số liệu để kết luận.';
 if(resultsError)return 'Chọn Tải lại kết quả để thử lại. Số liệu đã tải trước đó, nếu có, chưa được cập nhật.';
 if(!profile?.role_arn)return 'Tạo role chỉ đọc theo hướng dẫn, xác minh kết nối rồi chạy lần quét đầu tiên.';
 if(results.some(r=>['QUEUED','RUNNING'].includes(r.status))||scanPending)return 'Kết quả tự cập nhật mỗi 5 giây. Các region chưa hoàn tất chưa được tính vào số liệu.';
 if(!results.length)return 'Chọn Quét ngay để đọc tài nguyên trong các region đã chọn. Dấu — có nghĩa chưa có kết quả, không phải không có tài nguyên.';
 if(results.some(r=>['FAILED','TIMED_OUT'].includes(r.status)))return 'Xem lỗi của từng region bên dưới. Kiểm tra kết nối trước khi thử lại; không dùng kết quả này để kết luận toàn bộ account.';
 if(results.some(r=>r.status==='PARTIAL'))return 'Một phần tài nguyên, metrics hoặc cảnh báo chưa được đọc đầy đủ. Số liệu chỉ tính phần kết quả đã nhận.';
 return 'Kết quả chỉ phản ánh các region và loại tài nguyên trong phạm vi quét. Kiểm tra bằng chứng trước khi xử lý; không có cảnh báo không đồng nghĩa không có chi phí.';
}
function appendResultNotes(container,r){
 if(r.error)container.append(node('p',friendlyError(r.error),'footnote'));
 if(r.status==='PARTIAL')container.append(node('p','Kết quả chưa đầy đủ. Giới hạn: 100 tài nguyên mỗi loại, 50 cảnh báo mỗi region; một phần quyền đọc hoặc metrics cũng có thể thiếu.','footnote'));
 for(const e of r.errors||[])container.append(node('p',e.type+': '+e.code,'footnote'));
 const notices={
  FAILED:'Kết quả đã lưu nhưng gửi email thất bại. Liên hệ quản trị viên; cảnh báo vẫn xem được tại đây.',
  UNKNOWN:'Kết quả đã lưu nhưng chưa xác định được SES đã nhận email hay chưa. Kiểm tra trạng thái thông báo trước khi gửi lại để tránh email trùng.',
  STATE_FAILED:'Kết quả đã lưu nhưng không lưu hoặc đọc được trạng thái thông báo; chưa gửi yêu cầu SES. Liên hệ quản trị viên.',
  SENT_UNRECORDED:'SES đã nhận yêu cầu email nhưng chưa lưu được trạng thái gửi. Liên hệ quản trị viên trước khi gửi lại để tránh email trùng.'
 };
 if(notices[r.notification])container.append(node('p',notices[r.notification],'footnote'));
}
function renderPrincipals(){
 $('principals').replaceChildren();for(const [name,value] of [['ApiPrincipal',profile.api_principal],['ScanPrincipal',profile.scan_principal],['ExternalId',profile.external_id]]){
 const row=node('div',undefined,'parameter-row'),label=node('label',name),input=node('textarea'),button=node('button','Sao chép '+name,'button secondary');
 input.id='param-'+name;input.value=value||'';input.readOnly=true;input.rows=name==='ExternalId'?2:3;input.spellcheck=false;label.htmlFor=input.id;button.type='button';button.disabled=!value;
 button.onclick=()=>run(async()=>{try{await navigator.clipboard.writeText(input.value);button.textContent='Đã sao chép '+name;status('Đã sao chép '+name+'.');}catch{input.focus();input.select();status('Không truy cập được clipboard. Giá trị đã được chọn; dùng Ctrl+C hoặc thao tác sao chép trên thiết bị.',true);}},button);
 row.append(label,input,button);$('principals').append(row);}
}

(async()=>{try{const r=await fetch('config.json',{cache:'no-store'});if(!r.ok)throw Error('Không tải được cấu hình ứng dụng. Tải lại trang; nếu lỗi còn tiếp diễn, liên hệ quản trị viên.');cfg=await r.json();$('demo-banner').hidden=!cfg.demo;$('login').onclick=()=>run(login,$('login'));if(cfg.demo)$('start').textContent='Mở dashboard demo';const q=new URLSearchParams(location.search);if(q.has('error'))throw Error(q.get('error_description')||q.get('error'));if(q.has('code')){if(q.get('state')!==sessionStorage.getItem('crg-state')||!sessionStorage.getItem('crg-state'))throw Error('OAuth state không khớp. Hãy đăng nhập lại.');const verifier=sessionStorage.getItem('crg-verifier');const response=await fetch(cfg.auth+'/oauth2/token',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({grant_type:'authorization_code',client_id:cfg.clientId,code:q.get('code'),redirect_uri:cfg.redirect,code_verifier:verifier})});const v=await response.json();if(!response.ok)throw Error('Không đổi được authorization code.');token=v.access_token;sessionStorage.setItem('crg-token',token);sessionStorage.removeItem('crg-state');sessionStorage.removeItem('crg-verifier');history.replaceState({},'',cfg.redirect);}if(token)await init();}catch(e){status(friendlyError(e.message),true);}})();
