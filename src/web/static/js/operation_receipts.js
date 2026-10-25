/* 授权与认证回执的唯一展示入口；读取回执不会恢复任务或投稿。
 * Modification History: 2026-10-25 Codex 初版：持久反馈、状态时效、原生对话框与焦点返回。
 */
(() => {
  'use strict';
  let opener = null, generation = 0;
  const dialog = document.createElement('dialog');
  dialog.id = 'operation-receipt-dialog';
  dialog.setAttribute('aria-labelledby', 'operation-receipt-title');
  dialog.innerHTML = '<h2 id="operation-receipt-title">操作回执</h2><div id="operation-receipt-content" role="status" aria-live="polite"></div><div class="operation-receipt-actions"><button class="btn" id="operation-receipt-reload">重新读取</button><button class="btn" id="operation-receipt-close" autofocus>关闭</button></div>';
  document.body.append(dialog);
  const body = dialog.querySelector('#operation-receipt-content');
  const reload = dialog.querySelector('#operation-receipt-reload');
  dialog.querySelector('#operation-receipt-close').onclick = () => dialog.close();
  dialog.addEventListener('close', () => { generation++; opener?.focus(); });
  const time = value => value ? new Date(typeof value === 'number' ? value * 1000 : value).toLocaleString('zh-CN') : '无检查记录';
  const approvalTime = value => {
    if (!value) return '原审计未记录';
    const date = new Date(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value) ? value.replace(' ', 'T') + 'Z' : value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false}) + '（北京时间）';
  };
  function show(title, action) {
    opener = document.activeElement;
    dialog.querySelector('h2').textContent = title;
    body.textContent = '正在读取…'; reload.disabled = false; reload.onclick = action;
    if (!dialog.open) dialog.showModal();
    dialog.querySelector('#operation-receipt-close').focus();
    action();
  }
  async function readJSON(url, options = {}) {
    const response = await fetch(url, {cache:'no-store', signal:AbortSignal.timeout(40000), ...options});
    const data = await response.json();
    if (!response.ok) throw new Error(`HTTP ${response.status}，${typeof data.detail === 'string' ? data.detail : '请求未通过'}`);
    return data;
  }
  function receiptText(receipt) {
    const approval = receipt?.approval;
    if (!approval || receipt.state !== 'SAVED') return `当前授权未确认保存（${receipt?.state || 'UNKNOWN'}）。请核对原审计后操作。`;
    return `授权已保存 · 回执 #${approval.id}\n任务 #${receipt.video_id} · ${receipt.youtube_id} · 分集 ${receipt.slice_index}\n保存时间：${approvalTime(approval.created_at)}\n审批范围：${approval.level} · ${approval.review_stage || '原审查阶段'} · ${approval.platform || '原平台'}\n输入指纹：${approval.input_hash || '原审计未记录'}\n规则版本：${approval.rule_pack_version || '原审计未记录'}\n当前任务状态：${receipt.task_status}\n回执只证明该任务的人工授权已保存，后续加工与平台投稿各自确认。`;
  }
  window.OperationReceipts = {
    read: (id, slice = 0) => readJSON(`/api/videos/${encodeURIComponent(id)}/operation-receipts?slice_index=${slice}`),
    text: receiptText,
    open(id, slice = 0) {
      show('授权回执与投稿确认', async () => {
        const current = ++generation; reload.disabled = true;
        try {
          const result = await this.read(id, slice);
          if (current !== generation) return;
          body.textContent = receiptText(result.receipt) + '\n\n视频号：' + (result.submission?.label || result.wechat_state || '暂无投稿记录')
            + (result.submission ? '\n' + result.submission.message : '');
        } catch (error) {
          if (current === generation) body.textContent = `回执读取失败：${error.message}。结果尚未核实，请勿重复授权或投稿。`;
        } finally { if (current === generation) reload.disabled = false; }
      });
    },
  };
  const authButton = document.getElementById('cover-auth-status');
  const authNames = {READY:'封面服务已登录', AUTH_REQUIRED:'封面服务需要登录', UNKNOWN:'封面登录待核实'};
  function authText(state) {
    return `${authNames[state.status] || authNames.UNKNOWN}\n最近检查：${time(state.checked_at)}${state.fresh ? '' : '（已过期或暂无有效记录）'}\n`
      + (state.status === 'READY' ? '本次认证检查通过。生成封面时仍会重新核验权限。'
        : state.status === 'AUTH_REQUIRED' ? '认证检查确认需要手动登录 AGY；完成登录后点“核实登录状态”。'
        : '当前证据不足或检查失败，不能据此认定未登录。请核实登录状态。')
      + '\n此检查不生成封面，也不会打开登录授权页。';
  }
  async function refreshAuth() {
    try {
      const state = await readJSON('/api/cover-service/auth');
      authButton.textContent = authNames[state.status] || authNames.UNKNOWN;
      authButton.title = authText(state);
      return state;
    } catch { authButton.textContent = authNames.UNKNOWN; return null; }
  }
  window.OperationReceipts.openAuth = () => {
    show('封面服务登录状态', async () => {
      const current = ++generation; reload.disabled = true;
      body.textContent = '正在检查 AGY 认证，请稍候…';
      try {
        const state = await readJSON('/api/cover-service/auth/recheck', {method:'POST'});
        if (current !== generation) return;
        body.textContent = authText(state);
        authButton.textContent = authNames[state.status] || authNames.UNKNOWN;
        authButton.title = authText(state);
      } catch (error) { if (current === generation) body.textContent = `检查未完成：${error.message}。登录状态待核实。`; }
      finally { if (current === generation) reload.disabled = false; }
    });
    reload.textContent = '核实登录状态';
  };
  dialog.addEventListener('close', () => { reload.textContent = '重新读取'; });
  refreshAuth();
  setInterval(refreshAuth, 60000);
})();
