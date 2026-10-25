/*
 * 手动执行共用冷却确认：取消不领取，等待不启动，跳过只授权一次。
 *
 * Modification History
 * | Version | Date | Author | Description |
 * | --- | --- | --- | --- |
 * | 1.1.0 | 2026-10-25 | Codex | 规范错误响应解析，保留冷却确认并安全处理无效响应。 |
 */
window.ManualVideoExecution = (() => {
  const pending = new Set();
  let dialogOpen = false;
  function remaining(seconds) {
    const n = Math.max(0, Math.ceil(seconds));
    return n ? `${Math.floor(n / 60)} 分 ${n % 60} 秒` : '冷却已到期';
  }
  function failureMessage(result, response) {
    const detail = result?.detail;
    const message = result?.error || (typeof detail === 'string' ? detail : detail?.message);
    const code = detail !== null && typeof detail === 'object' && !Array.isArray(detail)
      && typeof detail.code === 'string' ? detail.code : null;
    if (typeof message === 'string' && message) return message + (code ? ` [${code}]` : '');
    if (!response.ok) return `请求失败（HTTP ${response.status}）`;
    if (!result || typeof result !== 'object' || Array.isArray(result)) {
      return '响应格式无效，请刷新查看后再操作';
    }
    return '请求未确认，请刷新查看后再操作';
  }
  function confirmCooldown(result) {
    if (dialogOpen) return Promise.resolve('cancel');
    dialogOpen = true;
    return new Promise(resolve => {
      const previous = document.activeElement;
      const dialog = document.createElement('dialog');
      dialog.id = 'manual-cooldown-confirm';
      dialog.className = 'manual-cooldown-dialog';
      dialog.setAttribute('aria-labelledby', 'manual-cooldown-title');
      dialog.setAttribute('aria-describedby', 'manual-cooldown-description');
      dialog.innerHTML = `<h2 id="manual-cooldown-title">视频号账号准入受阻</h2>
        <p id="manual-cooldown-description"></p><dl><dt>原因</dt><dd data-cooldown-reason></dd>
        <dt>预计可重试</dt><dd data-cooldown-until></dd><dt>剩余时间</dt><dd data-cooldown-remaining aria-live="off"></dd></dl>
        <p>是否跳过本地冷却，立即尝试执行这条视频？平台仍可能拒绝请求。仅对当前视频执行一次，其他任务继续等待。</p>
        <form method="dialog" class="console-confirm-actions">
          <button value="cancel" autofocus>取消</button><button value="wait">等待自动重试</button>
          <button value="force" class="manual-cooldown-force">跳过冷却，执行一次</button>
        </form>`;
      dialog.querySelector('#manual-cooldown-description').textContent = result.prepared
        ? '这条视频已加工完成，正在等待发布，将复用现有成片。'
        : '执行会沿用有效的已有产物；加工完成后将检查发布条件。单次跳过确认在 15 分钟内有效。';
      if (result.error === '冷却状态已变化，请重新确认') {
        dialog.querySelector('#manual-cooldown-description').textContent += ' 冷却状态已变化，请重新确认。';
      }
      const info = result.cooldown;
      dialog.querySelector('[data-cooldown-reason]').textContent = info.reason +
        (info.business_code != null ? `（${info.business_code}）` : '');
      dialog.querySelector('[data-cooldown-until]').textContent = info.until ? new Date(info.until * 1000)
        .toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false}) + '（北京时间）' : '未知，等待排队或其它条件变化';
      const tick = () => { dialog.querySelector('[data-cooldown-remaining]').textContent = info.until ? remaining(info.until - Date.now() / 1000) : '时间未知'; };
      tick();
      const timer = setInterval(tick, 1000);
      dialog.addEventListener('close', () => {
        clearInterval(timer);
        const choice = ['wait', 'force'].includes(dialog.returnValue) ? dialog.returnValue : 'cancel';
        dialog.remove(); dialogOpen = false;
        previous?.focus(); resolve(choice);
      }, {once: true});
      document.body.append(dialog); dialog.showModal();
      dialog.querySelector('[value="cancel"]').focus();
    });
  }
  async function execute(url) {
    if (pending.has(url)) return {cancelled: true};
    pending.add(url);
    try {
      let target = url;
      while (true) {
        const response = await fetch(target, {method: 'POST', signal: AbortSignal.timeout(20000)});
        let result;
        try { result = await response.json(); } catch { result = null; }
        if (result && typeof result === 'object' && !Array.isArray(result)
            && result.code === 'WECHAT_COOLDOWN' && result.cooldown) {
          const choice = await confirmCooldown(result);
          if (choice === 'cancel') return {cancelled: true};
          const next = new URL(url, location.origin);
          next.searchParams.set('cooldown_action', choice);
          next.searchParams.set('cooldown_version', result.cooldown.version);
          target = next.pathname + next.search;
          continue;
        }
        if (!response.ok || !result || typeof result !== 'object' || Array.isArray(result)
            || result.success !== true) {
          throw new Error(failureMessage(result, response));
        }
        return result;
      }
    } finally { pending.delete(url); }
  }
  return {execute, remaining};
})();
