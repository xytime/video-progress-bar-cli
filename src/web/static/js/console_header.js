/** 2026-10-20 Codex：全局操作、只读状态、维护闭锁与完整流水线确认。 */
(() => {
  const $ = id => document.getElementById(id);
  const controls = ['btn-scan-channels', 'btn-scan-engagement', 'btn-refresh-high-likes', 'btn-wechat-login', 'btn-run-pipeline', 'header-pipeline-submit'];
  let runtime = null, wechat = null, pending = false, busy = '', generation = 0;
  const scans = {channels: false, engagement: false};
  const feedback = message => { $('header-operation-feedback').textContent = message; };
  async function json(url, options) {
    const response = await fetch(url, {...options, signal: AbortSignal.timeout(12000)});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.message || `请求失败（${response.status}）`);
    return data;
  }
  function paint() {
    const running = runtime?.state === 'RUNNING';
    $('header-runtime-state').textContent = running ? '正常运行' : runtime?.state === 'MAINTENANCE' ? '维护中' : '运行状态未核实';
    $('header-runtime-state').dataset.state = runtime?.state || 'UNKNOWN';
    $('header-wechat-state').textContent = !wechat ? '微信状态未核实' : wechat.login_flow_active ? '微信：登录进行中' : `微信：${wechat.status_label || '状态未知'}`;
    controls.forEach(id => {
      const element = $(id); if (!element) return;
      const scan = id === 'btn-scan-channels' ? scans.channels : ['btn-scan-engagement', 'btn-refresh-high-likes'].includes(id) ? scans.engagement : false;
      element.disabled = !running || pending || Boolean(busy) || scan || (id === 'btn-wechat-login' && (!wechat || wechat.login_flow_active));
      element.title = !running ? '维护或状态未核实，暂不能执行' : scan ? '同类扫描正在进行，请勿重复提交' : id === 'btn-wechat-login' && wechat?.login_flow_active ? '已有登录流程，请勿重复启动' : '';
      element.setAttribute('aria-describedby', 'header-operation-feedback');
    });
    $('btn-scan-channels').textContent = scans.channels ? '频道扫描中…' : '扫描白名单频道';
    $('btn-scan-engagement').textContent = scans.engagement ? '高互动素材刷新中…' : '刷新高互动素材';
    const legacy = $('btn-refresh-high-likes');
    if (legacy) legacy.textContent = scans.engagement ? '高互动素材刷新中…' : '刷新高互动素材';
    if (!running && $('header-pipeline-confirm').open) $('header-pipeline-confirm').close();
  }
  async function refresh({quiet = false} = {}) {
    const token = ++generation;
    if (!quiet) { pending = true; paint(); }
    const results = await Promise.allSettled([
      json('/api/console/header'), json('/api/wechat/status'), json('/api/high-likes/status'),
    ]);
    if (token !== generation) return false;
    const [state, login, engagement] = results;
    runtime = state.status === 'fulfilled' && ['RUNNING', 'MAINTENANCE'].includes(state.value.state) && typeof state.value.channel_scan?.running === 'boolean' ? state.value : null;
    wechat = login.status === 'fulfilled' && typeof login.value.login_flow_active === 'boolean' && typeof login.value.status_label === 'string' ? login.value : null;
    const oldScans = {...scans};
    scans.channels = runtime?.channel_scan.running ?? true;
    scans.engagement = engagement.status === 'fulfilled' && typeof engagement.value.running === 'boolean' ? engagement.value.running : true;
    pending = false; paint();
    $('header-status-retry').hidden = Boolean(runtime && wechat && engagement.status === 'fulfilled');
    if (!runtime) feedback('运行状态读取失败，操作已暂停；请重新核实状态。');
    else if (runtime.state === 'MAINTENANCE') feedback('维护中：扫描、登录、加工与发布已暂停。' + (runtime.reason ? ` ${runtime.reason}` : ''));
    else if (!wechat) feedback('微信状态读取失败，扫码登录暂不可用；请重新核实状态。');
    else if (scans.channels || scans.engagement) feedback('扫描任务进行中；同类入口已禁用，页面会自动读取状态。');
    else if (oldScans.channels && runtime.channel_scan.outcome === 'error') feedback('频道扫描失败，请查看频道访问结果及扫描日志后重试。');
    else if (oldScans.channels && runtime.channel_scan.outcome === 'complete') feedback('频道扫描已完成，请在频道白名单核对采集结果。');
    else if (oldScans.engagement) { feedback('高互动刷新任务已结束，请核对素材列表；结束状态不代表全部来源采集成功。'); window.loadVideos?.(); }
    else if (!quiet) feedback('扫描仅采集素材；运行完整流水线可能继续加工和发布。');
    return runtime?.state === 'RUNNING';
  }
  async function allow(kind) {
    if (busy || pending) return false;
    if (!await refresh()) return false;
    if (kind === 'login' && (!wechat || wechat.login_flow_active)) return false;
    if (kind in scans && scans[kind]) return false;
    return true;
  }
  async function scan(kind) {
    if (!['channels', 'engagement'].includes(kind) || !await allow(kind)) return;
    busy = kind; paint();
    try {
      const data = await json(kind === 'channels' ? '/api/console/scan-channels' : '/api/high-likes/refresh', {method: 'POST'});
      if (data.started !== true) throw new Error(data.message || '扫描未启动，请重新核实状态');
      scans[kind] = true; feedback(data.message || '扫描已启动，请等待结果。');
    } catch (error) { feedback(error.message); }
    finally { busy = ''; paint(); }
  }
  const dialog = $('header-pipeline-confirm');
  let confirmOpener = null;
  function confirmPipeline() {
    // 只打开确认层，不预先提交；维护态仍须由 allow 重新读取后拒绝。
    return allow('pipeline').then(allowed => {
      if (!allowed) return;
      confirmOpener = document.activeElement;
      dialog.showModal(); $('header-pipeline-cancel').focus();
    });
  }
  dialog.addEventListener('close', () => confirmOpener?.focus());
  $('header-pipeline-submit').onclick = async () => {
    if (!await allow('pipeline')) return;
    busy = 'pipeline'; paint(); dialog.close();
    try {
      const data = await json('/api/pipeline/run', {method: 'POST'});
      if (!data.success) throw new Error(data.message || '流水线未启动');
      feedback('完整流水线请求已受理，请在生产队列核对实际进度。');
    } catch (error) { feedback(error.message); }
    finally { busy = ''; paint(); }
  };
  $('btn-scan-channels').onclick = () => scan('channels');
  $('btn-scan-engagement').onclick = () => scan('engagement');
  const menus = [...document.querySelectorAll('.console-header-menu')];
  menus.forEach(menu => menu.addEventListener('toggle', () => {
    if (menu.open) {
      menus.filter(other => other !== menu).forEach(other => { other.open = false; });
      if (menu.id === 'header-more-menu') window.fetchAiAuditSummary?.();
    }
  }));
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || dialog.open) return;
    menus.filter(menu => menu.open).forEach(menu => { menu.open = false; menu.querySelector('summary').focus(); });
  });
  document.addEventListener('click', event => menus.forEach(menu => {
    if (menu.open && !menu.contains(event.target)) menu.open = false;
  }));
  window.ConsoleHeader = {refresh, allow, scan, confirmPipeline};
  refresh();
  setInterval(() => { if (!document.hidden && !busy && !pending) refresh({quiet: true}); }, 15000);
})();
