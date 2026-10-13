/** 2026-10-12 Codex：v0.3 总览只读数据、分区与列表 URL 恢复。业务操作仍归旧模块。 */
(() => {
  const $=id=>document.getElementById(id);
  const groups={waitlist:'topics',high_likes:'topics',hotwords:'topics',manual:'topics',queue:'production',active:'production',ready:'production',wechat_deferred:'production',error:'production',review:'publications',completed:'publications'};
  const titles={overview:'工作总览',topics:'选题中心',production:'生产队列',publications:'发布记录',operations:'配置与运维'};
  let view='overview', restoring=false, overviewGeneration=0, lastSuccess='', busy=false, capabilityGeneration=0;
  const label={waitlist:'待筛选',active:'制作中',ready:'待发布',error:'异常记录',wechat_deferred:'待微信恢复',review:'本地受理／待核实'};
  const listURL=tab=>`/?view=${groups[tab]}&tab=${tab}&created_window=all`;
  const overview=document.createElement('section'); overview.id='workspace-overview'; overview.setAttribute('aria-label','工作总览');
  overview.innerHTML=`<div class="console-notice"><p id="console-search-state" role="status">正在核实关键词工作台状态…</p><a data-topic-entry href="/topic-candidates">YouTube 关键词采集 →</a></div>
    <div class="console-metrics">${['waitlist','active','ready','error'].map(tab=>`<a class="console-metric" href="${listURL(tab)}"><span>${label[tab]}</span><strong id="overview-${tab}">—</strong><span>当前列表 · 全部入库时间</span></a>`).join('')}</div>
    <div class="console-overview-grid"><section class="console-panel"><h2>建议先查看</h2><p>按事项类型排序，非严重度评级 · 全部入库时间</p><div class="console-attention" id="attention-main">正在读取关注事项…</div><p>投递结果未核实前，请勿重复提交。</p>
    <div class="console-tasks"><h2>当前任务</h2><div id="overview-tasks" aria-live="polite">正在读取制作与待发布记录…</div></div><details class="console-observation"><summary>观察与历史</summary><p>根据现有错误记录分类；规则已阻止的事项可按需复核。</p><div id="attention-observation"></div><a href="${listURL('error')}">全部异常记录 →</a></details></section>
    <aside class="console-panel console-shortcuts"><h2>常用入口</h2><a href="/?view=operations&tab=channels">频道白名单 <span>→</span></a><a data-topic-entry href="/topic-candidates">YouTube 关键词采集 <span>→</span></a><a href="/?view=production&tab=queue">生产队列 <span>→</span></a><a href="/product-settings">商品挂载 <span>→</span></a><p id="overview-feedback" role="status">正在读取概览…</p><button type="button" id="overview-retry" class="btn-tool-prefs">重新读取</button></aside></div>`;
  const app=document.querySelector('.app'); app.insertBefore(overview,$('global-funnel-panel'));
  const table=document.querySelector('.main-grid > .panel'); table.id='workspace-list';
  const channels=$('channel-list').closest('.panel'); channels.id='workspace-channels';
  const manual=$('video-url-input').closest('.panel'); manual.id='workspace-manual';
  const tools=document.createElement('section'); tools.id='operations-tools'; tools.className='panel'; tools.setAttribute('aria-label','运行与诊断');
  [$('ai-audit-mini'),$('btn-wechat-login'),$('btn-run-pipeline')].forEach(el=>tools.append(el));
  const products=document.createElement('a'); products.href='/product-settings';products.textContent='商品挂载';products.className='btn-tool-prefs';tools.prepend(products);app.append(tools);
  function paint(tab=legacy.tab()) {
    $('workspace-title').textContent=titles[view];document.title=titles[view]+' · 视频运营工作台';
    overview.hidden=view!=='overview';$('global-funnel-panel').hidden=view!=='overview';
    table.hidden=!['topics','production','publications'].includes(view)||tab==='manual';
    channels.hidden=view!=='operations';manual.hidden=!(view==='topics'&&tab==='manual');
    tools.hidden=view!=='operations';$('backfill-panel').hidden=view!=='operations';
    document.querySelectorAll('.tab-btn').forEach(el=>el.hidden=groups[el.id.slice(4)]!==view);
    window.ConsoleNavigation.select(view);
  }
  const legacy=window.DashboardLegacy;
  function persist() {
    if(restoring||!['topics','production','publications'].includes(view))return;
    const params=new URLSearchParams(legacy.query());params.set('view',view);
    const url='/?'+params.toString();if(location.pathname+location.search!==url)history.pushState(null,'',url);
    window.ConsoleNavigation.select(view);
  }
  function selectTab(tab) { view=groups[tab]||'topics';paint(tab); }
  async function readJSON(url) {
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),12000);
    try {const r=await fetch(url,{signal:controller.signal});if(!r.ok)throw new Error(`HTTP ${r.status}`);return await r.json();}
    finally {clearTimeout(timer);}
  }
  async function capability() {
    const generation=++capabilityGeneration;
    try {
      const d=await readJSON('/api/console/capabilities');
      if(generation!==capabilityGeneration)return;
      if(typeof d.topic_available!=='boolean'||typeof d.search_enabled!=='boolean')throw new Error('状态格式不完整');
      $('console-search-state').textContent=!d.topic_available?'关键词工作台仅限本机访问；请在本机打开后台。':d.search_enabled?'搜索配置已开放；是否可搜索以工作台门禁为准。':'生产搜索关闭；进入YouTube 关键词采集查看专题。';
      document.querySelectorAll('a[href="/topic-candidates"]').forEach(a=>{a.removeAttribute('aria-disabled');if(!d.topic_available){a.setAttribute('aria-disabled','true');a.dataset.unavailable='true';}else delete a.dataset.unavailable;});
    } catch(error) {
      if(generation!==capabilityGeneration)return;
      $('console-search-state').textContent=error.message==='HTTP 404'?'关键词工作台尚未采用，入口暂不可用。':'关键词工作台状态未核实，请重新读取；搜索开放状态未知。';
      document.querySelectorAll('a[href="/topic-candidates"]').forEach(a=>{a.setAttribute('aria-disabled','true');a.dataset.unavailable='true';});
    }
  }
  document.addEventListener('click',event=>{if(event.target.closest('a[data-unavailable]'))event.preventDefault();},true);
  function taskRows(items) {
    const target=$('overview-tasks');target.replaceChildren();
    if(!items.length){target.textContent='当前没有制作中或待发布的记录。';return;}
    items.slice(0,5).forEach(({video,tab})=>{
      const row=document.createElement('div');row.className='console-task';const info=document.createElement('div');
      info.textContent=video.display_title||video.published_title||video.zh_title||video.title||video.youtube_id;
      const time=document.createElement('small');time.textContent='更新：'+(video.updated_at?new Date(String(video.updated_at).replace(' ','T')+'Z').toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})+'（北京时间）':'未记录');info.append(time);
      const stage=document.createElement('span');stage.className='console-stage';stage.textContent=label[tab];
      const link=document.createElement('a');const url=new URL(listURL(tab),location.origin);url.searchParams.set('search',video.youtube_id);link.href=url.pathname+url.search;link.textContent='查看';
      row.append(info,stage,link);target.append(row);
    });
  }
  const attentionLabels={delivery:['投递结果待核实','核实投递结果','review'],blocked:['登录/恢复受阻','查看阻塞原因','error'],execution:['执行异常待排查','查看错误详情','error'],review:['平台审核中','查看审核记录','review'],policy:['内容规则拦截','按需复核','error']};
  function attentionRows(data) {
    const main=$('attention-main'), other=$('attention-observation');main.replaceChildren();other.replaceChildren();
    ['delivery','blocked','execution','review','policy'].forEach(kind=>{
      const item=data[kind], [name,action,tab]=attentionLabels[kind];
      if(!Number.isInteger(item?.count))throw new Error('关注数据格式不完整');
      const link=document.createElement('a');link.href=listURL(tab)+'&attention_kind='+kind+'&sort=updated_at_desc';
      link.dataset.attention=kind; if(!item.count)link.className='console-zero';
      const info=document.createElement('span');info.textContent=name+' '+item.count;
      const date=new Date(String(item.updated_at||'').replace(' ','T')+'Z');
      const time=document.createElement('small');time.textContent='记录最近更新：'+(Number.isNaN(date.valueOf())?'未记录':date.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+'（北京时间）');info.append(time);
      const next=document.createElement('span');next.textContent=action+' →';link.append(info,next);
      (['review','policy'].includes(kind)||!item.count?other:main).append(link);
    });
    if(!main.children.length) main.textContent='当前没有这些待核实或受阻事项。';
  }
  async function loadOverview() {
    if(busy)return;busy=true;const generation=++overviewGeneration;$('overview-retry').disabled=true;
    try {
      const tabs=['waitlist','active','ready','error'];
      const [results,attention]=await Promise.all([Promise.all(tabs.map(tab=>readJSON('/api/videos?tab='+tab+'&size=20&created_window=all'))),readJSON('/api/console/attention')]);
      if(generation!==overviewGeneration||view!=='overview')return;
      if(results.some(d=>!Number.isInteger(d.total_count)||!Array.isArray(d.videos)))throw new Error('列表数据格式不完整');
      const data=Object.fromEntries(tabs.map((tab,i)=>[tab,results[i]]));
      tabs.forEach(tab=>{[$('overview-'+tab),$('attention-'+tab)].filter(Boolean).forEach(el=>el.textContent=data[tab].total_count);});
      attentionRows(attention);
      taskRows(['active','ready'].flatMap(tab=>data[tab].videos.map(video=>({tab,video}))));
      lastSuccess=new Date().toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai'});
      $('overview-feedback').textContent='列表概览 · 最后成功读取 '+lastSuccess+'（北京时间）';$('overview-feedback').classList.remove('console-error');
      $('last-update').textContent='数据更新 '+lastSuccess;
    } catch(error) {
      if(generation!==overviewGeneration||view!=='overview')return;
      $('overview-feedback').textContent=lastSuccess?'读取失败，当前为旧数据 · 最后成功 '+lastSuccess:'读取失败，暂无可信数据。请重新读取。';$('overview-feedback').classList.add('console-error');
      $('last-update').textContent=lastSuccess?'旧数据 · '+lastSuccess:'读取失败';
      if(!lastSuccess){$('overview-tasks').textContent='任务读取失败，请重新读取。';$('attention-main').textContent='关注事项读取失败，请重新读取。';}
    } finally {busy=false;$('overview-retry').disabled=false;}
  }
  async function refresh() {
    if(view==='overview')await Promise.all([loadOverview(),legacy.funnel(),capability()]);
    // 配置及列表只在进入时读取，避免轮询重画频道、表单与当前选择。
  }
  function navigate(url,{pop=false}={}) {
    const p=url.searchParams;view=titles[p.get('view')]?p.get('view'):groups[p.get('tab')]||'overview';
    if(!pop&&url.href!==location.href)history.pushState(null,'',url);
    restoring=true;legacy.invalidate();
    const fallback={topics:'waitlist',production:'queue',publications:'review'}[view];
    const tab=groups[p.get('tab')]===view?p.get('tab'):fallback;
    if(tab)legacy.restore(p,tab);
    paint();restoring=false;
    if(view==='overview')refresh();
    if(view==='operations'){window.fetchChannels?.();legacy.audit();}
  }
  window.DashboardWorkspace={navigate,selectTab,persist,refresh,restoring:()=>restoring,view:()=>view};
  window.addEventListener('popstate',()=>navigate(new URL(location.href),{pop:true}));
  $('overview-retry').onclick=()=>refresh();
  navigate(new URL(location.href),{pop:true});legacy.startRefresh();
})();
