/** 入库诊断状态与只读请求控制器；纯展示依赖 FunnelDiagnosisView。
 * Modification History:
 * | 1.1.0 | 2026-10-29 | Codex | URL范围、失败保留快照、原生详情和安全事件委托。 |
 */
(() => {
  'use strict';
  const view = window.FunnelDiagnosisView;
  let mount = null, _funnelDiagnosisRequestId = 0, cached = null, controller = null;
  let overviewGeneration = 0, overviewSnapshot = null, initialized = false, detailGeneration = 0;
  let channelsLoaded = false, channelsLoading = false;
  let dialog = null, detailData = null, detailOpener = null, detailController = null;
  const state = {window:'today_bj',channel:'',pill:null,category:'ALL',cause:null,expanded:null,error:null,loading:false,snapshotScope:null,channels:[],channelsError:false};
  const scope = () => ({window:state.window,channel:state.channel});
  function restore(params) {
    state.window = Object.hasOwn(view.WINDOWS,params.get('created_window')) ? params.get('created_window') : 'today_bj';
    state.channel = params.get('channel') || '';
    state.pill = ['all_affected','unresolved','uncertain_delivery','stalled','recovered'].includes(params.get('diagnosis')) ? params.get('diagnosis') : null;
    state.category = ['ALL','SYSTEM','POLICY'].includes(params.get('category')) ? params.get('category') : 'ALL';
    state.cause = params.get('cause') || null;
    const task = Number(params.get('task'));
    state.expanded = Number.isSafeInteger(task) && task > 0 ? task : null;
    syncScope();
  }
  function persist(replace = false) {
    if (window.DashboardWorkspace?.view() !== 'health') return;
    const params = new URLSearchParams({view:'health',created_window:state.window});
    if (state.channel) params.set('channel',state.channel);
    if (state.pill) params.set('diagnosis',state.pill);
    if (state.category !== 'ALL') params.set('category',state.category);
    if (state.cause) params.set('cause',state.cause);
    if (state.expanded) params.set('task',String(state.expanded));
    const url = '/?' + params.toString();
    if (location.pathname + location.search !== url) history[replace ? 'replaceState' : 'pushState'](null,'',url);
  }
  function syncScope() {
    document.querySelectorAll('#global-funnel-tabs button').forEach(button => {
      const active = button.id === 'gf-tab-' + state.window;
      button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));
    });
  }
  function render() {
    if (!mount) mount = document.getElementById('funnel-diagnosis-mount');
    if (!mount || (document.querySelector('dialog[open]') && mount.children.length)) return;
    const focused = mount.contains(document.activeElement) ? document.activeElement.id : null;
    mount.setAttribute('aria-busy',String(state.loading));
    mount.innerHTML = view.render(cached,state);
    if (focused) document.getElementById(focused)?.focus({preventScroll:true});
    const status = document.getElementById('funnel-diagnosis-status');
    if (status) status.textContent = state.loading ? '正在读取诊断' : state.error ? '诊断读取失败，当前状态未知' : '诊断已更新';
  }
  async function readJSON(url, signal) {
    const response = await fetch(url,{cache:'no-store',signal});
    const data = await response.json();
    if (!response.ok) throw new Error(data?.detail?.message || `HTTP ${response.status}`);
    if (!data?.success) throw new Error('诊断响应无效');
    return data;
  }
  async function load(win = state.window, channel = state.channel) {
    if (window.DashboardWorkspace?.view() === 'health' && !channelsLoaded && !channelsLoading) loadChannels();
    if (Object.hasOwn(view.WINDOWS,win)) state.window = win;
    state.channel = channel || '';syncScope();
    const requested = scope(), request = ++_funnelDiagnosisRequestId;
    window._funnelDiagnosisRequestId = request;
    controller?.abort();controller = new AbortController();
    const activeController = controller, timer = setTimeout(() => activeController.abort(),15000);
    state.loading = true;render();
    try {
      const params = new URLSearchParams(requested);
      const data = await readJSON('/api/funnel/diagnosis?' + params,activeController.signal);
      if (request !== _funnelDiagnosisRequestId) return;
      if (!data.summary || !Array.isArray(data.tasks) || !Array.isArray(data.causes)) throw new Error('诊断数据不完整');
      cached = data;state.snapshotScope = requested;state.error = null;
      validateCause();persist(true);
    } catch (error) {
      if (request === _funnelDiagnosisRequestId) state.error = error.name === 'AbortError' ? '请求超时，请重新读取' : error.message;
    } finally {
      clearTimeout(timer);
      if (request === _funnelDiagnosisRequestId) {state.loading = false;render();}
    }
  }
  function validateCause() {
    if (state.cause && !cached?.tasks.some(task => task.cause_code === state.cause && view.matches(task,state,false))) state.cause = null;
  }
  function changeScope(win, channel = state.channel) {
    state.window = win;state.channel = channel;state.expanded = null;state.cause = null;
    persist();syncScope();
    if (window.DashboardLegacy?.funnel) window.DashboardLegacy.funnel();
    else load();
  }
  function updateFilter(action, value) {
    if (action === 'pill') state.pill = state.pill === value ? null : value;
    if (action === 'category') state.category = value;
    if (action === 'cause') state.cause = state.cause === value || !value ? null : value;
    if (action === 'toggle') state.expanded = state.expanded === Number(value) ? null : Number(value);
    if (action === 'clear') {state.pill = null;state.category = 'ALL';state.cause = null;state.expanded = null;}
    validateCause();persist();render();
    if (action === 'cause' && state.cause && matchMedia('(max-width: 760px)').matches) document.getElementById('funnel-task-heading')?.focus();
  }
  function findTask(id) {
    if (detailData?.video_id === Number(id)) return {...detailData,...detailData.diagnosis,...detailData.evidence};
    return cached?.tasks.find(task => task.video_id === Number(id));
  }
  function openReceipt(id) {
    const task = findTask(id);
    if (!task) return;
    if (typeof window.OperationReceipts?.open === 'function') {
      window.OperationReceipts.open(task.youtube_id,Number(task.slice_index) || 0);
      const title = document.getElementById('operation-receipt-title');
      if (title) title.textContent = `发布回执核对 · #${task.video_id} · 分集 ${Number(task.slice_index) || 0} · ${task.youtube_id}`;
      return;
    }
    openDetails(id);
  }
  async function copyError(button) {
    const text = button.closest('.funnel-diag-error-box')?.querySelector('code')?.textContent;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);button.textContent = '已复制';
    } catch (_) {button.textContent = '复制未成功，请手动选择错误文本';}
  }
  function handleClick(event) {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const {action,value} = button.dataset;
    if (action === 'refresh') {load();if (state.channelsError) loadChannels();}
    else if (action === 'details') openDetails(value);
    else if (action === 'receipt') openReceipt(value);
    else if (action === 'copy') copyError(button);
    else updateFilter(action,value);
  }
  function ensureDialog() {
    if (dialog) return;
    dialog = document.createElement('dialog');dialog.id = 'funnel-task-dialog';
    dialog.setAttribute('aria-labelledby','funnel-detail-title');
    dialog.innerHTML = '<h2 id="funnel-detail-title">任务详情</h2><div id="funnel-detail-content" role="status" aria-live="polite"></div><div class="funnel-diag-guarded-actions"><button type="button" id="funnel-detail-reload">重新核实此任务</button><button type="button" id="funnel-detail-close">关闭详情</button></div>';
    document.body.append(dialog);dialog.addEventListener('click',handleClick);
    document.getElementById('funnel-detail-close').addEventListener('click',() => dialog.close());
    document.getElementById('funnel-detail-reload').addEventListener('click',() => readDetails(dialog.dataset.task));
    dialog.addEventListener('close',() => {detailGeneration++;detailController?.abort();detailOpener?.focus({preventScroll:true});});
  }
  function openDetails(id) {
    if (!Number.isSafeInteger(Number(id)) || Number(id) < 1) return;
    ensureDialog();detailOpener = document.activeElement;dialog.dataset.task = id;
    document.getElementById('funnel-detail-title').textContent = `任务详情 · #${id}`;
    if (!dialog.open) dialog.showModal();
    document.getElementById('funnel-detail-close').focus();readDetails(id);
  }
  async function readDetails(id) {
    const request = ++detailGeneration, content = document.getElementById('funnel-detail-content');
    detailController?.abort();detailController = new AbortController();
    const activeController = detailController, timer = setTimeout(() => activeController.abort(),15000);
    content.textContent = `正在重新核实任务 #${id} 的最新状态与证据…`;
    try {
      const result = await readJSON(`/api/funnel/tasks/${Number(id)}/evidence`,activeController.signal);
      if (request !== detailGeneration) return;
      if (Number(result.data?.video_id) !== Number(id)) throw new Error('任务身份不匹配');
      detailData = result.data;content.innerHTML = view.detail(detailData);
    } catch (error) {
      if (request === detailGeneration) content.textContent = `任务 #${id} 详情读取失败，状态尚未核实：${error.message}。可重新读取。`;
    } finally {clearTimeout(timer);}
  }
  async function loadOverview() {
    const element = document.getElementById('overview-health-summary');
    if (!element) return;
    const request = ++overviewGeneration, abort = new AbortController(), timer = setTimeout(() => abort.abort(),15000);
    try {
      const data = await readJSON('/api/funnel/diagnosis?window=today_bj',abort.signal);
      if (request !== overviewGeneration) return;
      const summary = data.summary;
      if (!summary || !Number.isInteger(summary.total_ingested)) throw new Error('数据不完整');
      overviewSnapshot = data;
      element.textContent = `${summary.total_ingested} 入库 · ${summary.unresolved_tasks ?? 0} 未解决 · ${summary.uncertain_delivery_tasks ?? 0} 投递待核 · ${summary.recovered_pending_delivery ?? 0} 恢复待交付 · 观测 ${data.as_of_bj || '时效未知'}（北京时间，全频道）`;
    } catch (_) {
      if (request === overviewGeneration) element.textContent = `今日健康度不可用，状态未知。${overviewSnapshot ? '上次成功观测 ' + overviewSnapshot.as_of_bj + '（北京时间），已过期。' : '暂无可信读数。'}`;
    } finally {clearTimeout(timer);}
  }
  async function loadChannels() {
    if (window.DashboardWorkspace?.view() !== 'health' || channelsLoading) return;
    channelsLoading = true;
    try {
      const response = await fetch('/api/channels',{cache:'no-store',signal:AbortSignal.timeout(15000)});
      const data = await response.json();
      if (!response.ok || !Array.isArray(data.channels || data.approved)) throw new Error('频道选项无效');
      state.channels = data.channels || data.approved;state.channelsError = false;channelsLoaded = true;
    } catch (_) {state.channelsError = true;}
    finally {channelsLoading = false;}
    if (window.DashboardWorkspace?.view() === 'health') render();
  }
  function init() {
    if (initialized) return;
    mount = document.getElementById('funnel-diagnosis-mount');if (!mount) return;
    initialized = true;mount.addEventListener('click',handleClick);
    document.addEventListener('close',() => queueMicrotask(render),true);
    mount.addEventListener('change',event => {
      if (event.target.id === 'funnel-window') changeScope(event.target.value);
      if (event.target.id === 'funnel-channel') changeScope(state.window,event.target.value);
    });
    const channelSelect = document.getElementById('video-filter-channel');
    if (channelSelect) new MutationObserver(() => {if (window.DashboardWorkspace?.view() === 'health') render();}).observe(channelSelect,{childList:true});
    if (window.DashboardWorkspace?.view() === 'health' && !cached && !state.loading) load();
  }
  restore(new URLSearchParams(location.search));
  window.FunnelDiagnosis = {init,load,scope,restore,persist,loadOverview,changeScope,refresh:() => load(),getRequestId:() => _funnelDiagnosisRequestId,
    onPillClick:key => updateFilter('pill',key),onCategoryClick:key => updateFilter('category',key),onCauseClick:key => updateFilter('cause',key),toggleTask:id => updateFilter('toggle',id),locateTask:openDetails,openDetails};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',init);else init();
})();
