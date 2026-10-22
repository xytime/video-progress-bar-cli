/* 执行恢复：持久登记、统一状态回读，不提供冷却跳过。2026-10-22 Codex */
window.ManualVideoExecution = (() => {
  const pending = new Set();
  let dialogOpen = false;
  const labels = {WAITING:'等待恢复', RUNNING:'执行中', FINISHED:'已结束', ATTENTION:'需核验'};
  function remaining(seconds) {
    const n = Math.max(0, Math.ceil(seconds));
    return n ? `${Math.floor(n / 60)} 分 ${n % 60} 秒` : '冷却已到期，仍需检查调度条件';
  }
  function requestHtml(request) {
    if (!request) return '';
    const item = document.createElement('div'); item.className = 'execution-request';
    item.textContent = `${labels[request.display_state || request.state] || '状态待核验'} · ${request.message}`;
    return item.outerHTML;
  }
  function confirmWait(result) {
    if (dialogOpen) return Promise.resolve('cancel');
    dialogOpen = true;
    return new Promise(resolve => {
      const previous = document.activeElement;
      const dialog = document.createElement('dialog');
      dialog.id = 'manual-cooldown-confirm'; dialog.className = 'manual-cooldown-dialog';
      dialog.setAttribute('aria-labelledby', 'manual-cooldown-title');
      dialog.innerHTML = `<h2 id="manual-cooldown-title">执行与恢复状态</h2>
        <p data-description></p><ul data-blockers></ul><p data-deadline></p>
        <p>登记后，系统会在维护、账号冷却、调度额度及任务条件全部满足时执行。刷新或关闭页面不会丢失请求。</p>
        <form method="dialog" class="console-confirm-actions"><button value="cancel" autofocus>取消</button>
        <button value="wait">恢复后执行此任务</button></form>`;
      dialog.querySelector('[data-description]').textContent = result.prepared
        ? '成片已就绪，恢复后复用已有产物。' : '恢复后先加工，再由统一调度检查发布条件。';
      for (const reason of result.blockers || [result.cooldown?.reason || '等待执行条件恢复']) {
        const li = document.createElement('li'); li.textContent = reason; dialog.querySelector('ul').append(li);
      }
      const tick = () => { dialog.querySelector('[data-deadline]').textContent = result.cooldown?.active
        ? '账号冷却剩余：' + remaining(result.cooldown.until - Date.now()/1000) + '。到期不代表立即获得执行额度。' : ''; };
      tick(); const timer = setInterval(tick, 1000);
      dialog.addEventListener('close', () => {
        clearInterval(timer); const choice = dialog.returnValue === 'wait' ? 'wait' : 'cancel';
        dialog.remove(); dialogOpen = false; previous?.focus(); resolve(choice);
      }, {once:true});
      document.body.append(dialog); dialog.showModal(); dialog.querySelector('[value="cancel"]').focus();
    });
  }
  async function execute(url) {
    if (pending.has(url)) return {cancelled:true};
    pending.add(url);
    try {
      let response = await fetch(url, {method:'POST', signal:AbortSignal.timeout(20000)});
      let result = await response.json();
      if (['EXECUTION_WAIT', 'WECHAT_COOLDOWN'].includes(result.code)) {
        if (await confirmWait(result) !== 'wait') return {cancelled:true};
        const match = new URL(url, location.origin).pathname.match(/^\/api\/videos\/([^/]+)(?:\/slices\/(\d+))?\/process$/);
        if (!match) throw new Error('无法识别任务，请刷新查看');
        response = await fetch(`/api/execution-recovery/${match[1]}?slice_index=${match[2] || 0}`,
          {method:'POST', signal:AbortSignal.timeout(20000)});
        result = await response.json();
      }
      if (!response.ok || !result.success) {
        const detail = result.error || result.detail;
        throw new Error(typeof detail === 'string' ? detail : detail?.message || '请求未确认，请刷新查看执行状态');
      }
      refresh(); return result;
    } finally { pending.delete(url); }
  }
  async function refresh() {
    const panel = document.getElementById('execution-recovery-panel');
    if (!panel) return;
    const content = panel.querySelector('[data-recovery-content]');
    try {
      const response = await fetch('/api/execution-recovery', {signal:AbortSignal.timeout(15000)});
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (!Array.isArray(data.requests)) throw new Error();
      content.replaceChildren();
      const status = document.createElement('p');
      status.textContent = data.blockers?.length ? data.blockers.join('；') : '全局条件已恢复；任务仍需按序通过发布校验。';
      content.append(status);
      for (const row of data.requests) {
        const item = document.createElement('p'); item.className='execution-request';
        item.textContent = `${row.title || row.youtube_id}${row.slice_index ? ' · 分集 ' + row.slice_index : ''}：${labels[row.display_state || row.state] || '状态未知'} · ${row.message}${row.blockers?.length ? ' · ' + row.blockers.join('；') : ''}`;
        content.append(item);
      }
      if (!data.requests.length) { const empty=document.createElement('p'); empty.textContent='暂无已登记的等待任务'; content.append(empty); }
    } catch (_) { content.textContent='执行状态暂时无法读取，请刷新核验；不要重复启动任务。'; }
  }
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelector('[data-recovery-refresh]')?.addEventListener('click', refresh);
    refresh(); setInterval(() => { if (!document.hidden) refresh(); }, 30000);
  });
  return {execute, remaining, requestHtml, refresh};
})();
