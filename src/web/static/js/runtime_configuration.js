/* optional-publish-v1 | 2026-10-25 | Codex | 显式显示无每日上限；清空数值以原CAS流程取消日额。 */
/* runtime-center-v1 | 2026-10-24 | Codex | 草稿/预览/CAS/回滚与加载状态；无平台操作。 */
(() => {
  'use strict';
  const $=id=>document.getElementById(id), base='/api/runtime-configuration';
  const csrf=document.querySelector('meta[name=runtime-csrf]').content;
  const names={publish:'发视频',first_comment:'发首评',reply:'回复评论',comment_scan:'扫描新评论',post_match:'匹配作品编号',keepalive:'按需保活'};
  const labels={rolling_24h_limit:'最近24小时额度',rolling_1h_limit:'最近60分钟额度',min_interval_seconds:'两次流程最小间隔',max_replies_per_video_lifetime:'每视频累计回复',max_videos_per_run:'每轮最多视频',same_batch_success_cooldown_seconds:'同批成功查询冷却',max_retries:'额外重试次数',interval_seconds:'重试最小间隔'};
  let saved=null,draft=null,revision=null,metadata=null,preview=null,busy=false,conflict=false,page=1,view='operations',generation=0,editEpoch=0,afterDiscard=null,operationId=null,composing=false;
  const invalid=new Map();
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const stamp=t=>{if(!t)return '未知';const raw=typeof t==='number'?t*1000:/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(t)?t.replace(' ','T')+'Z':t;const d=new Date(raw);return Number.isNaN(d.getTime())?'未知':d.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});};
  const get=(obj,path)=>path.split('.').reduce((p,k)=>p?.[k],obj);
  const put=(obj,path,value)=>{const keys=path.split('.'),key=keys.pop();get(obj,keys.join('.'))[key]=value;};
  function changed(){return saved&&JSON.stringify(saved)!==JSON.stringify(draft);}
  function updateDirty(){ $('dirty-state').textContent=changed()?'有未保存修改':'与活动版本一致';$('preview').disabled=!changed()||busy||conflict||invalid.size>0; }
  async function api(path,options={}) {
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
    try {
      const response=await fetch(base+path,{...options,cache:'no-store',headers:{'Content-Type':'application/json','X-Runtime-CSRF':csrf},signal:controller.signal});
      const data=await response.json();if(!response.ok){const e=new Error(typeof data.detail==='string'?data.detail:'请求字段不合法，请检查后重试');e.status=response.status;throw e;}return data;
    }catch(e){if(e.name==='AbortError')throw new Error('请求超时，结果尚未确认；草稿保留，请核对版本');throw e;}finally{clearTimeout(timer);}
  }
  function field(path,label,unit,range,defaultValue) {
    const box=node('div',undefined,'runtime-field'),id='field-'+path.replaceAll('.','-');
    const unlimited=path==='wechat_operations.operations.publish.rolling_24h_limit';
    const title=node('label',label);title.htmlFor=id;
    const input=node('input');input.id=id;input.type='number';input.value=get(draft,path)??'';input.step=path.endsWith('google_translate_interval_seconds')?'0.1':'1';
    if(unlimited)input.placeholder='无每日上限';
    if(range){input.min=range[0];input.max=range[1];}
    const hint=node('small',(unit||'数值')+' · 默认 '+String(defaultValue??(unlimited?'无每日上限':'未知'))+(range?' · 允许 '+range.join('–'):'')+(unlimited?' · 留空表示无每日上限':''),'hint');hint.id=id+'-help';
    const error=node('span',invalid.get(path)||'','field-error');error.id=id+'-error';input.setAttribute('aria-describedby',hint.id+' '+error.id);
    input.setAttribute('aria-invalid',invalid.has(path)?'true':'false');
    input.addEventListener('input',()=>{
      const value=input.value===''?null:Number(input.value),bad=value===null?!unlimited:!Number.isFinite(value)||(input.step==='1'&&!Number.isInteger(value))||(range&&(value<range[0]||value>range[1]));
      put(draft,path,value);editEpoch++;if(bad)invalid.set(path,'请输入允许范围内的'+(input.step==='1'?'整数':'数值'));else invalid.delete(path);
      error.textContent=invalid.get(path)||'';input.setAttribute('aria-invalid',bad?'true':'false');preview=null;updateDirty();
    });box.append(title,input,hint,error);return box;
  }
  function renderOperations(){
    $('automatic-replies-enabled').disabled=false;$('automatic-replies-enabled').checked=draft.interaction_controls.automatic_replies_enabled;
    $('reply-control-state').textContent='当前活动值：'+(saved.interaction_controls.automatic_replies_enabled?'开启':'关闭')+' · 来源 interaction_controls · '+revision.slice(0,10);
    $('operation-cards').replaceChildren();
    Object.keys(names).forEach(op=>{const values=draft.wechat_operations.operations[op];
      const card=node('section');card.append(node('h2',names[op]));const gate=node('p','正在读取本地用量…','gate-summary');gate.id='gate-'+op;card.append(gate);const fields=node('div',undefined,'runtime-fields');card.append(fields);
      Object.entries(values).forEach(([key,val])=>{if(typeof val!=='number'&&val!==null)return;const path='operations.'+op+'.'+key,meta=metadata.fields.find(r=>r.domain==='wechat_operations'&&r.key===path);fields.append(field('wechat_operations.'+path,labels[key],meta.unit,meta.range,meta.default));});
      $('operation-cards').append(card);
    });
    $('retry-fields').replaceChildren();Object.entries(draft.wechat_operations.retry_policies.write_actions).forEach(([key,val])=>$('retry-fields').append(field('wechat_operations.retry_policies.write_actions.'+key,labels[key],key==='max_retries'?'首次之外的次数':'秒',key==='max_retries'?[0,2]:[60,604800],val)));
  }
  function catalogRows(){
    const q=$('search').value.trim().toLocaleLowerCase(),group=$('group').value,mode=$('mode').value;
    return metadata.fields.filter(r=>(group==='all'||r.group===group)&&(mode==='all'||r.mode===mode)&&(!q||[r.name,r.id,r.path].join(' ').toLocaleLowerCase().includes(q)));
  }
  function persist(){const url=new URL(location.href);url.searchParams.set('view',view);for(const k of ['search','group','mode']){const v=$(k).value;if(v&&v!=='all')url.searchParams.set(k==='search'?'q':k,v);else url.searchParams.delete(k==='search'?'q':k);}url.searchParams.set('page',page);history.replaceState(null,'',url);}
  function renderCatalog(){
    if(!metadata)return;
    const rows=catalogRows();page=Math.min(Math.max(1,page),Math.max(1,Math.ceil(rows.length/20)));$('catalog-fields').replaceChildren();
    for(const r of rows.slice((page-1)*20,page*20)){
      const row=node('article',undefined,'catalog-row'),info=node('div');info.append(node('strong',r.name),node('p',r.source+' · '+r.boundary),node('code',r.path+(r.line?':'+r.line:'')),node('p',r.reason));
      const value=node('div');
      if(r.mode==='managed'&&!['wechat_operations','interaction_controls'].includes(r.domain))value.append(field(r.domain+'.'+r.key,r.name,r.unit,r.range,r.default));
      else {value.append(node('strong',r.current===null?(r.nullable?'无每日上限':'实际生效值未知'):String(r.current)),node('p','默认/声明值：'+(r.default===null?(r.nullable?'无每日上限':'不展示或未知'):String(r.default))));if(r.mode==='managed'){const b=node('button','在操作额度编辑');b.type='button';b.onclick=()=>selectView('operations');value.append(b);}}
      row.append(info,value);$('catalog-fields').append(row);
    }
    if(!rows.length)$('catalog-fields').append(node('p','没有匹配参数。可清空搜索或更换配置组。'));
    $('catalog-count').textContent='共 '+rows.length+' 项 · 每页20项';$('page-state').textContent=page+' / '+Math.max(1,Math.ceil(rows.length/20));$('previous').disabled=page<=1;$('next').disabled=page>=Math.ceil(rows.length/20);$('clear-search').hidden=!$('search').value;persist();
  }
  function renderFiles(){
    $('config-files').replaceChildren();for(const f of metadata.files){const a=node('article');a.append(node('h3',f.title),node('code',f.path),node('p',f.boundary));if(f.editor&&f.editor!=='/runtime-configuration'){const link=node('a','打开专用配置');link.href=f.editor;a.append(link);}else a.append(node('small',f.mode==='managed'?'在本页编辑':'只读 / 需专门审阅'));$('config-files').append(a);}
  }
  function selectView(next){if(next==='catalog'&&!metadata){$('feedback').textContent='先重新载入有效配置，再查看参数目录';return;}view=['operations','catalog','history'].includes(next)?next:'operations';for(const v of ['operations','catalog','history'])$(v+'-view').hidden=v!==view;document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.view===view?'true':'false'));$('change-reason').hidden=view==='history';persist();if(view==='history')loadHistory();}
  async function load(){const seq=++generation;busy=true;updateDirty();$('feedback').textContent='正在读取活动版本…';
    try{const data=await api('/current');if(seq!==generation)return;saved=data.domains;draft=structuredClone(saved);revision=data.revision;metadata=data.catalog;document.querySelectorAll('[data-view]').forEach(b=>b.disabled=false);invalid.clear();conflict=false;preview=null;
      $('revision').textContent=data.version+' · '+revision.slice(0,10);$('coverage').textContent=metadata.coverage;
      $('group').replaceChildren(new Option('全部配置组','all'),...metadata.groups.map(g=>new Option(g.id+' '+g.name+'（'+g.count+'）',g.id)));
      const u=new URL(location.href);$('search').value=u.searchParams.get('q')||'';$('group').value=u.searchParams.get('group')||'all';$('mode').value=u.searchParams.get('mode')||'all';page=Number(u.searchParams.get('page')||1);
      renderOperations();renderFiles();renderCatalog();selectView(u.searchParams.get('view')||'operations');renderWorkers(data);$('feedback').textContent='已读取活动配置。普通编辑受服务端批准边界限制。';poll();
    }catch(e){$('feedback').textContent='读取失败：'+e.message;conflict=true;}finally{busy=false;updateDirty();}
  }
  function renderWorkers(data){
    const roleNames={'dashboard':'后台服务','ready-worker':'发布执行者','secondary-reply':'回复定时执行者'},rows=(data.workers||[]).map(r=>({...r,label:roleNames[r.role]||r.role}));$('loaded-state').textContent=rows.map(r=>r.label+'：'+r.state).join('；')||'尚无加载确认';
    $('active-attempt').textContent=data.active_attempt?'在途 '+data.active_attempt.purpose+' · 版本 '+(data.active_attempt.active_attempt_revision?.slice(0,10)||'未知，不能确认'):'当前没有浏览器在途操作';
    $('workers').replaceChildren(...rows.map(r=>node('p',r.label+' · '+r.state+' · 版本 '+(r.loaded_revision?.slice(0,10)||'未知')+' · 确认 '+stamp(r.acknowledged_at)+(r.role==='secondary-reply'?' · 本执行者身份'+(r.reply_identity_configured?'已配置':'尚未确认'):''))));
  }
  async function poll(){if(!revision)return;const expected=revision;
    try{const data=await api('/state');if(expected!==revision)return;renderWorkers(data);if(data.revision!==revision){conflict=true;$('feedback').textContent='活动版本已被其他操作更新。当前草稿已保留，请重新载入后编辑。';updateDirty();}
      for(const [op,g] of Object.entries(data.operations||{})){const box=$('gate-'+op);if(!box)continue;box.replaceChildren(node('strong',g.allowed?'账号时间门禁已满足':'正在等待'));box.append(node('span','24h已用 '+g.sessions_24h_count+(g.daily_limit?' / '+g.daily_limit:(op==='publish'?' · 无每日上限':''))+' · 60分钟已用 '+g.sessions_1h_count+(g.hourly_limit?' / '+g.hourly_limit:'')));if(g.blockers.length)box.append(node('div',g.blockers.map(b=>b.reason).join('；')));if(!g.allowed)box.append(node('div',g.until?'最早满足已知时间门禁 '+stamp(g.until)+'，不保证执行':'还有无确定期限的门禁'));}
      $('waits').replaceChildren();for(const w of data.waits||[]){const row=node('article',undefined,'wait-row');row.append(node('strong','首评待办 #'+w.id),node('p',w.blockers.length?w.blockers.map(b=>b.reason).join('；'):'已满足账号时间门禁，仍等待任务资格和串行机会'),node('p','最早时间下界 '+stamp(w.until)+' · 本地调度 '+stamp(w.next_attempt_at)));$('waits').append(row);}if(!data.waits?.length)$('waits').append(node('p','没有可重算的本地首评等待；人工与不确定任务不在此自动队列。'));
      $('additional-gates').replaceChildren(...(data.additional_gates||[]).map(g=>node('p',g.name+'：'+g.value)));$('state-feedback').textContent='本地快照 '+stamp(Date.now()/1000)+'。'+data.meaning;
    }catch(e){$('state-feedback').textContent='门禁状态读取失败：'+e.message+'；不沿用旧的可执行结论。';for(const op of Object.keys(names)){const box=$('gate-'+op);if(box)box.textContent='当前状态未知，请重试';}}
  }
  async function openPreview(rollbackVersion=null){if(busy)return;if(invalid.size){$('feedback').textContent='请先修正字段错误';return;}const reason=$('reason').value.trim();if(reason.length<3){$('reason').setAttribute('aria-invalid','true');$('feedback').textContent='请填写至少3字的变更原因';$('change-reason').hidden=false;$('reason').focus();return;}$('reason').removeAttribute('aria-invalid');busy=true;updateDirty();
    try{const epoch=editEpoch,body={expected_revision:revision,reason,...(rollbackVersion?{rollback_version:rollbackVersion}:{domains:draft})};const report=await api('/preview',{method:'POST',body:JSON.stringify(body)});if(epoch!==editEpoch){$('feedback').textContent='草稿已变化，请重新预览';return;}preview=report;operationId=crypto.randomUUID().replaceAll('-','');$('preview-content').replaceChildren();for(const d of report.changes){const row=node('div',undefined,'diff-row');row.append(node('strong',d.field),node('p',(d.before===null&&d.field.endsWith('publish.rolling_24h_limit')?'无每日上限':String(d.before))+' → '+(d.after===null&&d.field.endsWith('publish.rolling_24h_limit')?'无每日上限':String(d.after))));$('preview-content').append(row);}for(const [op,g] of Object.entries(report.proposed_operations||{})){if(!g.allowed)$('preview-content').append(node('p',names[op]+'：调整后仍等待 '+g.blockers.map(b=>b.reason).join('；')+'；最早下界 '+stamp(g.until)));}$('preview-content').append(node('p',report.risk),node('p','受影响的本地等待 '+report.waiting_tasks+' 条；'+(report.in_flight?'存在在途操作，继续原快照':'没有在途操作')),...report.effects.map(e=>node('p',e)));$('apply-feedback').textContent=report.message||'请核对以上差异；批准范围外的放宽不能在这里确认。';$('apply').disabled=!report.can_apply;$('preview-dialog').showModal();$('cancel-preview').focus();
    }catch(e){$('feedback').textContent='预览失败：'+e.message+'。草稿已保留。';if(e.status===409)conflict=true;}finally{busy=false;updateDirty();}
  }
  async function apply(){if(busy||!preview?.can_apply)return;busy=true;$('apply').disabled=true;$('cancel-preview').disabled=true;$('apply-feedback').textContent='正在提交版本；不会中断在途操作…';
    try{const data=await api('/apply',{method:'POST',body:JSON.stringify({preview_id:preview.preview_id,operation_id:operationId})});if(!data.saved)throw new Error('保存未确认');$('preview-dialog').close();await load();$('feedback').textContent='配置已提交；'+(data.recompute_error?'等待重算待确认，请查看执行者状态':'已完成本地等待重算')+'。执行者采用状态见上方。';}
    catch(e){$('apply-feedback').textContent='保存结果未确认：'+e.message+'。草稿已保留，请核对活动版本后再操作。';if(e.status===409)conflict=true;}
    finally{busy=false;$('cancel-preview').disabled=false;$('apply').disabled=conflict;updateDirty();}
  }
  async function loadHistory(){try{const data=await api('/history');$('history-list').replaceChildren();for(const h of data.versions){const row=node('article',undefined,'history-row'),info=node('div');info.append(node('strong',h.version+' · '+h.revision.slice(0,10)),node('p',stamp(h.created_at)+' 北京时间 · 操作者 '+h.actor),node('p',h.reason+(h.rollback_of?' · 回滚自 '+h.rollback_of:'')));const b=node('button',h.revision===revision?'当前活动版本':'预览回滚');b.type='button';b.disabled=h.revision===revision;b.onclick=()=>openPreview(h.version);row.append(info,b);$('history-list').append(row);}$('history-feedback').textContent='已载入 '+data.versions.length+' 个版本；只回滚配置。';}catch(e){$('history-feedback').textContent='历史读取失败：'+e.message;}}
  function guard(action){if(!changed()){action();return;}afterDiscard=action;$('discard-dialog').showModal();$('keep-editing').focus();}
  window.consoleNavigationGuard=guard;
  $('reload').onclick=()=>guard(load);$('preview').onclick=()=>openPreview();$('apply').onclick=apply;$('cancel-preview').onclick=()=>{if(!busy)$('preview-dialog').close();};$('preview-dialog').addEventListener('cancel',e=>{if(busy)e.preventDefault();});
  $('keep-editing').onclick=()=>$('discard-dialog').close();$('discard').onclick=()=>{const action=afterDiscard;$('discard-dialog').close();if(action)action();};
  $('automatic-replies-enabled').addEventListener('change',()=>{draft.interaction_controls.automatic_replies_enabled=$('automatic-replies-enabled').checked;editEpoch++;preview=null;updateDirty();});
  $('configuration-form').addEventListener('submit',e=>e.preventDefault());window.addEventListener('beforeunload',e=>{if(changed()){e.preventDefault();e.returnValue='';}});
  document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>selectView(b.dataset.view));
  $('search').addEventListener('compositionstart',()=>composing=true);$('search').addEventListener('compositionend',()=>{composing=false;page=1;renderCatalog();});$('search').oninput=()=>{if(!composing){page=1;renderCatalog();}};
  $('clear-search').onclick=()=>{$('search').value='';page=1;renderCatalog();$('search').focus();};for(const k of ['group','mode'])$(k).onchange=()=>{page=1;renderCatalog();};$('previous').onclick=()=>{page--;renderCatalog();};$('next').onclick=()=>{page++;renderCatalog();};
  document.querySelector('main').addEventListener('click',e=>{const a=e.target.closest('a');if(a&&changed()&&!e.ctrlKey&&!e.metaKey&&e.button===0){e.preventDefault();guard(()=>location.assign(a.href));}});
  ['reload','clear-search','cancel-preview','keep-editing','discard'].forEach(id=>$(id).disabled=false);
  load();setInterval(()=>{if(!document.hidden&&!busy)poll();},5000);
})();
