/** 发布恢复控制台：固定预览、明确选择、幂等操作与持久结果。 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id), base = '/api/publishing-recovery';
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const time = v => v ? new Date(typeof v === 'number' ? v*1000 : v.includes('T') ? v : v.replace(' ','T')+'Z').toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}) : '未知，等待条件变化';
  const labels = {ready:'可直接续跑',recoverable:'等待恢复条件',manual:'需登录或人工处理',protected:'已有提交证据 · 禁止重投',other:'独立流程',PLANNED:'正在登记恢复',QUEUED:'已入恢复队列',COMPLETED:'批次执行结束',BLOCKED:'恢复未执行',CANCELLED:'已取消',WAITING:'等待',RUNNING:'执行中',SKIPPED:'跳过',FAILED:'本次失败',ATTENTION:'需人工核实',PUBLISHED:'已发布',SUBMITTED_UNVERIFIED:'已提交或结果待确认'};
  let account=null, fresh=false, previewValid=false, preview=null, selected=new Set(), page=1, historyPage=1, busy=false, draft=null, pending=null, focusBack=null, previewGeneration=0;
  const size=20, store='vp-publishing-recovery-pending';
  // 局域网 HTTP 无 randomUUID，getRandomValues 在非安全上下文仍可生成随机身份。
  function operationId() {
    if (crypto.randomUUID) return crypto.randomUUID();
    const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
    const h=[...bytes].map(v=>v.toString(16).padStart(2,'0')).join('');
    return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
  }
  const params=new URLSearchParams(location.search);
  $('pr-window').value=['today','24h','custom'].includes(params.get('window'))?params.get('window'):'24h';
  $('pr-ready').checked=params.get('include_ready')==='1';
  $('pr-custom').hidden=$('pr-window').value!=='custom';
  try { pending=JSON.parse(sessionStorage.getItem(store)||'null'); } catch (_) {}
  function url() {
    const u=new URL(location.href);u.searchParams.set('window',$('pr-window').value);
    if(preview){u.searchParams.set('preview',preview.preview_id);u.searchParams.set('page',page);sessionStorage.setItem('vp-recovery-selection-'+preview.preview_id,JSON.stringify([...selected]));}
    history.replaceState(null,'',u);
  }
  async function api(path, options={}) {
    const response=await fetch(base+path,{...options,headers:{'Content-Type':'application/json'},signal:AbortSignal.timeout(12000)});
    let body;try{body=await response.json();}catch(_){throw new Error('服务器响应无法读取');}
    if(!response.ok){const e=new Error(typeof body.detail==='string'?body.detail:'输入无效，请检查后重试');e.status=response.status;throw e;}
    return body;
  }
  function controls() {
    document.querySelectorAll('[data-recovery]').forEach(b=>b.disabled=busy||!fresh||Boolean(pending)||(['retry','combined'].includes(b.dataset.recovery)&&(!selected.size||selected.size>1000||!previewValid||Date.now()/1000>preview.created_at+900)));
    $('pr-preview').disabled=busy;$('pr-refresh').disabled=busy;
    $('pr-check').hidden=!pending;$('pr-check').disabled=busy;
    $('pr-confirm').disabled=busy;$('pr-cancel').disabled=busy;
    $('pr-selected').textContent=`已选 ${selected.size} 项`;
  }
  async function loadStatus() {
    try {
      const rt=await api('/status');account=rt;fresh=true;
      $('pr-status').textContent=`${rt.account} · ${rt.allowed?'本地账户限制已满足，仍需逐任务检查':`有 ${rt.blockers.length} 项阻塞`} · 读取于 ${time(Date.now()/1000)}`;
      $('pr-metrics').innerHTML=[['本地有效额度',`${rt.sessions_24h_count} / ${rt.daily_limit}`,'过去滚动 24 小时'],['真实访问历史',`${rt.actual_sessions_24h_count} 次`,rt.quota_reset_at?`最近额度重置 ${time(rt.quota_reset_at)}`:'保留全部记录'],['最早账户准入',rt.allowed?'现在':time(rt.until),`当前间隔 ${rt.interval_seconds} 秒`]].map(([l,v,h])=>`<div class="pr-metric"><span>${esc(l)}</span><strong>${esc(v)}</strong><small class="hint">${esc(h)}</small></div>`).join('');
      $('pr-blockers').innerHTML=rt.blockers.map(b=>`<li>${esc(b.reason)} · ${esc(time(b.until))}</li>`).join('');
      $('pr-owners').textContent=`浏览器：${rt.browser_owner&&Object.keys(rt.browser_owner).length?JSON.stringify(rt.browser_owner):'无实际占用'}；加工：${rt.processing_owner&&Object.keys(rt.processing_owner).length?JSON.stringify(rt.processing_owner):'无实际占用'}；美股软避让：${rt.market_avoidance?'当前生效':'当前未生效'}（America/New_York）；时间显示均为北京时间。`;
      $('pr-sessions').innerHTML=(rt.recent_sessions||[]).slice().reverse().map(s=>`<p>${esc(time(s.at))} · ${esc(s.purpose)} · ${esc(String(s.task).split('/').pop())}</p>`).join('')||'<p class="hint">最近 24 小时没有真实访问。</p>';
    } catch(e) { fresh=false;$('pr-status').textContent='账户状态读取失败，已保留旧记录但禁止执行：'+e.message; }
    controls();
  }
  function rows() {
    if(!preview)return;
    const pages=Math.max(1,Math.ceil(preview.items.length/size));page=Math.min(page,pages);
    const list=preview.items.slice((page-1)*size,page*size);
    $('pr-results').hidden=false;$('pr-select-all').disabled=false;$('pr-clear').disabled=false;
    $('pr-summary').textContent=`固定范围 ${time(preview.start_bj)} 至 ${time(preview.end_bj)}，共 ${preview.items.length} 项，其中 ${preview.items.filter(i=>i.eligible).length} 项可选。预览 15 分钟有效；单批最多 1000 项，超过时请缩短时间范围。执行前再次复核。`;
    $('pr-rows').innerHTML=list.map(i=>`<tr><td><input type="checkbox" data-video="${i.id}" aria-label="选择 ${esc(i.title)}${i.slice_index?` 切片 ${i.slice_index}`:''}" ${!i.eligible?'disabled':''} ${selected.has(i.id)?'checked':''}></td><td>${esc(i.title)}<small>${esc(i.youtube_id)}${i.slice_index?` · 切片 ${i.slice_index}`:''} · ${esc(i.status)} · 分数 ${esc(i.score??'未知')}</small></td><td>${esc(time(i.failed_at))}${i.estimated?'<small>估算 · 仅有更新时间</small>':''}</td><td>${esc(labels[i.category]||i.category)}<small>${esc(i.reason||'未记录失败摘要')}</small>${i.href?`<a href="${esc(i.href)}">前往处理</a>`:''}${i.operation_id?`<small>批次 ${esc(i.operation_id)}</small>`:''}${i.blockers?.map(b=>`<small>${esc(b.reason)} · ${esc(time(b.until))}</small>`).join('')||''}</td><td>${esc(i.stage)}<small>${esc(i.artifacts)}</small><small>${esc(i.approval)}</small></td></tr>`).join('')||'<tr><td colspan="5">当前范围没有任务，可调整时间后重新预览。</td></tr>';
    $('pr-page').textContent=`第 ${page} / ${pages} 页`;$('pr-prev').disabled=page<=1;$('pr-next').disabled=page>=pages;
    const defaults=list.filter(i=>i.eligible&&!i.estimated), n=defaults.filter(i=>selected.has(i.id)).length;
    $('pr-page-select').checked=defaults.length>0&&n===defaults.length;$('pr-page-select').indeterminate=n>0&&n<defaults.length;
    $('pr-page-select').disabled=!defaults.length;url();controls();
  }
  async function loadPreview(key=null) {
    if(busy)return;const generation=++previewGeneration;busy=true;controls();
    $('pr-feedback').textContent='正在预览固定范围…';
    try {
      let result;
      if(key) {
        result=await api('/previews/'+encodeURIComponent(key)+'?size=100');
        const all=[...result.items];for(let n=2;n<=Math.ceil(result.total/100);n++){all.push(...(await api(`/previews/${encodeURIComponent(key)}?size=100&page=${n}`)).items);}result.items=all;
      } else {
        let start=$('pr-start').value.trim(),end=$('pr-end').value.trim();
        for(const [id,v] of [['pr-start',start],['pr-end',end]]) {
          const invalid=$('pr-window').value==='custom'&&!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(v);
          $(id).setAttribute('aria-invalid',String(invalid));if(invalid){$(id).focus();throw new Error('请按 YYYY-MM-DDTHH:mm 填写北京时间');}
        }
        result=await api('/preview',{method:'POST',body:JSON.stringify({window:$('pr-window').value,start:start?start+'+08:00':null,end:end?end+'+08:00':null,include_ready:$('pr-ready').checked})});
      }
      if(generation!==previewGeneration)return;
      preview=result;previewValid=true;selected.clear();
      if(key){try{const saved=JSON.parse(sessionStorage.getItem('vp-recovery-selection-'+key)||'[]');const eligible=new Set(preview.items.filter(i=>i.eligible).map(i=>i.id));saved.filter(i=>eligible.has(i)).forEach(i=>selected.add(i));}catch(_){}}
      $('pr-ready').checked=Boolean(preview.include_ready);
      page=key?Math.max(1,Number(params.get('page'))||1):1;
      $('pr-feedback').textContent='预览完成。请勾选具体任务；后续新失败不会加入本次操作。';rows();
      await loadStatus();
    } catch(e) {previewValid=false;$('pr-feedback').textContent='预览读取失败，旧结果仅供参考，选择已保留：'+e.message;}
    finally{busy=false;controls();}
  }
  async function loadHistory() {
    try {
      const data=await api('/operations?page='+historyPage);
      $('pr-history-feedback').textContent=`已读取 ${data.total} 个操作；批次结束不等于平台已接受或公开。`;
      $('pr-history-page').textContent=`第 ${historyPage} / ${Math.max(1,Math.ceil(data.total/10))} 页`;
      $('pr-history-prev').disabled=historyPage<=1;$('pr-history-next').disabled=historyPage*10>=data.total;
      const open=new Set([...document.querySelectorAll('.pr-operation[open]')].map(e=>e.dataset.operation));
      $('pr-history').innerHTML=data.items.map(o=>`<details class="pr-operation" data-operation="${esc(o.id)}" ${open.has(o.id)||new URLSearchParams(location.search).get('operation')===o.id?'open':''}><summary>${esc(time(o.created))} · ${esc(labels[o.state]||o.state)} · ${o.items.length} 项</summary><p>操作 ID：${esc(o.id)}</p>${o.reason?`<p>${esc(o.reason)}</p>`:''}${o.receipt?`<p>有效用量 ${o.receipt.before.sessions_24h_count} → ${o.receipt.after.sessions_24h_count}；真实历史 ${o.receipt.after.actual_sessions_24h_count} 次；上限 ${o.receipt.after.daily_limit}。${o.receipt.after.blockers.length?'仍有阻塞：'+esc(o.receipt.after.blockers.map(b=>b.reason).join('；')):'本地账户限制已满足，任务仍须逐项检查。'}</p>`:''}<ol>${o.items.map(i=>`<li><strong>${esc(i.zh_title||i.title||i.original.title)}${i.original.slice_index?` · 切片 ${i.original.slice_index}`:''}</strong> · ${esc(labels[i.state]||i.state)}<br>${esc(i.reason||'等待正式领取')} ${i.next_at?'· 最早 '+esc(time(i.next_at)):''}${i.permit_expires?`<br><small>单次制作避让：${i.permit_used?'已消费':i.permit_expires<Date.now()/1000?'已到期':'有效至 '+esc(time(i.permit_expires))}</small>`:''}</li>`).join('')}</ol>${o.items.some(i=>['RESERVED','WAITING'].includes(i.state))?`<button type="button" data-cancel="${esc(o.id)}">取消尚未启动项</button>`:''}</details>`).join('')||'<p class="hint">尚无恢复操作。</p>';
    } catch(e){$('pr-history-feedback').textContent='操作记录读取失败，旧记录可能过期：'+e.message;}
  }
  async function open(action, button) {
    if(busy||pending)return;await loadStatus();if(!fresh)return;
    const needsSelection=['retry','combined'].includes(action);
    if(needsSelection&&(!preview||!previewValid||!selected.size||selected.size>1000||Date.now()/1000>preview.created_at+900))return;
    draft={operation_id:operationId(),expected_version:needsSelection?preview.account_version:account.version,preview_id:needsSelection?preview.preview_id:null,selected_ids:needsSelection?[...selected]:[],reset_quota:['quota','all','combined'].includes(action),reset_cooldown:['cooldown','all','combined'].includes(action),priority:needsSelection&&$('pr-priority').checked,reset_backoff:needsSelection&&$('pr-backoff').checked,skip_avoidance:needsSelection&&$('pr-avoidance').checked};
    focusBack=button;
    $('pr-confirm-body').innerHTML=`<p>账户：${esc(account.account)}。${draft.reset_quota?'本地有效访问额度将归零，真实历史保留，上限不变。':''}${draft.reset_cooldown?'清除本地平台退避、会话间隔和恢复期；无法改变平台真实限制。':''}</p><p>${needsSelection?`仅续跑明确选中的 ${selected.size} 项，可能执行加工并向视频号发表。`:'本次只重置本地限制，不创建视频重试。现有自动队列可能随后继续。'}</p>${needsSelection?`<ul>${preview.items.filter(i=>selected.has(i.id)).map(i=>`<li>${esc(i.title)} · ${esc(i.youtube_id)}${i.slice_index?' · 切片 '+i.slice_index:''}</li>`).join('')}</ul><p>${draft.priority?'所选任务优先尝试一次。':''}${draft.reset_backoff?'仅解除有零进度未提交凭据的上传退避一次。':''}${draft.skip_avoidance?'本次跳过制作时段和盘中软避让，30 分钟未消费即失效，一次只加工一项。':''}</p>`:''}<p class="hint">已有提交记录不重投；内容审批、真实会话锁和维护准入继续生效。再次收到 -360 / 429 会重新停止并退避。</p>`;
    $('pr-confirm-feedback').textContent='';$('pr-confirm-dialog').showModal();$('pr-cancel').focus();
  }
  function showOperation(o) {
    pending=null;sessionStorage.removeItem(store);const u=new URL(location.href);u.searchParams.set('operation',o.id);history.replaceState(null,'',u);
    $('pr-feedback').textContent=`操作已记录：${labels[o.state]||o.state}，${o.items.length} 项。${o.reason||'逐项结果见操作记录。'}`;
  }
  async function submit(original=draft) {
    if(busy||!original)return;busy=true;pending=original;sessionStorage.setItem(store,JSON.stringify(pending));controls();
    $('pr-confirm-feedback').textContent='正在登记恢复，请勿重复操作…';
    try {
      const result=await api('/operations',{method:'POST',body:JSON.stringify(original)});showOperation(result);$('pr-confirm-dialog').close();fresh=false;await Promise.all([loadStatus(),loadHistory()]);
    } catch(e) {
      if([403,409,422].includes(e.status)) {pending=null;sessionStorage.removeItem(store);fresh=false;if(original.selected_ids.length)previewValid=false;$('pr-confirm-feedback').textContent='操作未完成：'+e.message+'。请重新预览或刷新账户后确认。';}
      else {$('pr-confirm-feedback').textContent='结果尚未确认。请保留原操作 ID 并核对，不能新建重复操作。';$('pr-history-feedback').textContent=`待核对操作 ${original.operation_id}：${e.message}`;}
    } finally{busy=false;controls();}
  }
  async function checkPending() {
    if(!pending||busy)return;busy=true;controls();const original=pending;
    try {showOperation(await api('/operations/'+encodeURIComponent(original.operation_id)));await loadHistory();await loadStatus();}
    catch(e){if(e.status===404){busy=false;await submit(original);}else{$('pr-history-feedback').textContent='原操作结果仍未确认：'+e.message;}}
    finally{busy=false;controls();}
  }
  $('pr-filter').addEventListener('submit',e=>{e.preventDefault();loadPreview();});
  $('pr-window').addEventListener('change',()=>{$('pr-custom').hidden=$('pr-window').value!=='custom';url();});
  $('pr-rows').addEventListener('change',e=>{const id=Number(e.target.dataset.video);if(id){e.target.checked?selected.add(id):selected.delete(id);rows();}});
  $('pr-page-select').addEventListener('change',e=>{preview.items.slice((page-1)*size,page*size).filter(i=>i.eligible&&!i.estimated).forEach(i=>e.target.checked?selected.add(i.id):selected.delete(i.id));rows();});
  $('pr-select-all').addEventListener('click',()=>{preview.items.filter(i=>i.eligible&&!i.estimated).forEach(i=>selected.add(i.id));rows();});
  $('pr-clear').addEventListener('click',()=>{selected.clear();rows();});
  $('pr-prev').addEventListener('click',()=>{page--;rows();});$('pr-next').addEventListener('click',()=>{page++;rows();});
  document.querySelectorAll('[data-recovery]').forEach(b=>b.addEventListener('click',()=>open(b.dataset.recovery,b)));
  $('pr-cancel').addEventListener('click',()=>$('pr-confirm-dialog').close());
  $('pr-confirm-dialog').addEventListener('cancel',e=>{if(busy)e.preventDefault();});
  $('pr-confirm-dialog').addEventListener('close',()=>{draft=null;focusBack?.focus();});
  $('pr-confirm').addEventListener('click',()=>submit());$('pr-check').addEventListener('click',checkPending);
  $('pr-refresh').addEventListener('click',()=>Promise.all([loadStatus(),loadHistory()]));
  $('pr-history-prev').addEventListener('click',()=>{historyPage--;loadHistory();});$('pr-history-next').addEventListener('click',()=>{historyPage++;loadHistory();});
  $('pr-history').addEventListener('click',async e=>{const id=e.target.dataset.cancel;if(!id||busy)return;busy=true;e.target.disabled=true;try{await api('/operations/'+encodeURIComponent(id)+'/cancel',{method:'POST'});await loadHistory();}catch(error){$('pr-history-feedback').textContent='取消未确认，请刷新核实：'+error.message;}finally{busy=false;controls();}});
  window.addEventListener('offline',()=>{fresh=false;$('pr-status').textContent='网络已断开，记录仅供参考；恢复连接后请刷新。';controls();});
  loadStatus();loadHistory();if(params.get('preview'))loadPreview(params.get('preview'));
  setInterval(()=>{if(!document.hidden&&!busy&&!$('pr-confirm-dialog').open){loadStatus();loadHistory();}},15000);
  controls();
})();
