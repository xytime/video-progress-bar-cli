/* Modification History: 1.0.0 | 2026-10-11 | Codex | 本机候选交互、CAS、错误恢复、筛选与分页；无自动搜索。 */
/* Modification History: 1.0.1 | 2026-10-12 | Codex | 显示持久化维护状态，保留本地专题管理。 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const csrf = document.querySelector('meta[name="topic-csrf"]').content;
  const api = '/api/topic-candidates';
  // 绑定事件前保持按钮禁用，避免首屏出现尚未就绪的操作。
  let model = null, editing = null, initialDraft = '', pending = false, action = null;
  let pageNumber = 1, listGeneration = 0, listController = null, pollTimer = null, queryTimer = null;
  const statusNames = {ACTIVE:'有效', PAUSED:'已暂停', EXPIRED:'已到期', ARCHIVED:'已归档', NEW:'未整理', SAVED:'收藏', REJECTED:'排除', CHECKABLE:'可人工核实', INCOMPLETE:'资料不足', RESTRICTED:'规则受限', UNAVAILABLE:'不可用', RUNNING:'搜索中', STOPPING:'正在停止', COMPLETE:'完成', PARTIAL:'部分完成', FAILED:'失败', INTERRUPTED:'已中断'};
  const failures = {NETWORK:'官方请求失败或超时', API_QUOTA:'官方项目配额已耗尽', API_CREDENTIALS:'官方凭据无效', API_ACCESS:'官方访问受限', API_RATE_LIMIT:'官方请求限流', API_ERROR:'官方服务暂不可用', BUDGET:'今日预算不足', MARKET_GUARD:'宿主保护窗口', GUARD_UNKNOWN:'宿主保护状态无法确认', GUARD_DISABLED:'宿主保护未开启', DEADLINE:'时间不足，搜索已停止', DATABASE_BUSY:'数据库忙，请稍后重试', DATABASE_ERROR:'数据库操作未完成', STOPPED:'专题或运行状态已改变', SEARCH_CLOSED:'搜索已关闭', RESTARTED:'服务重启，本轮未自动续跑', INTERNAL_ERROR:'本轮未完成，请重新载入查看状态', INVALID_RESPONSE:'官方资料不足'};
  const text = (tag, value, className) => { const el=document.createElement(tag); el.textContent=value; if(className) el.className=className; return el; };
  const when = value => { const date=new Date(value); return value && !Number.isNaN(date.valueOf()) ? date.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}) : '未知'; };
  const say = (value, id='feedback') => { $(id).textContent=value; };
  function button(label, fn, disabled=false) { const el=text('button',label); el.type='button'; el.disabled=disabled; el.addEventListener('click',fn); return el; }
  function focusedRow() {
    const el=document.activeElement, row=el.closest?.('[data-topic], [data-key]');
    return row ? {topic:row.dataset.topic,key:row.dataset.key,label:el.textContent} : null;
  }
  function restoreRowFocus(saved) {
    if(!saved || document.activeElement!==document.body) return;
    const row=document.querySelector(saved.topic?`[data-topic="${saved.topic}"]`:`[data-key="${saved.key}"]`);
    const choices=[...(row?.querySelectorAll('button:not(:disabled), a') || [])];
    (choices.find(el=>el.textContent===saved.label) || choices[0])?.focus({preventScroll:true});
  }
  async function request(path, body, method='GET', signal) {
    let response;
    try { response=await fetch(api+path,{method, credentials:'same-origin', signal,
      headers: body ? {'Content-Type':'application/json','X-Topic-CSRF':csrf} : {}, body: body ? JSON.stringify(body) : undefined}); }
    catch(error) { if(error.name==='AbortError') throw error; throw new Error('服务暂不可用，请保留当前修改并重试。'); }
    const result=await response.json();
    if(!response.ok) {
      const detail=result.detail || '';
      const error=new Error(response.status===403 ? (detail.message || detail || '本机会话已过期，请重新打开页面。') : response.status===409 ? (detail.message || '资料已更新，请重新载入后再操作。') : typeof detail==='object' && !Array.isArray(detail) ? detail.message : Array.isArray(detail) ? '输入不符合要求，请检查对应字段。' : detail || '操作未完成，请重试。');
      error.code=detail?.code; error.fields=Array.isArray(detail) ? detail : []; throw error;
    }
    return result;
  }
  async function mutation(fn, success, feedback='feedback') {
    if(pending) return false;
    pending=true; clearTimeout(pollTimer); document.querySelectorAll('.topic-workbench button').forEach(el=>{el.dataset.beforeDisabled=String(el.disabled);el.disabled=true;});
    say('正在保存…',feedback);
    try { await fn(); say(success,feedback); return true; }
    catch(error) { say(error.message,feedback); if(feedback==='form-feedback') fieldError(error); return false; }
    finally { pending=false; document.querySelectorAll('[data-before-disabled]').forEach(el=>{el.disabled=el.dataset.beforeDisabled==='true';delete el.dataset.beforeDisabled;}); if(model?.jobs.some(job=>['RUNNING','STOPPING'].includes(job.state))) pollTimer=setTimeout(load,1500); }
  }
  async function load() {
    if(pending) return;
    clearTimeout(pollTimer);
    const focused=focusedRow();
    try { const result=await request('/state'); if(pending) return; model=result; renderState(); await loadCandidates(); restoreRowFocus(focused); }
    catch(error) { say(error.message); $('topics').setAttribute('aria-busy','false'); $('candidates').setAttribute('aria-busy','false'); }
    if(model?.jobs.some(job=>['RUNNING','STOPPING'].includes(job.state))) pollTimer=setTimeout(load,1500);
  }
  function renderState() {
    $('new-topic').disabled=false;
    $('mode-state').textContent=model.control.mode==='OFF' ? (model.search_open ? '已关闭；仅手动搜索' : '生产搜索尚未开放；可管理专题和整理已有候选') : '仅发现；点击专题按钮才会搜索';
    if (model.maintenance?.state !== 'RUNNING') {
      $('mode-state').textContent=(model.maintenance?.state === 'MAINTENANCE' ? '维护中；' : '维护状态无法确认；') + $('mode-state').textContent;
    }
    $('budget').textContent=`太平洋日期 ${model.budget.day} · 搜索 ${model.budget.search} / ${model.limits.search} 次 · 详情 ${model.budget.general} / ${model.limits.general} units`;
    $('mode-button').textContent=model.control.mode==='OFF' ? '开启手动搜索' : '关闭搜索';
    $('mode-button').disabled=model.control.mode==='OFF' && !model.search_open;
    const options=$('topic-filter'), selected=options.value;
    options.replaceChildren(new Option('全部专题',''));
    model.topics.forEach(topic=>options.add(new Option(topic.name,topic.id)));
    options.value=selected;
    const list=$('topics'); list.replaceChildren(); list.setAttribute('aria-busy','false');
    if(!model.topics.length) list.append(text('p','还没有专题。点击“新建专题”保存关注的关键词。','hint'));
    model.topics.forEach(topic=>{
      const row=text('article','', 'topic-row'); row.dataset.topic=topic.id;
      const main=text('div',''); main.append(text('h3',topic.name),text('p',topic.query),text('p',`${statusNames[topic.status]} · ${topic.category} · 到期 ${when(topic.expires_at)} · ${topic.candidate_count} 个历史候选`,'hint'),text('p',`最近搜索：${when(topic.last_run_at)}`,'hint'));
      const actions=text('div','', 'topic-actions');
      const busy=model.jobs.some(j=>j.topic_id===topic.id && ['RUNNING','STOPPING'].includes(j.state));
      actions.append(button(busy?'搜索中':'搜索候选',async()=>{
        const idem=crypto.randomUUID().replaceAll('-','');
        if(await mutation(()=>request(`/topics/${topic.id}/search`,{version:topic.version,idempotency:idem},'POST'),'搜索已开始；请查看最近搜索。')) await load();
      }, topic.status!=='ACTIVE'||model.control.mode==='OFF'||!model.search_open||busy));
      actions.append(button('编辑',()=>openEditor(topic),topic.status==='ARCHIVED'||busy));
      if(topic.status!=='ARCHIVED') {
        actions.append(button(topic.status==='ACTIVE'?'暂停':'恢复',async()=>{
          if(topic.status==='EXPIRED') { openAction('恢复专题',`为“${topic.name}”设置新的有效期。`,false,true,()=>request(`/topics/${topic.id}/state`,{version:topic.version,state:'ACTIVE',valid_days:Number($('renew-days').value)},'POST')); return; }
          if(await mutation(()=>request(`/topics/${topic.id}/state`,{version:topic.version,state:topic.status==='ACTIVE'?'PAUSED':'ACTIVE'},'POST'),'专题状态已保存。')) await load();
        }));
        actions.append(button('归档',()=>openAction('归档专题',`归档“${topic.name}”后停止搜索并保留历史记录，首期不提供恢复。`,false,false,()=>request(`/topics/${topic.id}/state`,{version:topic.version,state:'ARCHIVED'},'POST'))));
      }
      row.append(main,actions); list.append(row);
    });
    const jobs=$('jobs'); jobs.replaceChildren();
    if(!model.jobs.length) jobs.append(text('p','尚无搜索记录。','hint'));
    model.jobs.slice(0,10).forEach(job=>{ const name=model.topics.find(t=>t.id===job.topic_id)?.name || '历史专题'; const c=job.counts || {}; jobs.append(text('p',`${name} · ${statusNames[job.state]} · ${when(job.started_at)} · 新增 ${c.new || 0} / 重复 ${c.duplicate || 0} / 受限 ${c.restricted || 0} · 预留消耗：搜索 ${job.search_requests || 0} 次 / 详情 ${job.general_units || 0} units${job.state==='COMPLETE'&&!(c.new+c.duplicate)?' · 本轮无结果':''}${job.code&&job.code!=='OK'?' · '+(failures[job.code]||'本轮未完成'):''}`)); });
  }
  function filterParams() { return new URLSearchParams({topic_id:$('topic-filter').value,state:$('state-filter').value,eligibility:$('eligibility-filter').value,q:$('candidate-query').value,page:String(pageNumber)}); }
  async function loadCandidates() {
    const focused=focusedRow();
    const generation=++listGeneration;
    listController?.abort(); listController=new AbortController(); $('candidates').setAttribute('aria-busy','true');
    const params=filterParams(); history.replaceState(null,'',location.pathname+'?'+params);
    try {
      const result=await request('/videos?'+params,undefined,'GET',listController.signal);
      if(generation!==listGeneration) return;
      const list=$('candidates');list.replaceChildren();
      if(!result.candidates.length) list.append(text('p',result.total ? '本页没有候选，请返回上一页。' : '暂无符合条件的候选。可调整筛选；真实搜索开放后，再手动搜索专题。','hint'));
      result.candidates.forEach(candidate=>{
        const meta=candidate.metadata, card=text('article','', 'candidate-card'); card.dataset.key=candidate.key;
        card.append(text('h3',meta.title), text('p',`YouTube · ${meta.channel_name || '频道未知'} · ${when(meta.published_at)} · ${meta.duration===null?'时长未知':meta.duration+' 秒'}`,'hint'));
        card.append(text('p',`播放 ${meta.views??'未知'} · 点赞 ${meta.likes??'未知'} · 语言未核实`,'hint'),text('p',`命中：${candidate.topics.map(t=>t.name).join('、')} · ${statusNames[candidate.state]} · ${statusNames[candidate.eligibility]}`));
        const source=text('details',''); source.append(text('summary','来源与原始描述'),text('p',`视频 ID：${meta.youtube_id} · 频道 ID：${meta.channel_id || '未知'}`,'hint'),text('p',meta.description || '原始描述未知')); card.append(source);
        card.append(text('p',candidate.reason),text('p',`资料更新 ${when(candidate.fetched_at)}${candidate.needs_review?' · 资料已变化，需重新核实':''}`,'hint'));
        if(candidate.pipeline_present) card.append(text('p',`已在主流水线：${candidate.pipeline_states.map(s=>s.status).join('、')}`));
        const actions=text('div','', 'candidate-actions'), link=`https://www.youtube.com/watch?v=${meta.youtube_id}`;
        const open=text('a','打开原视频'); open.href=link; open.target='_blank'; open.rel='noopener noreferrer'; actions.append(open);
        actions.append(button('复制原链接',async()=>{try {await navigator.clipboard.writeText(link);say('原视频链接已复制。');}catch(_){let input=card.querySelector('.copy-link');if(!input){input=text('input','', 'copy-link');input.readOnly=true;input.setAttribute('aria-label','原视频链接');card.append(input);}input.value=link;input.focus();input.select();say('浏览器未允许复制，已选中原链接，可手动复制。');}}));
        const decide=(state,reason)=>request(`/videos/${candidate.key}/decision`,{revision:candidate.revision,decision_revision:candidate.decision_revision,content_version:candidate.content_version,state,reason},'POST');
        const save=async state=>{if(await mutation(()=>decide(state,null),state==='NEW'?'已取消收藏。':'已收藏，仅保存选题意向。')) await loadCandidates();};
        if(candidate.state==='SAVED') {
          actions.append(button('取消收藏',()=>save('NEW')));
          if(candidate.needs_review) actions.append(button('核实后重新收藏',()=>save('SAVED'),!candidate.can_save));
        } else actions.append(button('收藏',()=>save('SAVED'),!candidate.can_save));
        actions.append(button('排除',()=>openAction('排除候选',`排除“${meta.title}”后，跨专题重复发现仍保留排除决定，首期不提供恢复。`,true,false,()=>decide('REJECTED',$('reject-reason').value)),candidate.state==='REJECTED'));
        card.append(actions);list.append(card);
      });
      $('candidate-range').textContent=`共 ${result.total} 个候选 · 第 ${result.page} 页`;
      $('previous').disabled=result.page<=1; $('next').disabled=result.page*25>=result.total;
      restoreRowFocus(focused);
    } catch(error) { if(error.name!=='AbortError'&&generation===listGeneration) say(error.message); }
    finally { if(generation===listGeneration) $('candidates').setAttribute('aria-busy','false'); }
  }
  function draft() { return {name:$('topic-name').value,query:$('topic-query').value,category:$('topic-category').value,lookback_days:Number($('topic-lookback').value),valid_days:Number($('topic-days').value)}; }
  function openEditor(topic=null) { editing=topic; $('editor-title').textContent=topic?'编辑专题':'新建专题'; ['name','query','category'].forEach(key=>$('topic-'+key).value=topic?.[key] || (key==='category'?'宏观经济':'')); $('topic-lookback').value=topic?.lookback_days || 7; $('topic-days').value=topic?.valid_days || 7; clearErrors();say('','form-feedback');initialDraft=JSON.stringify(draft());$('topic-editor').showModal();$('topic-name').focus(); }
  function clearErrors() { ['name','query','days'].forEach(key=>{$(key+'-error').textContent='';$('topic-'+key).removeAttribute('aria-invalid');}); }
  function invalid(key,message) { $(key+'-error').textContent=message;$('topic-'+key).setAttribute('aria-invalid','true'); }
  function fieldError(error) { const key={INVALID_NAME:'name',INVALID_QUERY:'query',INVALID_EXPIRY:'days'}[error.code]; if(key) invalid(key,error.message); for(const field of error.fields||[]){const mapped={name:'name',query:'query',valid_days:'days'}[field.loc?.at(-1)];if(mapped)invalid(mapped,'请检查此字段');} document.querySelector('#topic-form [aria-invalid="true"]')?.focus(); }
  function closeEditor(event) { if(pending){event?.preventDefault();return;} if(JSON.stringify(draft())!==initialDraft){event?.preventDefault();$('discard-dialog').showModal();return;} $('topic-editor').close(); }
  function openAction(title,description,reason,renew,fn) { action=fn;$('action-title').textContent=title;$('action-description').textContent=description;$('reason-field').hidden=!reason;$('renew-field').hidden=!renew;say('','action-feedback');$('action-dialog').showModal(); }
  $('topic-form').addEventListener('submit',async event=>{event.preventDefault();clearErrors();const value=draft();if(!value.name.trim())invalid('name','请填写专题名称');if(!value.query.trim())invalid('query','请填写查询词');if(!Number.isInteger(value.valid_days)||value.valid_days<1||value.valid_days>30)invalid('days','有效期应为 1–30 天');const first=document.querySelector('#topic-form [aria-invalid="true"]');if(first){first.focus();return;}const okay=await mutation(()=>request(editing?'/topics/'+editing.id:'/topics',editing?{...value,version:editing.version}:value,editing?'PUT':'POST'),'专题已保存，不会自动搜索。','form-feedback');if(okay){$('topic-editor').close();say('专题已保存，不会自动搜索。');await load();}});
  $('action-form').addEventListener('submit',async event=>{event.preventDefault();if(!$('renew-field').hidden&&(!Number.isInteger(Number($('renew-days').value))||Number($('renew-days').value)<1||Number($('renew-days').value)>30)){say('新有效期应为 1–30 天','action-feedback');$('renew-days').focus();return;}if(await mutation(action,'操作已保存。','action-feedback')){$('action-dialog').close();say('操作已保存。');await load();}});
  $('new-topic').addEventListener('click',()=>openEditor());$('reload').addEventListener('click',load);
  ['editor-cancel','editor-close'].forEach(id=>$(id).addEventListener('click',closeEditor));$('topic-editor').addEventListener('cancel',closeEditor);
  $('action-dialog').addEventListener('cancel',event=>{if(pending)event.preventDefault();});$('action-cancel').addEventListener('click',()=>$('action-dialog').close());
  $('keep-editing').addEventListener('click',()=>$('discard-dialog').close());$('discard-edit').addEventListener('click',()=>{$('discard-dialog').close();$('topic-editor').close();});
  $('mode-button').addEventListener('click',async()=>{if(await mutation(()=>request('/mode',{version:model.control.version,mode:model.control.mode==='OFF'?'DISCOVERY_ONLY':'OFF'},'PUT'),'运行模式已保存。'))await load();});
  $('filters').addEventListener('submit',event=>event.preventDefault());
  ['topic-filter','state-filter','eligibility-filter'].forEach(id=>$(id).addEventListener('change',()=>{pageNumber=1;loadCandidates();}));
  $('candidate-query').addEventListener('input',event=>{clearTimeout(queryTimer);if(!event.isComposing)queryTimer=setTimeout(()=>{pageNumber=1;loadCandidates();},300);});
  $('candidate-query').addEventListener('compositionend',()=>{clearTimeout(queryTimer);queryTimer=setTimeout(()=>{pageNumber=1;loadCandidates();},300);});
  $('clear-query').addEventListener('click',()=>{$('candidate-query').value='';pageNumber=1;loadCandidates();$('candidate-query').focus();});
  $('previous').addEventListener('click',()=>{pageNumber=Math.max(1,pageNumber-1);loadCandidates();});$('next').addEventListener('click',()=>{pageNumber++;loadCandidates();});
  $('audit-open').addEventListener('click',async()=>{try{const rows=await request('/audit');$('audit-records').replaceChildren(...rows.map(r=>text('p',`${when(r.at)} · ${r.action} · 本机会话 ${r.actor}${r.reason?' · '+r.reason:''}`)));}catch(error){say(error.message);}});
  ['reload','clear-query','editor-close','editor-cancel','action-cancel','keep-editing','discard-edit'].forEach(id=>$(id).disabled=false);
  const initial=new URLSearchParams(location.search); ['state','eligibility'].forEach(key=>$(key+'-filter').value=initial.get(key)||'');$('candidate-query').value=initial.get('q')||'';pageNumber=Math.max(1,Number(initial.get('page'))||1);
  load().then(()=>{if(initial.get('topic_id')&&model?.topics.some(t=>t.id===initial.get('topic_id'))){$('topic-filter').value=initial.get('topic_id');loadCandidates();}});
})();
