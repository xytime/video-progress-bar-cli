/** 评论回复：分栏阅读、直接筛选、请求竞态保护与保留草稿的策略保存。
 * Modification History
 * | Version | Date | Author | Description |
 * | --- | --- | --- | --- |
 * | reply-recovery-v1 | 2026-10-25 | Codex | 活动版本保存、本机验证、真实错误与草稿保护。 |
 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const base = '/api/secondary-reply-settings';
  const defaults = {tab:'ledger', page:1, size:10, sort:'newest_desc', status:'all', platform_post_id:'all', time_window:'all', style:'all', provider_kind:'all', search:''};
  const filters = {...defaults};
  const statuses = {APPROVED:'待发送', PENDING_REVIEW:'待审核', VERIFIED:'已核实', UNCERTAIN:'待只读对账', FAILED:'失败', SKIPPED:'已跳过', MANUAL:'人工处理'};
  const styles = {MACRO:'宏观视角', PRAGMATIC:'务实交流', PHILOSOPHICAL:'哲理思辨', CASUAL_LIGHT:'轻松互动', CASUAL:'轻松互动', HUMOROUS:'幽默互动'};
  const fields = {'window-start':'window_start_shanghai', 'window-end':'window_end_shanghai', 'min-interval-seconds':'min_interval_seconds', 'hourly-quota':'hourly_quota', 'max-per-video':'max_per_video', 'approval-mode':'approval_mode'};
  let saved = null, digest = '', revision = null, busy = false, conflict = false;
  let items = [], selected = '', historyController, historySequence = 0, searchTimer, composing = false;
  let leaveAction, returnFocus, listScroll = 0;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const statusBadge = status => `<span class="sr-badge ${statuses[status] ? status.toLowerCase() : ''}">${esc(statuses[status] || status || '未知状态')}</span>`;
  const dateFormatter = new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
  function parseDate(value) {
    if (value === null || value === undefined || value === '') return null;
    let raw = String(value).trim();
    if (/^\d+$/.test(raw)) raw = Number(raw) * (Number(raw) > 10000000000 ? 1 : 1000);
    else if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(raw)) raw = raw.replace(' ','T') + 'Z';
    const date = new Date(raw);
    return Number.isNaN(date.getTime()) ? null : date;
  }
  const time = value => { const date = parseDate(value); return date ? dateFormatter.format(date).replace(/\//g,'-') : '暂无记录'; };
  const shortDate = new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'});
  const shortClock = new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
  function compactTime(value, terse = false) {
    const date = parseDate(value);
    if (!date) return '暂无记录';
    const day = shortDate.format(date), today = shortDate.format(new Date());
    const yesterday = shortDate.format(new Date(Date.now() - 86400000));
    return `${day === today ? '今天' : day === yesterday ? '昨天' : day.replace(/\//g,'-').slice(terse ? 5 : 0)} ${shortClock.format(date)}`;
  }
  const timeElement = (value, clockOnly = false) => `<time${parseDate(value) ? ' datetime="' + parseDate(value).toISOString() + '"' : ''} title="${esc(time(value))}">${esc(clockOnly && parseDate(value) ? shortClock.format(parseDate(value)) : compactTime(value,true))}</time>`;
  const originalTime = item => item.comment_createtime || item.comment_discovered_at || item.created_at;
  const key = item => String(item.task_id);
  const title = item => item.video_zh_title || item.video_title || '未命名视频';
  const provider = value => /manual/i.test(value || '') ? '人工精修导入' : value ? 'AI 生成' : '来源未记录';

  async function api(path, options = {}) {
    const controller = new AbortController();
    const external = options.signal;
    const abort = () => controller.abort();
    if (external?.aborted) abort();
    external?.addEventListener('abort', abort, {once:true});
    const timer = setTimeout(abort, 12000);
    try {
      const csrf = document.querySelector('meta[name="runtime-csrf"]')?.content;
      const headers = {'Content-Type':'application/json'};
      if (csrf && !csrf.startsWith('__')) headers['X-Runtime-CSRF'] = csrf;
      const response = await fetch(base + path, {...options, headers, signal:controller.signal});
      const result = await response.json();
      if (!response.ok) {
        const error = new Error(typeof result.detail === 'string' ? result.detail : '请求校验未通过，请检查输入。');
        error.status = response.status;
        throw error;
      }
      return result;
    } catch (error) {
      if (error.name === 'AbortError' && !external?.aborted) throw new Error('读取超时，请重试。');
      throw error;
    } finally { clearTimeout(timer); external?.removeEventListener('abort', abort); }
  }
  function writeURL() {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([name,value]) => {
      // 搜索内容可能含个人信息，不写入地址或持久存储。
      if (name !== 'search' && value !== defaults[name]) params.set(name,String(value));
    });
    history.replaceState(null,'',location.pathname + (params.size ? '?' + params : '') + location.hash);
  }
  function readURL() {
    const params = new URLSearchParams(location.search);
    ['tab','status','platform_post_id','style'].forEach(name => { if (params.has(name)) filters[name] = params.get(name); });
    for (const [name,id] of [['sort','filter-sort'],['time_window','filter-time-window'],['provider_kind','filter-provider']]) {
      const value = params.get(name);
      if ([...$(id).options].some(option => option.value === value)) filters[name] = value;
    }
    filters.size = [5,10,20,50].includes(Number(params.get('size'))) ? Number(params.get('size')) : 10;
    filters.page = Math.max(1, Math.min(500, Number.parseInt(params.get('page'),10) || 1));
    if (![...Object.keys(statuses),'all','INACTIVE'].includes(filters.status)) filters.status = 'all';
    if (!['ledger','policy'].includes(filters.tab)) filters.tab = 'ledger';
  }
  function switchTab(tab, focus = false) {
    filters.tab = tab;
    ['ledger','policy'].forEach(name => {
      const active = name === tab;
      $('tab-' + name).setAttribute('aria-selected',String(active));
      $('tab-' + name).tabIndex = active ? 0 : -1;
      $('view-' + name).hidden = !active;
    });
    if (focus) $('tab-' + tab).focus();
    writeURL();
  }
  const hasRecordFilters = () => Object.keys(defaults).some(name => !['tab','page','size','sort'].includes(name) && filters[name] !== defaults[name]);
  function syncFilters() {
    const ids = {size:'filter-size',sort:'filter-sort',platform_post_id:'filter-video',time_window:'filter-time-window',style:'filter-style',provider_kind:'filter-provider',search:'filter-search'};
    Object.entries(ids).forEach(([name,id]) => {
      const element = $(id);
      if (element.tagName === 'SELECT' && ![...element.options].some(option => option.value === String(filters[name]))) {
        element.add(new Option(name === 'platform_post_id' ? '当前所选视频' : filters[name], filters[name]));
      }
      element.value = String(filters[name]);
    });
    document.querySelectorAll('[data-status]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.status === filters.status)));
    $('filter-other-status').value = ['INACTIVE','SKIPPED','MANUAL'].includes(filters.status) ? filters.status : 'all';
    $('clear-search').hidden = !filters.search;
    $('btn-clear-filters').disabled = !hasRecordFilters();
  }
  function renderList() {
    $('history-list').innerHTML = items.length ? items.map(item => `<button type="button" class="sr-record" data-record="${esc(key(item))}" aria-current="${key(item) === selected}" aria-controls="record-detail"><span class="sr-record-top"><span class="sr-record-title">《${esc(title(item))}》</span>${statusBadge(item.status)}</span><span class="sr-record-person">${esc(item.nickname || '匿名观众')}</span><span class="sr-record-comment">${esc(item.comment_content || '原评内容未记录')}</span><span class="sr-record-time">${timeElement(originalTime(item))}</span><span class="sr-record-likes">${esc(item.comment_like_count ?? 0)} 赞</span></button>`).join('') : '<p class="sr-empty">没有符合条件的回复记录。<br>可调整或清除筛选，也可刷新记录。</p>';
    renderDetail();
  }
  function metadata(rows) {
    return '<dl class="sr-metadata">' + rows.map(([label,value]) => `<dt>${esc(label)}</dt><dd>${esc(value === null || value === undefined || value === '' ? '未记录' : typeof value === 'object' ? JSON.stringify(value,null,2) : value)}</dd>`).join('') + '</dl>';
  }
  function renderDetail() {
    const item = items.find(row => key(row) === selected);
    if (!item) {
      $('record-detail').innerHTML = '<h2 id="detail-title" class="sr-only">回复详情</h2><p class="sr-empty">暂无可展示的回复详情。</p>';
      return;
    }
    const steps = [['采集',item.comment_discovered_at || item.created_at],['生成',item.created_at],['提交意图',item.submit_intent_at],['核实',item.verified_at]];
    const notice = item.status === 'UNCERTAIN' ? '发送结果尚未确认，需按既有流程只读对账。' : item.status === 'PENDING_REVIEW' ? '等待 Telegram 审批；审批入口仍在原有卡片。' : '';
    $('record-detail').innerHTML = `<button class="sr-mobile-back" id="back-to-list" type="button"><span class="sr-icon sr-icon-left" aria-hidden="true"></span>返回列表</button><div class="sr-detail-head"><h2 id="detail-title" class="sr-detail-video-title">《${esc(title(item))}》</h2><p class="sr-detail-meta">${esc(item.nickname || '匿名观众')} · ${esc(compactTime(originalTime(item)))}</p>${statusBadge(item.status)}</div>
      <section class="sr-detail-section"><h3>观众评论</h3><p class="sr-conversation">${esc(item.comment_content || '原评内容未记录')}</p><p class="sr-detail-meta">${timeElement(item.comment_createtime)} · 观众 ${esc(item.nickname || '匿名观众')} · ${esc(item.comment_like_count ?? 0)} 赞${!item.comment_createtime ? ' · 原评发布时间未记录' : ''}</p></section>
      <section class="sr-detail-section"><h3>作者回复</h3><div class="sr-reply-copy"><p class="sr-conversation" lang="zh-CN">${esc(item.chinese_reply || '暂无中文回复')}</p>${item.english_reply ? `<span class="sr-reply-label">英文回复</span><p class="sr-conversation sr-reply-en" lang="en">${esc(item.english_reply)}</p>` : ''}</div>${notice ? `<p class="sr-detail-note">${esc(notice)}</p>` : ''}${item.error_message || (['FAILED','UNCERTAIN','SKIPPED','MANUAL'].includes(item.status) && item.reason_code) ? `<p class="sr-detail-note">${esc(item.reason_code)}${item.error_message ? '<br>' + esc(item.error_message) : ''}</p>` : ''}</section>
      <section class="sr-detail-section"><h3>处理记录</h3><ol class="sr-timeline${steps.every(([,value]) => parseDate(value)) ? ' is-complete' : ''}">${steps.map(([label,value]) => `<li class="${parseDate(value) ? 'is-done' : ''}"><span class="sr-step-icon" aria-hidden="true"></span><strong>${label}</strong>${timeElement(value,true)}</li>`).join('')}</ol></section>
      <details id="record-evidence"><summary><span class="sr-only">查看</span>技术凭据</summary>${metadata([['视频中文标题',title(item)],['视频英文标题',item.video_en_title],['视频发布时间',time(item.video_published_at)],['任务 ID',item.task_id],['处理状态',item.status],['原评论 ID',item.comment_id],['原评发布时间',time(item.comment_createtime)],['采集入库时间',time(item.comment_discovered_at || item.created_at)],['草稿生成时间',time(item.created_at)],['审批通过时间',time(item.approved_at)],['提交意图时间',time(item.submit_intent_at)],['平台回读核实时间',time(item.verified_at)],['平台视频 ID',item.platform_post_id],['Telegram 审批消息',item.approval_message_id],['平台回复 ID',item.platform_reply_comment_id],['证据引用',item.evidence_refs]])}</details>
      <details id="record-generation"><summary><span class="sr-only">查看</span>生成信息</summary>${metadata([['中文字数',Array.from(item.chinese_reply || '').length],['英文字数',Array.from(item.english_reply || '').length],['回复意图',item.intent],['回复风格',styles[item.style] || item.style],['风格标识',item.style],['生成来源',provider(item.provider)],['生成标识',item.provider],['原因代码',item.reason_code],['错误详情',item.error_message]])}</details>
      <div class="sr-detail-footer"><button id="expand-record" type="button" aria-expanded="false">查看完整记录<span class="sr-icon sr-icon-right" aria-hidden="true"></span></button></div>`;
    $('expand-record').addEventListener('click', () => {
      const open = !$('record-evidence').open || !$('record-generation').open;
      $('record-evidence').open = open; $('record-generation').open = open;
      $('expand-record').setAttribute('aria-expanded',String(open));
      $('expand-record').firstChild.textContent = open ? '收起完整记录' : '查看完整记录';
    });
    const syncDisclosure = () => {
      if (!$('record-evidence') || !$('record-generation') || !$('expand-record')) return;
      const open = $('record-evidence').open && $('record-generation').open;
      $('expand-record').setAttribute('aria-expanded',String(open));
      $('expand-record').firstChild.textContent = open ? '收起完整记录' : '查看完整记录';
    };
    ['record-evidence','record-generation'].forEach(id => $(id).addEventListener('toggle',syncDisclosure));
    $('back-to-list').addEventListener('click', returnToList);
  }
  function returnToList() {
    $('view-ledger').classList.remove('is-mobile-detail');
    const row = [...document.querySelectorAll('[data-record]')].find(button => button.dataset.record === selected);
    row?.focus({preventScroll:true});
    window.scrollTo({top:listScroll,behavior:'instant'});
  }
  function renderPagination(data) {
    const totalPages = Math.max(1, data.total_pages || 1);
    filters.page = data.page || filters.page;
    $('history-counts').textContent = `共 ${data.total_count ?? 0} 条 · 第 ${filters.page} / ${totalPages} 页`;
    const pages = [...new Set([1,filters.page-1,filters.page,filters.page+1,totalPages])].filter(page => page > 0 && page <= totalPages).sort((a,b) => a-b);
    const button = (label,page,disabled,current = false) => `<button type="button" data-page="${page}"${disabled ? ' disabled' : ''}${current ? ' aria-current="page"' : ''} aria-label="${esc(current ? '当前第 ' + page + ' 页' : label)}">${esc(label)}</button>`;
    $('page-controls').innerHTML = button('上一页',filters.page-1,filters.page<=1) + pages.map((page,index) => (index && page-pages[index-1]>1 ? '<span aria-hidden="true">…</span>' : '') + button(String(page),page,false,page===filters.page)).join('') + button('下一页',filters.page+1,filters.page>=totalPages);
    document.querySelectorAll('[data-count]').forEach(element => { element.textContent = data.counts?.[element.dataset.count] ?? (element.dataset.count === 'all' ? data.global_total ?? 0 : 0); });
    const videos = data.filter_options?.videos || [];
    $('filter-video').innerHTML = '<option value="all">全部视频</option>' + videos.map(video => `<option value="${esc(video.platform_post_id)}">${esc(video.video_title || video.platform_post_id)} (${esc(video.count)})</option>`).join('');
    syncFilters(); writeURL();
  }
  async function loadHistory(clear = false) {
    historyController?.abort();
    historyController = new AbortController();
    const controller = historyController, sequence = ++historySequence;
    $('reading-workspace').setAttribute('aria-busy','true');
    $('history-feedback').textContent = '正在读取回复记录…';
    $('retry-history').hidden = true;
    if (clear) {
      items = []; selected = ''; $('view-ledger').classList.remove('is-mobile-detail');
      $('history-list').innerHTML = '<p class="sr-empty">正在读取记录…</p>';
      $('record-detail').innerHTML = '<h2 id="detail-title" class="sr-only">回复详情</h2><p class="sr-empty">正在读取记录…</p>';
      $('history-counts').textContent = '正在读取…'; $('page-controls').replaceChildren();
    }
    const params = new URLSearchParams(Object.entries(filters).filter(([name]) => name !== 'tab'));
    try {
      const data = await api('/history?' + params, {signal:controller.signal});
      if (sequence !== historySequence) return;
      items = data.items || [];
      if (!items.some(item => key(item) === selected)) selected = items[0] ? key(items[0]) : '';
      renderList(); renderPagination(data);
      $('history-feedback').textContent = hasRecordFilters() ? `匹配 ${data.total_count ?? 0} 条 · 上方状态数量为全量统计` : '';
    } catch (error) {
      if (sequence !== historySequence || controller.signal.aborted) return;
      $('history-feedback').textContent = `记录读取失败：${error.message}${items.length ? '。下方保留上次读取结果。' : ''}`;
      $('retry-history').hidden = false;
      if (!items.length) {
        $('history-list').innerHTML = '<p class="sr-empty">记录暂时不可用，请重试读取。</p>';
        renderDetail(); $('history-counts').textContent = '尚未读取记录';
      }
    } finally { if (sequence === historySequence) $('reading-workspace').setAttribute('aria-busy','false'); }
  }
  function applyFilters() {
    clearTimeout(searchTimer); filters.page = 1;
    syncFilters(); writeURL(); loadHistory(true);
  }
  function draft() {
    const value = structuredClone(saved || {});
    Object.entries(fields).forEach(([id,name]) => { value[name] = $(id).type === 'number' ? ($(id).value === '' ? null : Number($(id).value)) : $(id).value.trim(); });
    return value;
  }
  const dirty = () => Boolean(saved && JSON.stringify(draft()) !== JSON.stringify(saved));
  function interval(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0) return '请输入有效秒数';
    if (!seconds) return '不限制最小间隔';
    return `${seconds % 3600 === 0 ? seconds / 3600 + ' 小时' : seconds % 60 === 0 ? seconds / 60 + ' 分钟' : seconds + ' 秒'}`;
  }
  const windowLabel = config => config.window_start_shanghai === config.window_end_shanghai || (config.window_start_shanghai === '00:00' && config.window_end_shanghai === '24:00') ? '全天 24 小时' : `${config.window_start_shanghai}–${config.window_end_shanghai}`;
  function state() {
    $('editor').disabled = !saved || busy;
    $('save').disabled = !dirty() || busy || conflict;
    $('reload-policy').disabled = busy;
    $('dirty-state').textContent = busy ? '正在处理…' : !saved ? '尚未载入策略' : conflict ? '保存冲突，草稿已保留' : dirty() ? '有未保存的修改' : '与已保存策略一致';
    if (!saved) return;
    const value = draft();
    $('preview-window').textContent = windowLabel(value);
    $('preview-interval').textContent = interval(value.min_interval_seconds);
    $('preview-hourly').textContent = `${value.hourly_quota ?? '—'} 条 / 60 分钟`;
    $('preview-video-max').textContent = `${value.max_per_video ?? '—'} 条 / 视频`;
    $('window-summary').textContent = `当前表单：北京时间 ${windowLabel(value)}`;
    $('interval-summary').textContent = `当前表单：${interval(value.min_interval_seconds)}`;
    $('policy-preview').textContent = `${dirty() ? '未保存草稿' : '已保存配置'}：${value.approval_mode === 'hybrid_auto' ? '自动回复 + 事后通告' : '人工审批后发送'}。`;
  }
  function renderPolicy(data) {
    revision = data.revision ?? null;
    $('min-interval-seconds').min = data.limits?.min_interval_seconds ?? 0;
    $('hourly-quota').max = data.limits?.hourly_quota ?? 100;
    $('min-interval-seconds').labels[0].textContent = `最小提交间隔（秒，${$('min-interval-seconds').min}–86400）`;
    $('hourly-quota').labels[0].textContent = `账号滚动 60 分钟上限（1–${$('hourly-quota').max}）`;
    $('quota-source').textContent = revision ? '回复使用独立额度；首评单独计额。所有调整仍受已批准边界约束。' : '首评和二级回复共享账号滚动 60 分钟配额。';
    saved = data.config; digest = data.digest; conflict = false;
    Object.entries(fields).forEach(([id,name]) => { $(id).value = String(saved[name]); $(id).removeAttribute('aria-invalid'); });
    $('saved-summary').innerHTML = `${esc(saved.approval_mode === 'hybrid_auto' ? '自动回复' : '人工审批')} · 北京时间 ${esc(windowLabel(saved))}<span class="sr-saved-schedule"> · 间隔 ${esc(interval(saved.min_interval_seconds))}</span><span class="sr-saved-limits"> · ${esc(saved.hourly_quota)} 条 / 60 分钟 · ${esc(saved.max_per_video)} 条 / 视频</span>`;
    state();
  }
  async function loadPolicy() {
    if (busy) return;
    busy = true; state();
    try { renderPolicy(await api('')); $('feedback').textContent = ''; }
    catch (error) { $('feedback').textContent = '策略读取失败：' + error.message + '。可重新载入策略。'; if (!saved) $('saved-summary').textContent = '读取失败，可进入策略页重试'; }
    finally { busy = false; state(); }
  }
  function validate() {
    const value = draft();
    const failures = [];
    const clock = /^([01]\d|2[0-3]):[0-5]\d$/;
    if (!clock.test(value.window_start_shanghai)) failures.push(['window-start','开始时间须为 00:00–23:59。']);
    if (!clock.test(value.window_end_shanghai) && value.window_end_shanghai !== '24:00') failures.push(['window-end','结束时间须为 00:00–24:00。']);
    [['min-interval-seconds',Number($('min-interval-seconds').min),86400],['hourly-quota',1,Number($('hourly-quota').max)],['max-per-video',1,20]].forEach(([id,min,max]) => { const number = value[fields[id]]; if (!Number.isInteger(number) || number < min || number > max) failures.push([id,`${$(id).labels[0].textContent}须为范围内整数。`]); });
    if (!['manual','hybrid_auto'].includes(value.approval_mode)) failures.push(['approval-mode','请选择有效回复方式。']);
    Object.keys(fields).forEach(id => { $(id).setAttribute('aria-invalid',String(failures.some(([field]) => id === field))); $(id).setAttribute('aria-describedby','feedback'); });
    if (failures.length) { $('feedback').textContent = failures.map(([,message]) => message).join(' '); $(failures[0][0]).focus(); return false; }
    return true;
  }
  function guarded(action) {
    if (!dirty()) { action(); return; }
    leaveAction = action; returnFocus = document.activeElement;
    $('keep-editing').disabled = false; $('discard').disabled = false;
    $('discard-dialog').showModal(); $('keep-editing').focus();
  }
  $('discard-dialog').addEventListener('close',() => { returnFocus?.focus(); });
  $('keep-editing').addEventListener('click',() => { leaveAction = null; $('discard-dialog').close(); });
  $('discard').addEventListener('click',() => { const action = leaveAction; leaveAction = null; $('discard-dialog').close(); action?.(); });
  $('discard-dialog').addEventListener('cancel',() => { leaveAction = null; });
  window.addEventListener('beforeunload',event => { if (dirty()) { event.preventDefault(); event.returnValue = ''; } });
  document.addEventListener('click',event => {
    const anchor = event.target.closest('a[href]');
    if (!anchor || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || anchor.target === '_blank' || anchor.origin !== location.origin || anchor.href === location.href || !dirty()) return;
    event.preventDefault(); guarded(() => { saved = null; location.assign(anchor.href); });
  });
  $('settings-form').addEventListener('input',state);
  $('settings-form').addEventListener('change',state);
  $('settings-form').addEventListener('submit',async event => {
    event.preventDefault();
    if (busy || conflict || !dirty() || !validate()) return;
    const config = draft(); busy = true; state(); $('feedback').textContent = '正在保存策略…';
    try { renderPolicy(await api('', {method:'PUT',body:JSON.stringify({config,expected_digest:digest,expected_revision:revision})})); $('feedback').textContent = '策略已保存；后续执行将按既有机制读取。'; }
    catch (error) { conflict = error.status === 409; $('feedback').textContent = `${conflict ? '保存冲突：' : '保存失败：'}${error.message} 草稿已保留。`; }
    finally { busy = false; state(); }
  });
  $('reload-policy').addEventListener('click',() => guarded(loadPolicy));
  $('edit-policy').addEventListener('click',() => switchTab('policy',true));
  ['ledger','policy'].forEach(name => $('tab-' + name).addEventListener('click',() => switchTab(name)));
  document.querySelector('[role=tablist]').addEventListener('keydown',event => { if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return; event.preventDefault(); switchTab(event.key === 'Home' ? 'ledger' : event.key === 'End' ? 'policy' : filters.tab === 'policy' ? 'ledger' : 'policy',true); });
  [['preset-24h','00:00','24:00'],['preset-daytime','08:30','23:00']].forEach(([id,start,end]) => $(id).addEventListener('click',() => { $('window-start').value = start; $('window-end').value = end; state(); }));
  [['preset-interval-1h',3600],['preset-interval-2h',7200],['preset-interval-30m',1800]].forEach(([id,seconds]) => $(id).addEventListener('click',() => { $('min-interval-seconds').value = seconds; state(); }));
  Object.entries({size:'filter-size',sort:'filter-sort',platform_post_id:'filter-video',time_window:'filter-time-window',style:'filter-style',provider_kind:'filter-provider'}).forEach(([name,id]) => $(id).addEventListener('change',() => { filters[name] = name === 'size' ? Number($(id).value) : $(id).value; applyFilters(); }));
  $('status-filters').addEventListener('click',event => { const button = event.target.closest('[data-status]'); if (button) { filters.status = button.dataset.status; applyFilters(); } });
  $('filter-other-status').addEventListener('change',() => { filters.status = $('filter-other-status').value; applyFilters(); });
  $('history-list').addEventListener('click',event => {
    const button = event.target.closest('[data-record]'); if (!button) return;
    selected = button.dataset.record; listScroll = window.scrollY;
    renderList(); $('view-ledger').classList.add('is-mobile-detail');
    if (matchMedia('(max-width:720px)').matches) { $('back-to-list').focus({preventScroll:true}); $('record-detail').scrollIntoView({block:'start'}); }
    else [...document.querySelectorAll('[data-record]')].find(row => row.dataset.record === selected)?.focus({preventScroll:true});
  });
  $('page-controls').addEventListener('click',event => { const button = event.target.closest('[data-page]'); if (button && !button.disabled) { filters.page = Number(button.dataset.page); writeURL(); loadHistory(true); } });
  function searchInput() {
    clearTimeout(searchTimer);
    filters.search = $('filter-search').value; syncFilters();
    // 输入未提交时也立即取消旧查询，避免旧结果覆盖正在输入的新条件。
    historyController?.abort(); historySequence++;
    if (!composing) searchTimer = setTimeout(applyFilters,300);
  }
  $('filter-search').addEventListener('compositionstart',() => { composing = true; clearTimeout(searchTimer); });
  $('filter-search').addEventListener('compositionend',() => { composing = false; searchInput(); });
  $('filter-search').addEventListener('input',searchInput);
  $('filter-search').addEventListener('keydown',event => { if (event.key === 'Enter' && !event.isComposing && !composing) { event.preventDefault(); applyFilters(); } });
  $('clear-search').addEventListener('click',() => { filters.search = ''; applyFilters(); $('filter-search').focus(); });
  $('btn-clear-filters').addEventListener('click',() => { Object.assign(filters,{...defaults,tab:filters.tab,size:filters.size,sort:filters.sort}); applyFilters(); });
  ['refresh-history','retry-history'].forEach(id => $(id).addEventListener('click',() => { clearTimeout(searchTimer); loadHistory(); }));
  // 事件绑定完成后启用操作，避免脚本未加载时出现无响应按钮。
  document.querySelectorAll('[data-js-action]').forEach(button => { button.disabled = false; });
  readURL(); syncFilters(); switchTab(filters.tab); loadPolicy(); loadHistory(true);
})();
