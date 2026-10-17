/** 生词片尾：独立草稿、CAS 保存、匹配预览与任务结果。 */
(() => {
  const $ = id => document.getElementById(id);
  const base = '/api/vocabulary-outro-settings';
  const reasons = {content_type:'任务内容类型',channel:'来源频道',topic:'显式 AI 主题',default:'未命中特定类型'};
  const statuses = {PENDING:'待完成',DISABLED:'配置关闭',RENDERED:'已生成片尾',NO_SUITABLE_TERMS:'独立复核后无合适生词',FAILED:'处理失败'};
  let saved = null, savedDigest = '', groups = {}, busy = false, conflict = false, previewGeneration = 0;
  let previewController, leaveAction, returnFocus;
  const node = (tag, text, cls) => {const n = document.createElement(tag); n.textContent = text; if(cls)n.className=cls; return n;};

  async function api(path, options = {}) {
    const controller = options.controller || new AbortController();
    const timer = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(base + path, {...options, headers:{'Content-Type':'application/json'}, signal:controller.signal});
      const result = await response.json();
      if(!response.ok) {
        const error = new Error(typeof result.detail === 'string' ? result.detail : '请求校验未通过，请检查表单。');
        error.status = response.status; throw error;
      }
      return result;
    } catch(error) {
      if(error.name === 'AbortError') throw new Error('请求超时或已取消，请重试。');
      throw error;
    } finally {clearTimeout(timer);}
  }
  function draft() {
    const config = structuredClone(saved);
    config.enabled = $('enabled').checked;
    for(const group of Object.keys(groups)) {
      config.profiles[group].enabled = $('group-' + group).checked;
      const input = $('channels-' + group);
      if(input) config.profiles[group].channel_ids = input.value.split(/[,，\s]+/).filter(Boolean);
    }
    return config;
  }
  const dirty = () => saved && JSON.stringify(draft()) !== JSON.stringify(saved);
  function state() {
    $('editor').disabled = !saved || busy;
    $('save').disabled = !dirty() || busy || conflict;
    $('reload').disabled = busy;
    $('dirty-state').textContent = busy ? '正在处理…' : !saved ? '尚未载入' : dirty() ? '有未保存修改' : '配置已载入';
    if(saved) $('effective-state').textContent = $('enabled').checked ? '总开关已开启，各类型按下方开关执行。' : '总开关已关闭，下方类型选择会保留，当前均不追加。';
  }
  function invalidatePreview() {
    previewGeneration++; previewController?.abort();
    $('preview-result').textContent = '表单或上下文已变化，请重新预览。';
    $('preview').disabled = false;
  }
  function render(value) {
    saved = value.config; savedDigest = value.digest; groups = value.groups;
    $('enabled').checked = saved.enabled;
    $('profiles').replaceChildren(); $('channel-fields').replaceChildren();
    for(const [key,label] of Object.entries(groups)) {
      const line = document.createElement('label'); line.className='outro-toggle'; line.htmlFor='group-'+key;
      const input = document.createElement('input'); input.type='checkbox'; input.id='group-'+key; input.checked=saved.profiles[key].enabled;
      line.append(node('span',label),input); $('profiles').append(line);
      if(['wallstreet','ted','ai_news'].includes(key)) {
        const labelNode = node('label',label+'来源频道'); labelNode.htmlFor='channels-'+key;
        const channels=document.createElement('input');channels.type='text';channels.id='channels-'+key;
        channels.value=saved.profiles[key].channel_ids.join(', ');channels.setAttribute('aria-describedby','feedback');
        $('channel-fields').append(labelNode,channels);
      }
    }
    conflict=false;invalidatePreview();state();
  }
  async function load() {
    if(busy)return;
    busy=true;state();$('feedback').textContent='正在读取配置…';
    try {render(await api(''));$('feedback').textContent='已载入保存配置；新任务在开始制作片尾时采用。';}
    catch(error) {$('feedback').textContent=error.message+' 当前草稿已保留。';}
    finally {busy=false;state();}
  }
  function guard(action) {
    if(busy)return;
    if(!dirty()){action();return;}
    leaveAction=action;returnFocus=document.activeElement;$('discard-dialog').showModal();$('keep-editing').focus();
  }
  $('keep-editing').onclick=()=>$('discard-dialog').close();
  $('discard').onclick=()=>{const action=leaveAction;$('discard-dialog').close();action?.();};
  $('discard-dialog').addEventListener('close',()=>{leaveAction=null;returnFocus?.focus();});
  window.consoleNavigationGuard=guard;
  $('back').onclick=event=>{event.preventDefault();guard(()=>location.assign($('back').href));};
  window.addEventListener('beforeunload',event=>{if(dirty()){event.preventDefault();event.returnValue='';}});
  $('reload').onclick=()=>guard(load);
  $('settings-form').onsubmit=event=>event.preventDefault();
  $('settings-form').addEventListener('input',event=>{
    if(event.target.id==='video') $('sample-context').hidden=Boolean($('video').value);
    invalidatePreview();state();
  });
  $('save').onclick=async()=>{
    if(busy||!dirty()||conflict)return;
    const config=draft();busy=true;state();$('feedback').textContent='正在保存…';
    try {
      const result=await api('',{method:'PUT',body:JSON.stringify({config,expected_digest:savedDigest})});
      render(result);$('feedback').textContent='配置已保存。尚未开始制作片尾的任务会采用新配置。';
    } catch(error) {
      if(error.status===409)conflict=true;
      $('feedback').textContent=error.message+' 草稿已保留。';
    } finally {busy=false;state();}
  };
  $('preview').onclick=async()=>{
    const generation=++previewGeneration;previewController?.abort();previewController=new AbortController();
    const context={content_type:$('content-type').value,source_channel_id:$('channel').value.trim(),product_topic:$('topic').value};
    $('preview').disabled=true;$('preview-result').textContent='正在预览…';
    try {
      const result=await api('/preview',{method:'POST',controller:previewController,body:JSON.stringify({config:draft(),video_key:$('video').value||null,context})});
      if(generation!==previewGeneration)return;
      const d=result.decision;$('preview-result').replaceChildren(node('p',d.group_label+' · '+(d.applicable===false?'独立学习卡，不经过此步骤':d.enabled?'追加生词片尾':'不追加生词片尾')),
        node('p','匹配原因：'+(reasons[d.reason]||d.reason)),node('p',result.scope,'hint'));
      if(result.frozen) $('preview-result').append(node('p','此任务已固定采用：'+result.frozen.group_label+' · '+(statuses[result.frozen.status]||'状态未知')+'；本次保存不改变该任务。'));
    } catch(error) {if(generation===previewGeneration)$('preview-result').textContent=error.message;}
    finally {if(generation===previewGeneration)$('preview').disabled=false;}
  };
  async function loadVideos() {
    $('reload-videos').disabled=true;$('videos-state').textContent='正在读取最近任务…';
    try {
      const result=await api('/videos');const selected=$('video').value;
      $('video').replaceChildren(new Option('使用样例上下文',''));
      for(const video of result.videos) $('video').add(new Option(video.title||video.youtube_id,video.preview_key));
      $('video').value=[...$('video').options].some(x=>x.value===selected)?selected:'';
      $('sample-context').hidden=Boolean($('video').value);
      $('videos-state').textContent=result.videos.length?`已载入 ${result.videos.length} 条任务。`:'暂无最近任务，可使用样例预览。';
      invalidatePreview();
    }catch(error){$('videos-state').textContent=error.message+' 可使用样例预览。';}
    finally{$('reload-videos').disabled=false;}
  }
  async function loadRecords() {
    $('reload-records').disabled=true;$('records-state').textContent='正在读取执行记录…';
    try {
      const result=await api('/records');$('records').replaceChildren();
      for(const record of result.records) {
        const row=node('article','', 'outro-record');row.append(node('strong',record.prefix+' · '+(statuses[record.status]||'状态未知')));
        row.append(node('p',`${record.group_label} · ${record.items_count ?? '—'} 个生词${record.recovery_checked?' · 已独立复核':''}`));
        const time=new Date(record.updated_at||record.recorded_at);
        row.append(node('p',Number.isNaN(time.valueOf())?'时间未知':time.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}),'hint'));
        if(record.status==='FAILED')row.append(node('p','异常：'+(record.error_code||'未知')+'。该任务需排查后重试。'));
        $('records').append(row);
      }
      $('records-state').textContent=(result.records.length?`最近 ${result.records.length} 条本地结果。`:'尚无新配置的执行记录。')+(result.unreadable?` ${result.unreadable} 条记录不可读取，状态未知。`:'');
    }catch(error){$('records-state').textContent=error.message+' 已显示内容可能过期。';}
    finally{$('reload-records').disabled=false;}
  }
  $('reload-videos').onclick=loadVideos;$('reload-records').onclick=loadRecords;
  ['reload','reload-videos','preview','reload-records','keep-editing','discard'].forEach(id=>$(id).disabled=false);
  load();loadVideos();loadRecords();
})();
