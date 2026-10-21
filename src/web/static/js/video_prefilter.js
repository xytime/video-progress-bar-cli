/* Modification History: 1.1.0 | 2026-10-21 | Codex | 结果优先摘要、按需编辑与可比较指标；保留草稿和门禁。 */
(() => {
  'use strict';
  const $=id=>document.getElementById('prefilter-'+id), api='/api/video-prefilter';
  const csrf=document.querySelector('meta[name="topic-csrf"]').content;
  const names={QUALIFIED:'指标合格',REJECTED:'未达标',INCOMPLETE:'资料不足',FAILED:'请求失败',COMPLETE:'完成',PARTIAL:'部分完成',INTERRUPTED:'已中断',RUNNING:'执行中'};
  const controls=['name','keywords','lookback_hours','max_duration','min_views','min_like_ratio','candidate_count'];
  const params=new URLSearchParams(location.search);
  let model=null, selected=null, baseline=JSON.stringify(controls.map(key=>$(key).value)), healthy=false, pending=false, jobId=params.get('job')||'', category=params.has('category')?params.get('category'):'QUALIFIED', page=Math.max(1,Math.min(10000,Number(params.get('page'))||1)), listGeneration=0, timer=null, idem=null;
  const node=(tag,value,cls)=>{const el=document.createElement(tag);el.textContent=value??'';if(cls)el.className=cls;return el;};
  const say=(id,value)=>{$(id).textContent=value;};
  const when=value=>value?new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'未知';
  const button=(label,fn,disabled=false)=>{const el=node('button',label);el.type='button';el.disabled=disabled;el.addEventListener('click',fn);return el;};
  const raw=()=>JSON.stringify(controls.map(key=>$(key).value));
  const dirty=()=>raw()!==baseline;
  function url(){const q=new URLSearchParams();if(jobId)q.set('job',jobId);if(selected)q.set('rule',selected.id);q.set('category',category);q.set('page',page);history.replaceState(null,'',location.pathname+(q.size?'?'+q:''));}
  async function request(path,body,method='GET'){
    const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),12000);
    try{
      const response=await fetch(api+path,{method,signal:controller.signal,credentials:'same-origin',headers:body?{'Content-Type':'application/json','X-Topic-CSRF':csrf}:{},body:body?JSON.stringify(body):undefined});
      const data=await response.json();
      if(!response.ok){const detail=data.detail;const error=new Error(Array.isArray(detail)?'输入不符合要求，请检查字段。':detail?.message||detail||'读取失败，请重试。');error.fields=Array.isArray(detail)?detail:[];throw error;}
      return data;
    }catch(error){if(error.name==='AbortError')throw new Error('请求超时。写入状态可能尚未确认，请先重新载入。');throw error;}
    finally{clearTimeout(timeout);}
  }
  function sync(){
    $('fields').disabled=!healthy||pending;
    $('rule').disabled=!healthy||pending;
    $('copy').disabled=!healthy||pending;
    $('save').disabled=!healthy||pending||Boolean(selected&&!dirty());
    $('search').disabled=!healthy||pending||!selected||dirty()||!model?.can_search||model.jobs.some(j=>j.state==='RUNNING');
    $('editor').classList.toggle('has-draft',dirty());
    $('dirty').dataset.dirty=String(dirty());
    say('dirty',dirty()?'有未保存的修改，请先保存配置':selected?'配置已保存 · 版本 '+selected.version:'新规则，请先保存配置');
  }
  function fill(rule){
    const value=rule||model.defaults;selected=rule||null;
    for(const key of controls)$(key).value=key==='keywords'?value[key].join('\n'):key==='min_like_ratio'?Number((value[key]*100).toFixed(8)):value[key];
    baseline=raw();idem=null;sync();url();
    $('config-title').textContent=value.name;
    say('keyword-summary',value.keywords.join('  /  '));
    say('rule-summary',`近 ${value.lookback_hours} 小时 · 时长 ≤ ${value.max_duration/60} 分钟 · 播放 ≥ ${value.min_views.toLocaleString()} · 点赞率 ≥ ${(value.min_like_ratio*100).toFixed(2)}% · 最多 ${value.candidate_count} 条`);
    $('editor').open=!selected;
    for(const key of controls){$(key).removeAttribute('aria-invalid');say(key+'-error','');}
  }
  async function discard(){
    if(!dirty())return true;
    const dialog=$('discard'), focus=document.activeElement;$('keep').disabled=false;$('discard-confirm').disabled=false;dialog.showModal();$('keep').focus();
    return new Promise(resolve=>{
      const done=answer=>{if(answer)baseline=raw();dialog.close();dialog.removeEventListener('cancel',cancel);$('keep').onclick=null;$('discard-confirm').onclick=null;focus?.focus();resolve(answer);};
      const cancel=event=>{event.preventDefault();done(false);};dialog.addEventListener('cancel',cancel);
      $('keep').onclick=()=>done(false);$('discard-confirm').onclick=()=>done(true);
    });
  }
  window.consoleNavigationGuard=async proceed=>{if(await discard())proceed();};
  document.querySelectorAll('.prefilter-tabs a,.breadcrumbs a').forEach(link=>link.addEventListener('click',async event=>{if(!dirty())return;event.preventDefault();if(await discard())location.href=link.href;}));
  window.addEventListener('beforeunload',event=>{if(dirty()){event.preventDefault();event.returnValue='';}});
  function renderState(){
    const chosen=selected?.id||'';$('rule').replaceChildren(node('option','新规则'));$('rule').firstChild.value='';
    for(const rule of model.rules){const opt=node('option',rule.name);opt.value=rule.id;$('rule').append(opt);}$('rule').value=chosen;
    say('gate',model.gate.message);$('gate').dataset.closed=String(!model.can_search);
    say('budget',`共享今日预算 · 搜索 ${model.budget.search} / ${model.limits.search} 次 · 详情 ${model.budget.general} / ${model.limits.general} 次`+(model.trial?' · 试运行累计额度跨日和重启不重置':''));
    $('history').replaceChildren();
    for(const job of model.jobs){const row=node('div','', 'prefilter-history-row');row.append(node('span',`${job.snapshot.name} · v${job.rule_version} · ${when(job.started_at)} · ${names[job.state]||job.state}`),button('查看本轮',()=>{jobId=job.id;category='QUALIFIED';page=1;url();loadResults();$('results-title').scrollIntoView({block:'start'});}));$('history').append(row);}
    if(!model.jobs.length)say('history','尚无检索记录。');sync();
  }
  async function loadState(initial=false){
    try{const result=await request('/state');model=result;healthy=true;
      if(initial){fill(model.rules.find(r=>r.id===params.get('rule'))||model.rules[0]||null);if(!jobId)jobId=model.jobs.find(j=>j.rule_id===selected?.id)?.id||'';url();}
      renderState();say('state-feedback','配置与能力已读取 · '+when(new Date().toISOString())+'（北京时间）');
    }catch(error){healthy=false;say('state-feedback','读取失败，当前状态未核实。'+error.message);sync();}
  }
  async function poll(){clearTimeout(timer);await loadState();if(jobId)await loadResults();if(model?.jobs.some(j=>j.state==='RUNNING'))timer=setTimeout(poll,2000);}
  function value(){
    const result={};let first=null;
    for(const key of controls){let message='';const el=$(key);el.removeAttribute('aria-invalid');
      if(key==='name'){result[key]=el.value.trim();if(!result[key])message='请输入规则名称。';}
      else if(key==='keywords'){result[key]=el.value.split('\n').map(v=>v.trim()).filter(Boolean);if(!result[key].length||result[key].length>10||result[key].some(v=>v.length>80||/["|\x00-\x1f]/.test(v)))message='请输入 1–10 个短语，每行一个、最多 80 字，不含引号或竖线。';}
      else{result[key]=Number(el.value);if(el.value===''||!el.checkValidity()||!Number.isFinite(result[key]))message='请输入允许范围内的数值。';if(key==='min_like_ratio')result[key]/=100;}
      say(key+'-error',message);if(message){el.setAttribute('aria-invalid','true');first??=el;}
    }if(first){$('editor').open=true;first.focus();return null;}return result;
  }
  async function mutate(fn,message){
    if(pending||!healthy)return;pending=true;clearTimeout(timer);sync();
    try{await fn();say('form-feedback',message);}
    catch(error){say('form-feedback',error.message);for(const field of error.fields||[]){const key=field.loc?.[1];if(controls.includes(key)){$(key).setAttribute('aria-invalid','true');say(key+'-error',field.msg);$('editor').open=true;$(key).focus();}}}
    finally{pending=false;await loadState();if(jobId)await loadResults();sync();if(model?.jobs.some(j=>j.state==='RUNNING'))timer=setTimeout(poll,2000);}
  }
  $('form').addEventListener('submit',event=>{event.preventDefault();const body=value();if(!body)return;
    mutate(async()=>{const row=await request(selected?'/rules/'+selected.id:'/rules',selected?{...body,version:selected.version}:body,selected?'PUT':'POST');fill(row);},'配置已保存。未发起检索。');});
  $('search').addEventListener('click',()=>{if($('search').disabled)return;idem??=crypto.randomUUID();mutate(async()=>{const job=await request('/rules/'+selected.id+'/search',{version:selected.version,idempotency:idem},'POST');jobId=job.id;category='QUALIFIED';page=1;idem=null;url();},'已提交手动检索；收藏不会触发生产。');});
  $('rule').addEventListener('change',async()=>{const id=$('rule').value;if(await discard()){fill(model.rules.find(r=>r.id===id)||null);jobId=model.jobs.find(j=>j.rule_id===selected?.id)?.id||'';page=1;category='QUALIFIED';url();await loadResults();}else $('rule').value=selected?.id||'';});
  $('copy').addEventListener('click',()=>{selected=null;$('rule').value='';baseline='';idem=null;sync();url();$('editor').open=true;$('name').focus();});
  for(const key of controls)$(key).addEventListener('input',sync);
  $('reload').addEventListener('click',async()=>{if(await discard()){await loadState();if(healthy){fill(model.rules.find(r=>r.id===selected?.id)||model.rules[0]||null);await poll();}}});
  $('result-retry').addEventListener('click',()=>loadResults());
  $('previous').addEventListener('click',()=>{page--;url();loadResults();});$('next').addEventListener('click',()=>{page++;url();loadResults();});
  async function decide(row,decision,resultJob){await mutate(()=>request(`/jobs/${resultJob}/videos/${row.key}/decision`,{revision:row.revision,content_version:row.observation.content_version,decision},'POST'),'整理决定已保存；不会触发生产。');}
  function renderResults(data){
    const job=data.job, counts=job.counts, rule=job.snapshot;
    say('job-status',`${names[job.state]||job.state} · ${job.phase==='SEARCH'?'正在检索候选':job.phase==='DETAILS'?'正在读取详情':'本轮已结束'} · 返回 ${counts.returned||0} 个 · 详情 ${counts.detailed||0} 个${counts.unprocessed?' · 尚未分类 '+counts.unprocessed+' 个':''}${job.code&&job.code!=='OK'?' · '+job.code:''}`);
    say('snapshot',`${rule.name} · 规则版本 ${job.rule_version} · ${when(job.started_at)}（北京时间）起回溯 ${rule.lookback_hours} 小时 · ≤ ${rule.max_duration} 秒 · 播放 ≥ ${rule.min_views.toLocaleString()} · 点赞率 ≥ ${(rule.min_like_ratio*100).toFixed(2)}%${job.has_more?' · 还有更多候选，本轮未继续翻页':''}`);
    $('categories').replaceChildren();for(const key of ['',...Object.keys(names).slice(0,4)]){const el=button(`${key?names[key]:'全部'} ${key?counts[key]||0:counts.returned||0}`,()=>{category=key;page=1;url();loadResults();});el.setAttribute('aria-pressed',String(category===key));el.dataset.category=key||'ALL';$('categories').append(el);}
    $('results').replaceChildren();
    if(!data.results.length){say('results',job.state==='RUNNING'?'候选尚未写入，请等待本轮结束。':data.total===0&&['FAILED','INTERRUPTED'].includes(job.state)?'本轮请求未完成，请查看失败状态；不是零条合格结果。':'此分类暂无可用记录。超过 30 天的源资料已清除。');}
    else{
      const table=node('table','', 'prefilter-table'), head=node('thead',''), tr=node('tr','');
      const labels=['视频 / 来源','播放量','点赞率','时长','人工整理'];
      table.append(node('caption','预筛选候选，按播放量降序','sr-only'));
      for(const label of labels){const th=node('th',label);th.scope='col';tr.append(th);}head.append(tr);table.append(head);const body=node('tbody','');
      for(const row of data.results){const r=row.observation,m=r.metadata, line=node('tr','');line.dataset.key=row.key;line.dataset.category=r.category;
        const cells=labels.map(label=>{const cell=node('td','');cell.dataset.label=label;line.append(cell);return cell;});
        const link=node('a',m.title||'来源资料不足','prefilter-video-title');link.href='https://www.youtube.com/watch?v='+encodeURIComponent(m.youtube_id);link.target='_blank';link.rel='noopener noreferrer';
        cells[0].append(link,node('p',m.channel_name||m.channel_id||'未知频道','hint'),node('p','发布 '+when(m.published_at)+'（北京时间）','hint'),node('p','获取 '+when(row.fetched_at)+'（北京时间）','hint'));
        const detail=node('details','', 'prefilter-conclusion');detail.append(node('summary',names[r.category]),node('p',r.reasons.join('；'),'hint'));cells[0].append(detail);
        cells[1].append(node('strong',m.views==null?'未知':m.views.toLocaleString(),'prefilter-views'),node('p','点赞 '+(m.likes==null?'未知':m.likes.toLocaleString()),'hint'));
        cells[2].append(node('span',m.likes==null||!m.views?'未知':(m.likes/m.views*100).toFixed(2)+'%','prefilter-metric'));
        cells[3].append(node('span',m.duration==null?'未知':`${Math.floor(m.duration/60)}:${String(m.duration%60).padStart(2,'0')}`,'prefilter-metric'));
        cells[4].append(node('p',{NEW:'未整理',SAVED:'已收藏',REJECTED:'已排除'}[row.decision],'hint'));const actions=node('div','', 'prefilter-row-actions');
        if(row.decision!=='SAVED')actions.append(button('收藏',()=>decide(row,'SAVED',job.id),!healthy||pending||r.category!=='QUALIFIED'));
        if(row.decision!=='REJECTED')actions.append(button('排除',()=>decide(row,'REJECTED',job.id),!healthy||pending));
        if(row.decision!=='NEW')actions.append(button('撤销整理',()=>decide(row,'NEW',job.id),!healthy||pending));cells[4].append(actions);body.append(line);
      }table.append(body);$('results').append(table);
    }
    say('page',`第 ${data.page} 页 · 此分类 ${data.total} 条`);$('previous').disabled=pending||page<=1;$('next').disabled=pending||page*data.page_size>=data.total;
  }
  async function loadResults(){
    if(!jobId){++listGeneration;$('results').replaceChildren();$('categories').replaceChildren();say('job-status','尚未检索。请保存配置后手动开始。');say('snapshot','');say('page','');say('result-feedback','');$('previous').disabled=true;$('next').disabled=true;$('result-retry').disabled=true;return;}const generation=++listGeneration;$('results').setAttribute('aria-busy','true');$('result-retry').disabled=true;
    try{const data=await request(`/results?job_id=${encodeURIComponent(jobId)}&category=${category}&page=${page}`);if(generation!==listGeneration)return;renderResults(data);say('result-feedback','结果来自所示历史快照，仅供人工预筛选。');}
    catch(error){if(generation!==listGeneration)return;$('results').replaceChildren();say('result-feedback','结果读取失败。'+error.message);$('previous').disabled=true;$('next').disabled=true;}
    finally{if(generation===listGeneration){$('results').setAttribute('aria-busy','false');$('result-retry').disabled=false;}}
  }
  $('reload').disabled=false;
  (async()=>{await loadState(true);await poll();})();
})();
