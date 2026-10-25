/* Modification History: 1.0.0 | 2026-10-25 | Codex | 真实只读分页、可恢复筛选和报告；动态内容仅 textContent。 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id), root = document.querySelector('.english-console');
  const query = new URLSearchParams(location.search);
  const categories = ['all', 'active', 'attention', 'done'];
  let category = categories.includes(query.get('category')) ? query.get('category') : 'all';
  let page = Math.max(1, Number(query.get('page')) || 1), selected = query.get('task') || '';
  let items = [], current, request, reportRequest, timer, composing = false, listY = 0, opener, loaded = false;
  const reportNames = {history:'处理记录',asset:'成片资料',audio:'音频质量',language:'语言准确性',visual:'视觉检查',safety:'内容安全',platform:'平台回读依据'};
  const platformNames = {PUBLISHED:'已公开（历史回读）',UNDER_REVIEW:'审核中',SUBMITTED_BOUND:'已受理',UNCERTAIN:'结果不明',NOT_SUBMITTED:'未提交',UNKNOWN:'暂无可核实记录',FAILED:'处理失败',SUBMITTING:'投稿中',PENDING:'等待同步',CANCELED:'已取消',LOGIN_REQUIRED:'等待登录',REJECTED:'平台拒绝'};
  $('ew-search').value = query.get('q') || '';
  $('ew-trigger').value = query.get('trigger') || '';
  $('ew-date').value = query.get('date') || '';
  function node(tag, text, cls) {const n=document.createElement(tag); if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
  function button(text, action) {const n=node('button',text);n.type='button';n.addEventListener('click',action);return n;}
  function time(value) {return value ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'short',hour12:false}).format(new Date(value))+'（北京）' : '时间未知';}
  function remember() {
    const params=new URLSearchParams();
    for(const [key,value] of Object.entries({q:$('ew-search').value.trim(),category,trigger:$('ew-trigger').value,date:$('ew-date').value,page:String(page),task:selected}))if(value)params.set(key,value);
    history.replaceState(null,'',location.pathname+'?'+params.toString());
  }
  async function fetchJSON(url, signal) {
    const response=await fetch(url,{signal,cache:'no-store',headers:{Accept:'application/json'}});
    if(!response.ok)throw new Error(response.status===403?'本机会话已失效，请重新打开本页':response.status===422?'筛选条件无效，请检查日期或重置条件':'读取失败，请稍后刷新');
    return response.json();
  }
  function filters() {
    $('ew-clear-search').hidden=!$('ew-search').value;
    document.querySelectorAll('[data-category]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.category===category)));
    $('ew-more').textContent=($('ew-trigger').value||$('ew-date').value)?'筛选已启用':'更多筛选';
  }
  async function load() {
    request?.abort(); const controller=new AbortController();request=controller;
    const params=new URLSearchParams({q:$('ew-search').value.trim(),category,trigger:$('ew-trigger').value,date:$('ew-date').value,page:String(page)});
    filters();$('ew-tasks').setAttribute('aria-busy','true');$('ew-refresh').disabled=true;
    $('ew-feedback').classList.remove('error');$('ew-feedback').textContent=loaded?'正在刷新，以下保留上次读取的记录…':'正在读取真实任务…';
    const timeout=setTimeout(()=>controller.abort('timeout'),15000);
    try {
      const data=await fetchJSON('/api/english-world/console?'+params,controller.signal);
      if(controller!==request)return;
      loaded=true;items=data.items;page=data.page;
      for(const key of categories)$('count-'+key).textContent=data.counts[key];
      current=items.find(r=>r.id===selected)||items[0];selected=current?.id||'';
      renderList();renderDetail();remember();
      $('ew-results').textContent=data.total?`找到 ${data.total} 条任务 · 每页最多 20 条`:'没有匹配任务。请调整或重置筛选条件。';
      $('ew-page').textContent=`${data.page} / ${data.pages} 页`;
      $('ew-prev').disabled=data.page<=1;$('ew-next').disabled=data.page>=data.pages;
      $('ew-feedback').textContent=`已读取 ${time(data.fetched_at)} · 本地台账${data.warnings.length?' · '+data.warnings.join('；'):''}`;
      $('ew-schedule-text').textContent=`制作时刻：${data.schedule.slots.join('、')}（北京时间）。${data.schedule.installed}。自动投稿配置：${data.schedule.auto_submission?'开启':'关闭'}；实际执行仍受原有门禁约束。`;
      $('ew-coverage').textContent=`统计范围：最近最多 1,000 条人工任务、1,000 条成片审核项和 200 次定时运行；按明确关联去重。账本共 ${data.coverage.jobs} 条人工任务、${data.coverage.reviews} 条成片、${data.coverage.run_logs} 次运行${data.coverage.limited?'；已达到窗口上限，统计不代表全部历史':'。'}。`;
    } catch(error) {
      if(controller!==request)return;
      if(error.name==='AbortError' && controller.signal.reason!=='timeout')return;
      $('ew-feedback').classList.add('error');$('ew-feedback').textContent=(controller.signal.reason==='timeout'?'读取超时，请刷新':error.message)+(loaded?'；以下为上次记录，当前进度未知。':'；尚未取得任务。');
      if(!loaded){$('ew-tasks').replaceChildren(node('p','任务暂不可读取，请刷新重试。','ew-empty'));$('ew-detail').replaceChildren(node('p','暂无可读取详情。','ew-empty'));}
    } finally {clearTimeout(timeout);if(controller===request){$('ew-tasks').setAttribute('aria-busy','false');$('ew-refresh').disabled=false;}}
  }
  function renderList() {
    $('ew-tasks').replaceChildren();
    for(const row of items){
      const b=button('',()=>choose(row.id,true));b.className='ew-task';b.dataset.task=row.id;b.setAttribute('aria-pressed',String(row.id===selected));
      b.append(node('strong',row.title),node('small',row.source));
      b.append(node('span',row.label,'ew-badge'+(row.attention?' attention':'')));
      b.append(node('small',({manual:'人工任务',scheduled:'定时运行',auto:'独立成片'})[row.trigger]+' · '+time(row.created_at)));
      $('ew-tasks').append(b);
    }
    if(!items.length)$('ew-tasks').append(node('p','没有匹配任务。重置条件可恢复列表。','ew-empty'));
  }
  function choose(id, entered) {
    current=items.find(r=>r.id===id);selected=id;renderList();renderDetail();remember();
    $('ew-detail').scrollTop=0;
    if(entered&&matchMedia('(max-width:1024px)').matches){listY=window.scrollY;root.classList.add('is-detail');window.scrollTo(0,0);$('ew-task-heading')?.focus();}
  }
  function section(title) {const s=node('section',undefined,'ew-section');s.append(node('h3',title));return s;}
  function renderDetail() {
    const detail=$('ew-detail');detail.replaceChildren();
    if(!current){detail.append(node('p','没有匹配的任务详情。','ew-empty'));root.classList.remove('is-detail');return;}
    const row=current;
    const back=button('← 返回任务列表',()=>{root.classList.remove('is-detail');window.scrollTo(0,listY);document.querySelector(`[data-task="${CSS.escape(selected)}"]`)?.focus({preventScroll:true});});back.className='ew-detail-back';detail.append(back);
    const header=node('div',undefined,'ew-detail-header'),heading=node('h2',row.title);heading.id='ew-task-heading';heading.tabIndex=-1;
    header.append(heading,node('p',row.source,'hint'),node('span',row.label,'ew-badge'+(row.attention?' attention':'')),node('p','最近更新：'+time(row.updated_at),'hint'));detail.append(header);
    const status=section('当前进度');status.append(node('p',row.error||'以最近台账状态为准；没有额外的执行心跳时不估算进度百分比。'));
    const stages=node('div',undefined,'ew-stage');
    for(const [name,value] of [['成片资料',row.review_id?'已登记成片，文件见证据':'尚无关联成片台账'],['投稿授权',row.approved_at?'授权记录 '+time(row.approved_at):'暂无授权记录'],['平台记录',platformNames[row.wechat.state]||row.wechat.state]]){const stage=node('div');stage.append(node('span',name),node('p',value));stages.append(stage);}
    status.append(stages);detail.append(status);
    const evidence=section('质量与证据');const grid=node('div',undefined,'ew-reports');
    for(const [key,label] of Object.entries(reportNames)){const b=button(label+' →',()=>openReport(row.id,key,b));b.dataset.report=key;grid.append(b);}evidence.append(grid,node('p','缺失、未绑定或旧文件报告不会显示为当前通过。','hint'));detail.append(evidence);
    const platform=section('平台投递');const platformGrid=node('div',undefined,'ew-platform');
    for(const [key,name] of [['wechat','视频号'],['douyin','抖音']]){const data=row[key],box=node('div');box.append(node('h3',name),node('p',platformNames[data.state]||data.state),node('p','作品 ID：'+(data.post_id||'未登记'),'hint'),node('p','记录时间：'+time(data.observed_at),'hint'));platformGrid.append(box);}platform.append(platformGrid,node('p','本地历史记录不代表此刻公开可见；刷新不会触发平台回查。','hint'));detail.append(platform);
  }
  async function openReport(task,kind,from) {
    reportRequest?.abort();const controller=new AbortController();reportRequest=controller;opener=from;
    $('ew-report-heading').textContent=reportNames[kind];$('ew-report-body').replaceChildren(node('p','正在读取对应任务证据…'));
    $('ew-report').showModal();$('ew-report-close').focus();
    const timeout=setTimeout(()=>controller.abort('timeout'),20000);
    try{const data=await fetchJSON('/api/english-world/console/report?'+new URLSearchParams({task,kind}),controller.signal);if(controller!==reportRequest||!$('ew-report').open)return;
      $('ew-report-body').replaceChildren(node('h3',data.task.title),node('p','任务创建：'+time(data.task.created_at),'hint'),node('p',data.status,'ew-report-state'),...data.lines.map(line=>node('p',line)));
    }catch(error){if(controller===reportRequest&&$('ew-report').open)$('ew-report-body').replaceChildren(node('p',controller.signal.reason==='timeout'?'证据读取超时，请关闭后重试':error.message,'ew-report-state'));}finally{clearTimeout(timeout);}
  }
  $('ew-report-close').onclick=()=>$('ew-report').close();
  $('ew-report').addEventListener('close',()=>{reportRequest?.abort();reportRequest=null;if(opener?.isConnected)opener.focus();});
  function changed(){clearTimeout(timer);page=1;selected='';load();}
  $('ew-search').addEventListener('compositionstart',()=>{composing=true;clearTimeout(timer);});
  $('ew-search').addEventListener('compositionend',()=>{composing=false;timer=setTimeout(changed,300);});
  $('ew-search').addEventListener('input',()=>{filters();if(!composing){clearTimeout(timer);timer=setTimeout(changed,300);}});
  $('ew-search').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.isComposing&&!composing){event.preventDefault();changed();}});
  $('ew-clear-search').onclick=()=>{$('ew-search').value='';changed();$('ew-search').focus();};
  $('ew-trigger').onchange=changed;$('ew-date').onchange=changed;
  $('ew-reset').onclick=()=>{$('ew-search').value='';$('ew-trigger').value='';$('ew-date').value='';category='all';changed();};
  document.querySelectorAll('[data-category]').forEach(b=>b.onclick=()=>{category=b.dataset.category;changed();});
  $('ew-more').onclick=()=>{const expanded=$('ew-more').getAttribute('aria-expanded')!=='true';$('ew-more').setAttribute('aria-expanded',String(expanded));$('ew-extra').classList.toggle('expanded',expanded);};
  $('ew-prev').onclick=()=>{page--;load();};$('ew-next').onclick=()=>{page++;load();};$('ew-refresh').onclick=load;
  window.addEventListener('popstate',()=>location.reload());
  document.querySelectorAll('button[disabled]:not(#ew-prev):not(#ew-next)').forEach(b=>b.disabled=false);
  filters();load();
})();
