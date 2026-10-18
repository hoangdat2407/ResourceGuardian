'use strict';
const $=id=>document.getElementById(id);
let cfg,profile,results=[],historyRows=[],token=sessionStorage.getItem('crg-token'),pollTimer,pollCount=0,loadingResults=true,resultsError=false,scanPending=false;
const pages={overview:['Tổng quan tài nguyên','Tập trung vào tài nguyên cần bạn kiểm tra.'],findings:['Tài nguyên cần kiểm tra','Mỗi cảnh báo đi kèm lý do và bằng chứng.'],history:['Lịch sử quét','Theo dõi kết quả theo thời gian trong từng region.'],connection:['Kết nối tài khoản AWS','Cấp quyền đọc bằng IAM Role và ExternalId riêng.'],settings:['Cấu hình & cảnh báo','Điều chỉnh ngưỡng phát hiện và lịch quét.']};
const regions=['ap-southeast-1','ap-southeast-2','ap-northeast-1','us-east-1','us-west-2','eu-west-1'];
const fields={cpu_percent:['Ngưỡng CPU (%)',1,50,1],network_mib_hour:['Ngưỡng network (MiB/giờ)',.1,100,.1],window_hours:['Cửa sổ EC2 (giờ)',24,168,1],orphan_hours:['Theo dõi EBS / EIP (giờ)',1,168,1],snapshot_days:['Tuổi snapshot (ngày)',7,365,1],interval_hours:['Khoảng quét (giờ)',1,24,1]};
const stateLabels={REVIEW:'Cần kiểm tra',OBSERVING:'Đang quan sát',INSUFFICIENT_DATA:'Thiếu dữ liệu',QUEUED:'Đang chờ',RUNNING:'Đang quét',SUCCEEDED:'Hoàn tất',PARTIAL:'Chưa đầy đủ',FAILED:'Lỗi',TIMED_OUT:'Quá hạn'};
const reasons={'Low CPU and network; confirm intended workload':'CPU và network thấp; kiểm tra mục đích sử dụng.','Missing CloudWatch metrics; not classified as idle':'Thiếu metrics CloudWatch; chưa thể kết luận ít hoạt động.','Instance younger than observation window':'Instance mới hơn cửa sổ quan sát.','Unattached volume; validate data retention':'Volume chưa gắn vào instance; kiểm tra nhu cầu giữ dữ liệu.','Unassociated public IPv4; may be intentionally reserved':'Elastic IP chưa liên kết; có thể đang được giữ có chủ đích.','Old snapshot not referenced by listed AMIs; backup purpose requires review':'Snapshot cũ, không được các AMI đã đọc tham chiếu; kiểm tra mục đích sao lưu.'};
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function status(text,error=false){$('status').hidden=!text;$('status').textContent=text;$('status').className=error?'error':'';}
function badge(s){return node('span',stateLabels[s]||s,'badge '+(s==='REVIEW'?'review':s==='FAILED'||s==='PARTIAL'||s==='TIMED_OUT'?'error':s==='SUCCEEDED'?'good':'observing'));}
function date(t){return t?new Date(t*1000).toLocaleString('vi-VN'):'Chưa có thời gian';}
function b64(b){return btoa(String.fromCharCode(...b)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');}
function random(){const b=new Uint8Array(32);crypto.getRandomValues(b);return b64(b);}
async function login(){if(!cfg)return;if(cfg.demo){token='demo-local-only';sessionStorage.setItem('crg-token',token);await run(init);return;}const verifier=random(),state=random();sessionStorage.setItem('crg-verifier',verifier);sessionStorage.setItem('crg-state',state);const challenge=b64(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(verifier))));location.assign(cfg.auth+'/oauth2/authorize?'+new URLSearchParams({client_id:cfg.clientId,response_type:'code',scope:'openid email aws.cognito.signin.user.admin',redirect_uri:cfg.redirect,state,code_challenge:challenge,code_challenge_method:'S256'}));}
function logout(){clearTimeout(pollTimer);sessionStorage.removeItem('crg-token');token=null;if(cfg.demo){location.reload();return;}location.assign(cfg.auth+'/logout?'+new URLSearchParams({client_id:cfg.clientId,logout_uri:cfg.redirect}));}
async function api(path,method='GET',data){const r=await fetch(cfg.api+path,{method,headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},...(data!==undefined?{body:JSON.stringify(data)}:{})});let v;try{v=await r.json();}catch{throw Error('Máy chủ trả phản hồi không hợp lệ.');}if(r.status===401){clearTimeout(pollTimer);token=null;sessionStorage.removeItem('crg-token');$('app').hidden=true;$('welcome').hidden=false;$('login').textContent='Đăng nhập';$('login').onclick=login;}if(!r.ok)throw Error(friendlyError(v.error||v.message||'HTTP '+r.status));return v;}
async function run(fn,button){if(button)button.disabled=true;try{await fn();}catch(e){status(friendlyError(e.message),true);}finally{if(button){const feedback=$(button.id+'-feedback');if(feedback){feedback.hidden=$('status').hidden;feedback.textContent=$('status').textContent;feedback.className='inline-feedback '+$('status').className;}}if(button)button.disabled=button.dataset.saved==='true';if(button===$('scan')&&profile)render();}}
function showPage(page){if(!profile)return;if(!pages[page])page='overview';for(const key of Object.keys(pages))$('page-'+key).hidden=key!==page;document.querySelectorAll('nav button').forEach(b=>{b.classList.toggle('active',b.dataset.page===page);if(b.dataset.page===page)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});$('page-title').textContent=pages[page][0];$('page-subtitle').textContent=pages[page][1];$('breadcrumb').textContent=document.querySelector('[data-page="'+page+'"]').textContent.replace(/[\d—]+$/,'').trim();document.title=pages[page][0]+' | Cloud Guardian';if(page==='history')run(loadHistory);}
function evidence(f){const v=f.evidence||{},lines=[];if(v.cpu_p95!==undefined)lines.push('CPU p95: '+v.cpu_p95+'%');if(v.network_mib_hour!==undefined)lines.push('Network: '+v.network_mib_hour+' MiB/giờ');if(v.coverage!==undefined)lines.push('Độ phủ: '+Math.round(v.coverage*100)+'%');if(v.observed_hours!==undefined)lines.push('Theo dõi: '+v.observed_hours+' giờ');if(v.size_gib!==undefined)lines.push('Dung lượng: '+v.size_gib+' GiB');if(v.age_days!==undefined)lines.push('Tuổi: '+v.age_days+' ngày');if(v.logical_volume_gib!==undefined)lines.push('Dung lượng logic: '+v.logical_volume_gib+' GiB');if(v.volume_id)lines.push('Volume: '+v.volume_id);return lines.join(' · ')||'Xem lý do cảnh báo';}
function findings(){return results.flatMap(r=>(r.findings||[]).map(f=>({...f,region:r.region})));}
function renderTable(container,items,allowIgnore=true){container.replaceChildren();if(!items.length){container.append(node('div','Không có tài nguyên phù hợp với danh sách này.','empty'));return;}const wrap=node('div',undefined,'table-wrap'),table=node('table'),thead=node('thead'),tr=node('tr');for(const h of ['Tài nguyên','Trạng thái & lý do','Bằng chứng',...(allowIgnore?['Thao tác']:[])]){const th=node('th',h);th.scope='col';tr.append(th);};thead.append(tr);table.append(thead);const body=node('tbody');for(const f of items){const row=node('tr'),resource=node('td');resource.append(node('div',f.type,'resource-type'),node('code',f.resource_id),node('small',f.region));const detail=node('td');detail.append(badge(f.level),node('p',reasons[f.reason]||f.reason));row.append(resource,detail,node('td',evidence(f),'evidence'));if(allowIgnore){const td=node('td'),b=node('button','Bỏ qua 7 ngày','button secondary');b.onclick=()=>run(async()=>{await api('/ignore','PUT',{region:f.region,resource_id:f.resource_id,days:7});b.textContent='Đã ghi nhận';b.dataset.saved='true';status('Đã bỏ qua 7 ngày. Cảnh báo được loại ở lần quét tiếp theo.');},b);td.append(b);row.append(td);}[...row.children].forEach((td,i)=>td.dataset.label=['Tài nguyên','Trạng thái & lý do','Bằng chứng','Thao tác'][i]);body.append(row);}table.append(body);wrap.append(table);container.append(wrap);}
function renderFindings(){
 const q=$('search').value.trim().toLowerCase(),type=$('filter-type').value,level=$('filter-level').value;
 const all=findings(),filtered=all.filter(f=>(!type||f.type===type)&&(!level||f.level===level)&&[f.resource_id,f.reason,reasons[f.reason]||''].some(s=>s.toLowerCase().includes(q)));
 $('findings-scope').textContent=filtered.length+' / '+all.length+' cảnh báo trong kết quả hiện có. '+(results.some(r=>r.status==='PARTIAL')?'Kết quả chưa đầy đủ; một phần tài nguyên hoặc cảnh báo có thể chưa hiển thị.':'Chỉ bao gồm các region đã chọn.');
 renderTable($('findings-list'),filtered);
 if(!filtered.length)emptyState($('findings-list'),q||type||level?'Không khớp bộ lọc':'Chưa có cảnh báo để hiển thị',q||type||level?'Thử xóa từ khóa hoặc chọn Tất cả.':resultMessage());
}

function render(){
 const fs=findings(),measured=results.some(r=>Object.keys(r.counts||{}).length>0&&['SUCCEEDED','PARTIAL'].includes(r.status));
 const busy=scanPending||results.some(r=>['QUEUED','RUNNING'].includes(r.status));
 $('total').textContent=measured?results.reduce((sum,r)=>sum+Object.values(r.counts||{}).reduce((a,b)=>a+b,0),0):'—';
 for(const [id,level] of [['review','REVIEW'],['observing','OBSERVING'],['insufficient','INSUFFICIENT_DATA']])$(id).textContent=measured?fs.filter(f=>f.level===level).length:'—';
 $('nav-count').textContent=measured?fs.filter(f=>f.level==='REVIEW').length:'—';
 $('account-name').textContent=profile.account_id||'Chưa kết nối AWS';$('account-regions').textContent=(profile.regions||[]).join(' / ');
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
 try{results=(await api('/findings')).results;resultsError=false;loadingResults=false;render();
 if(results.some(r=>['QUEUED','RUNNING'].includes(r.status))&&pollCount<185){clearTimeout(pollTimer);pollTimer=setTimeout(()=>{pollCount++;run(refresh);},5000);}else clearTimeout(pollTimer);
 }catch(e){loadingResults=false;resultsError=true;clearTimeout(pollTimer);render();throw e;}
}

async function loadHistory(){
 const c=$('history-list');c.replaceChildren(node('p','Đang tải lịch sử…','muted'));$('history-detail').replaceChildren();
 try{historyRows=(await api('/history')).results;c.replaceChildren();
 if(!historyRows.length){emptyState(c,'Chưa có lịch sử quét','Chạy lần quét đầu tiên. Lịch sử chỉ chứa kết quả của kết nối hiện tại trong 30 ngày gần nhất.');return;}
 const wrap=node('div',undefined,'table-wrap'),t=node('table'),thead=node('thead'),head=node('tr'),labels=['Thời gian','Region','Trạng thái','Cần kiểm tra','Chi tiết'];
 for(const x of labels){const th=node('th',x);th.scope='col';head.append(th);}thead.append(head);t.append(thead);const body=node('tbody');
 for(const r of historyRows){const tr=node('tr'),st=node('td'),action=node('td'),b=node('button','Xem','button secondary');st.append(badge(r.status));b.setAttribute('aria-label','Xem kết quả '+r.region+' '+date(r.completed_at));
 b.onclick=()=>{const detail=$('history-detail');detail.replaceChildren(node('h3','Kết quả '+date(r.completed_at)+' / '+r.region),badge(r.status));appendResultNotes(detail,r);const content=node('div');renderTable(content,(r.findings||[]).map(f=>({...f,region:r.region})),false);if(!(r.findings||[]).length)emptyState(content,'Không có cảnh báo được lưu',r.status==='SUCCEEDED'?'Không phát hiện ứng viên trong phạm vi lần quét này.':'Lần quét chưa hoàn tất đầy đủ; không thể kết luận không có ứng viên.');detail.append(content);detail.focus();};
 action.append(b);tr.append(node('td',date(r.completed_at)),node('td',r.region),st,node('td',['SUCCEEDED','PARTIAL'].includes(r.status)?String((r.findings||[]).filter(f=>f.level==='REVIEW').length):'—'),action);[...tr.children].forEach((td,i)=>td.dataset.label=labels[i]);body.append(tr);}
 t.append(body);wrap.append(t);c.append(wrap);
 }catch(e){emptyState(c,'Không tải được lịch sử','Chọn Tải lại để thử lại. '+friendlyError(e.message));throw e;}
}

async function init(){profile=await api('/me');$('app').hidden=false;$('welcome').hidden=true;$('login').textContent='Đăng xuất';$('login').onclick=logout;renderPrincipals();$('role').value=profile.role_arn||'';$('region-options').replaceChildren();for(const r of regions){const l=node('label'),i=node('input');i.type='checkbox';i.value=r;i.checked=(profile.regions||['ap-southeast-1']).includes(r);const text=node('span',regionNames[r]);text.append(node('small',r));l.append(i,text);$('region-options').append(l);}$('settings-fields').replaceChildren();for(const [k,[label,min,max,step]] of Object.entries(fields)){const l=node('label',label),i=node('input');i.id=k;i.type='number';i.required=true;i.min=min;i.max=max;i.step=step;i.value=profile.settings[k];l.append(i,node('small','Trong khoảng '+min+'–'+max));$('settings-fields').append(l);}$('email-enabled').checked=!!profile.notifications?.enabled;$('email-enabled').disabled=!profile.email_available;$('save-email').disabled=!profile.email_available;$('email-note').textContent=profile.email_available?(profile.notifications?.email?'Địa chỉ nhận: '+profile.notifications.email:'Sử dụng email Cognito đã xác minh. Nếu SES đang ở sandbox, email nhận cần được xác minh trong SES.'): 'Cảnh báo email chưa được bật cho website này. Bạn vẫn xem cảnh báo trên dashboard.';loadingResults=true;results=[];resultsError=false;render();showPage(location.hash.slice(1)||'overview');await refresh();status(cfg.demo?'Bạn đang dùng bản demo với dữ liệu mẫu.':'');}
function navigate(page){if(location.hash.slice(1)===page)showPage(page);else location.hash=page;}
document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>navigate(b.dataset.page));document.querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>navigate(b.dataset.go));window.addEventListener('hashchange',()=>showPage(location.hash.slice(1)));for(const id of ['search','filter-type','filter-level'])$(id).addEventListener('input',renderFindings);
$('connection-form').onsubmit=e=>{e.preventDefault();run(async()=>{
 let saved=false;const feedback=$('connection-feedback');feedback.hidden=false;feedback.className='';feedback.textContent='Đang xác minh quyền truy cập AWS…';$('connect').textContent='Đang kiểm tra…';
 try{const selected=[...document.querySelectorAll('#region-options input:checked')].map(i=>i.value);
 if(selected.length<1||selected.length>3)throw Error('Chọn từ 1 đến 3 region.');
 const arn=$('role').value.trim();if(!/^arn:aws:iam::\d{12}:role\/GuardianReadRole-[A-Za-z0-9+=,.@_-]{1,40}$/.test(arn))throw Error('Nhập RoleArn từ Outputs: arn:aws:iam::123456789012:role/GuardianReadRole-<suffix>. Không dùng principal ARN.');
 await api('/connection','PUT',{role_arn:arn,regions:selected});saved=true;await init();feedback.textContent='Đã xác minh và lưu kết nối AWS. Tiếp tục bước 3 để quét lần đầu.';status('Đã xác minh và lưu kết nối AWS.');
 }catch(e){feedback.className='error';feedback.textContent=(saved?'Kết nối đã lưu, nhưng chưa tải được dữ liệu mới. Tải lại trang để tiếp tục. ':'')+friendlyError(e.message);throw e;}finally{$('connect').textContent='Kiểm tra và lưu kết nối';}
 },$('connect'));};
$('settings-form').onsubmit=e=>{e.preventDefault();run(async()=>{const v={};for(const k of Object.keys(fields))v[k]=Number($(k).value);profile.settings=await api('/settings','PUT',v);status('Đã lưu ngưỡng và lịch quét.');},$('save-settings'));};
$('save-email').onclick=()=>run(async()=>{profile.notifications=await api('/notifications','PUT',{enabled:$('email-enabled').checked});$('email-note').textContent=profile.notifications.enabled?'Địa chỉ nhận: '+profile.notifications.email:'Đã tắt cảnh báo email.';status('Đã lưu lựa chọn email.');},$('save-email'));
$('scan').onclick=()=>run(async()=>{scanPending=true;render();try{const r=await api('/scans','POST',{});sessionStorage.setItem('crg-last-scan',r.scan_id);pollCount=0;status('Đã nhận yêu cầu quét. Dashboard tự cập nhật mỗi 5 giây.');await refresh();}finally{scanPending=false;render();}},$('scan'));
$('first-scan').onclick=()=>{navigate('overview');$('scan').click();};
$('refresh').onclick=()=>run(async()=>{pollCount=0;await refresh();status('Đã tải lại kết quả.');},$('refresh'));$('refresh-history').onclick=()=>run(loadHistory,$('refresh-history'));
$('start').onclick=()=>run(login,$('start'));

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
function appendResultNotes(container,r){if(r.error)container.append(node('p',friendlyError(r.error),'footnote'));if(r.status==='PARTIAL')container.append(node('p','Kết quả chưa đầy đủ. Giới hạn: 100 tài nguyên mỗi loại, 50 cảnh báo mỗi region; một phần quyền đọc hoặc metrics cũng có thể thiếu.','footnote'));for(const e of r.errors||[])container.append(node('p',e.type+': '+e.code,'footnote'));if(r.notification==='FAILED')container.append(node('p','Kết quả đã lưu nhưng gửi email thất bại. Liên hệ quản trị viên; cảnh báo vẫn xem được tại đây.','footnote'));}
function renderPrincipals(){
 $('principals').replaceChildren();for(const [name,value] of [['ApiPrincipal',profile.api_principal],['ScanPrincipal',profile.scan_principal],['ExternalId',profile.external_id]]){
 const row=node('div',undefined,'parameter-row'),label=node('label',name),input=node('textarea'),button=node('button','Sao chép '+name,'button secondary');
 input.id='param-'+name;input.value=value||'';input.readOnly=true;input.rows=name==='ExternalId'?2:3;input.spellcheck=false;label.htmlFor=input.id;button.type='button';button.disabled=!value;
 button.onclick=()=>run(async()=>{try{await navigator.clipboard.writeText(input.value);button.textContent='Đã sao chép '+name;status('Đã sao chép '+name+'.');}catch{input.focus();input.select();status('Không truy cập được clipboard. Giá trị đã được chọn; dùng Ctrl+C hoặc thao tác sao chép trên thiết bị.',true);}},button);
 row.append(label,input,button);$('principals').append(row);}
}

(async()=>{try{const r=await fetch('config.json',{cache:'no-store'});if(!r.ok)throw Error('Không tải được cấu hình ứng dụng. Tải lại trang; nếu lỗi còn tiếp diễn, liên hệ quản trị viên.');cfg=await r.json();$('demo-banner').hidden=!cfg.demo;$('login').onclick=()=>run(login,$('login'));if(cfg.demo)$('start').textContent='Mở dashboard demo';const q=new URLSearchParams(location.search);if(q.has('error'))throw Error(q.get('error_description')||q.get('error'));if(q.has('code')){if(q.get('state')!==sessionStorage.getItem('crg-state')||!sessionStorage.getItem('crg-state'))throw Error('OAuth state không khớp. Hãy đăng nhập lại.');const verifier=sessionStorage.getItem('crg-verifier');const response=await fetch(cfg.auth+'/oauth2/token',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({grant_type:'authorization_code',client_id:cfg.clientId,code:q.get('code'),redirect_uri:cfg.redirect,code_verifier:verifier})});const v=await response.json();if(!response.ok)throw Error('Không đổi được authorization code.');token=v.access_token;sessionStorage.setItem('crg-token',token);sessionStorage.removeItem('crg-state');sessionStorage.removeItem('crg-verifier');history.replaceState({},'',cfg.redirect);}if(token)await init();}catch(e){status(friendlyError(e.message),true);}})();
