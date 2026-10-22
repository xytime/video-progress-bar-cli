/* 高互动列表：只呈现服务端动作，提交时携带版本；浏览标记与生产状态独立。 */
window.EngagementRows = (() => {
  const pending = new Set();
  const esc = value => escapeHtml(String(value ?? ''));
  const attr = value => escapeAttr(String(value ?? ''));
  function state(v) {
    const e = v.engagement || {label:'状态待核实', reason:'请刷新页面读取最新状态', tone:'muted'};
    return `<div class="engagement-state">
      <span class="engagement-label engagement-${attr(e.tone)}">${esc(e.label)}</span>
      <p class="engagement-reason">${esc(e.reason)}</p></div>`;
  }
  function actions(v) {
    const e = v.engagement || {};
    let html = '';
    if (e.action) {
      html += `<button type="button" class="engagement-action" data-engagement-action="${attr(e.action)}"
        data-yid="${attr(v.youtube_id)}" ${pending.has(v.youtube_id) ? 'disabled' : ''}>${esc(e.action_label)}</button>`;
    }
    if (v.prepared_video_url) {
      html += `<a class="engagement-link" target="_blank" rel="noopener" href="${attr(v.prepared_video_url)}">查看成片</a>`;
    }
    if (e.stage === 'ENG_SEGMENTED') {
      html += `<button type="button" class="engagement-link" data-engagement-action="slices" data-yid="${attr(v.youtube_id)}">查看分集</button>`;
    }
    html += `<button type="button" class="engagement-link" data-engagement-action="details"
      data-yid="${attr(v.youtube_id)}">查看详情</button>`;
    if (e.stage === 'ENG_LOGIN') {
      html += '<a class="engagement-link" href="/?view=operations&tab=channels">前往登录</a>';
    }
    return html;
  }
  async function execute(button) {
    const yid = button.dataset.yid;
    const action = button.dataset.engagementAction;
    const v = _currentVideosMap[yid];
    if (!v || pending.has(yid)) return;
    if (action === 'slices') {
      await toggleSlices({stopPropagation() {}, currentTarget: button}, yid);
      button.textContent = button.classList.contains('expanded') ? '收起分集' : '查看分集';
      return;
    }
    if (action === 'details') {
      const dialog = document.createElement('dialog');
      dialog.className = 'engagement-dialog';
      dialog.setAttribute('aria-label', '视频处理详情');
      dialog.innerHTML = `<h2>${esc(v.display_title || v.title || yid)}</h2>${state(v)}
        <p>评分：${esc(v.score ?? '未记录')} · 来源：${esc(v.source || '未知')}</p>
        <p>成片：${v.preparation_ready ? '记录为已就绪' : '未记录完整就绪产物'}</p>
        <p>记录更新时间：${esc(v.updated_at || '未知')}（UTC）</p>
        ${renderPlatformBadges(v)}
        <h3>原始状态与原因</h3><pre>${esc(v.status)}\n${esc(v.error_msg || '没有错误记录')}</pre>
        <p class="engagement-help">浏览标记不代表加工完成；平台受理不代表已公开发布。</p>
        <form method="dialog"><button class="engagement-link">关闭</button></form>`;
      document.body.append(dialog);
      dialog.addEventListener('close', () => { dialog.remove(); button.focus(); }, {once:true});
      dialog.showModal(); return;
    }
    const e = v.engagement;
    if (!e || e.action !== action || !e.version) {
      showToast('状态已变化，请刷新列表', 'error'); return;
    }
    if (action === 'bypass-censor') {
      openBypassModal(yid, 0, e.version); return;
    }
    const consequences = action === 'promote'
      ? '将转为手动任务，评分设为 100 并锁定，随后开始处理。'
      : action === 'retry' && Number(v.score) < 75
        ? '恢复为待筛选；当前低于 75 分，本次不会立即启动。'
        : '将启动处理并沿用有效的已有产物。';
    if (!confirm(`${e.action_label}：${v.display_title || v.title || yid}\n\n${consequences}\n后续沿用现有审核与发布流程，符合条件后可能自动发布。`)) return;
    const originalText = button.textContent;
    let cancelled = false;
    pending.add(yid); button.disabled = true;
    button.textContent = '正在提交…';
    try {
      const url = `/api/videos/${encodeURIComponent(yid)}/${action}?engagement_version=${encodeURIComponent(e.version)}`;
      if (action === 'process') {
        const result = await window.ManualVideoExecution.execute(url);
        if (result.cancelled) { cancelled = true; return; }
        showToast(result.message || '操作已受理，请查看最新状态');
        return;
      }
      const response = await fetch(url,
        {method:'POST'});
      const result = await response.json();
      if (!response.ok || !result.success) {
        const detail = result.error || result.detail;
        throw new Error(typeof detail === 'string' ? detail : detail?.message || '操作未完成');
      }
      showToast(result.message || '操作已受理，请查看最新状态');
    } catch (error) {
      showToast(error.message || '请求未确认，请刷新查看；不要重复提交', 'error');
    } finally {
      pending.delete(yid);
      if (cancelled) {
        button.disabled = false; button.textContent = originalText; button.focus();
        return;
      }
      // 列表读取失败时也不能把旧按钮重新启用。
      button.textContent = '请刷新确认状态';
      await loadVideos();
      fetchStats();
    }
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-engagement-action]');
    if (button && !button.disabled) execute(button);
  });
  return {state, actions};
})();
