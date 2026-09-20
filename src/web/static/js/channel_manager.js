/**
 * Video Pipeline Dashboard - Channel Management & Funnel Popover
 * Decoupled from index.html into static/js/channel_manager.js
 */

(() => {
  // Defensive fallbacks for shared utility functions
  const _escapeHtml = (str) =>
    (typeof window.escapeHtml === 'function')
      ? window.escapeHtml(str)
      : String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

  const _escapeAttr = (str) => {
    const s = str == null ? '' : str;
    return (typeof window.escapeAttr === 'function')
      ? window.escapeAttr(s)
      : String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  };

  const _statusBadge = (state) =>
    (typeof window.statusBadge === 'function')
      ? window.statusBadge(state)
      : `<span class="badge ${state === 'PAUSED' ? 'badge-PAUSED' : 'badge-PUBLISHED'}">${state === 'PAUSED' ? '已暂停' : '监控中'}</span>`;

  const _showToast = (msg, type) => {
    if (typeof window.showToast === 'function') {
      window.showToast(msg, type);
    } else {
      console.log(`[Toast ${type || 'info'}] ${msg}`);
    }
  };

  const _relativeTime = (ts) =>
    (typeof window.relativeTime === 'function') ? window.relativeTime(ts) : (ts || '—');

  const escapeHtml = _escapeHtml;
  const escapeAttr = _escapeAttr;
  const statusBadge = _statusBadge;
  const showToast = _showToast;
  const relativeTime = _relativeTime;

  // ── 频道白名单与漏斗管理状态 ──
  let _funnelState = {
    channelId: null,
    channelName: null,
    window: '7d',
    isPinned: false,
    cache: {},
    timer: null,
    activeTrigger: null,
  };

  async function fetchChannels() {
    try {
      const r = await fetch('/api/channels');
      const d = await r.json();
      const channels = d.channels || d.approved || [];
      const countEl = document.getElementById('channel-count');
      if (countEl) countEl.textContent = d.total_managed != null ? d.total_managed : (d.total_approved || 0);

      const subcountsEl = document.getElementById('channel-subcounts');
      if (subcountsEl) {
        subcountsEl.textContent = `(监控中 ${d.total_approved || 0} · 已暂停 ${d.total_paused || 0})`;
      }

      const list = document.getElementById('channel-list');
      if (!channels || channels.length === 0) {
        list.innerHTML = '<div class="empty-state"><div class="empty-icon">📻</div>暂无受管频道，请在下方添加</div>';
        return;
      }
      list.innerHTML = channels.map(c => {
        const isPaused = c.status === 'PAUSED';
        const safeId = _escapeAttr(c.channel_id);
        const safeName = _escapeHtml(c.channel_name);
        const attrName = _escapeAttr(c.channel_name);
        const pauseBtn = isPaused
          ? `<button class="btn-channel-action btn-channel-resume" data-channel-id="${safeId}" onclick="toggleChannelPause(this.dataset.channelId, false)">▶ 恢复</button>`
          : `<button class="btn-channel-action btn-channel-pause" data-channel-id="${safeId}" onclick="toggleChannelPause(this.dataset.channelId, true)">⏸ 暂停</button>`;

        return `
          <div class="channel-item ${isPaused ? 'is-paused' : ''}" id="channel-item-${safeId}">
            <div class="channel-item-header">
              <div class="channel-name" title="${attrName}">${safeName}</div>
              <div class="channel-header-badge">${_statusBadge(c.status)}</div>
            </div>
            <div class="channel-item-footer">
              <div class="channel-id" title="${safeId}">${_escapeHtml(c.channel_id)}</div>
              <div class="channel-actions">
                <button class="btn-channel-funnel" 
                        id="btn-funnel-${safeId}"
                        data-channel-id="${safeId}"
                        data-channel-name="${attrName}"
                        onclick="toggleFunnelPopover(event, this.dataset.channelId, this.dataset.channelName)"
                        onmouseenter="showFunnelPreview(event, this.dataset.channelId, this.dataset.channelName)"
                        onmouseleave="scheduleFunnelHide()">
                  📊 漏斗
                </button>
                ${pauseBtn}
                <button class="btn-delete"
                        data-channel-id="${safeId}"
                        data-channel-name="${attrName}"
                        onclick="deleteChannel(this.dataset.channelId, this.dataset.channelName)">删除</button>
              </div>
            </div>
          </div>
        `;
      }).join('');
    } catch(e) { console.warn('channels fetch error', e); }
  }

  async function toggleChannelPause(channelId, pause) {
    if (channelId && typeof channelId === 'object' && channelId.dataset) {
      channelId = channelId.dataset.channelId;
    }
    if (navigator.vibrate) navigator.vibrate(10);
    const action = pause ? 'pause' : 'resume';
    try {
      const r = await fetch(`/api/channels/${encodeURIComponent(channelId)}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const d = await r.json();
      if (d.success) {
        _showToast(pause ? '⏸ 频道已暂停自动抓取轮询' : '🟢 频道已恢复自动抓取监控');
        await fetchChannels();
      } else {
        _showToast(d.error || '操作失败', 'error');
      }
    } catch(e) {
      _showToast('网络请求失败', 'error');
    }
  }

  function showFunnelPreview(event, channelId, channelName) {
    const trigger = (event && event.currentTarget) ? event.currentTarget : (event && event.dataset ? event : null);
    if (channelId && typeof channelId === 'object' && channelId.dataset) {
      channelName = channelId.dataset.channelName;
      channelId = channelId.dataset.channelId;
    }
    channelId = channelId || (trigger && trigger.dataset ? trigger.dataset.channelId : null);
    channelName = channelName || (trigger && trigger.dataset ? trigger.dataset.channelName : null);
    if (_funnelState.isPinned && _funnelState.channelId === channelId) return;
    if (_funnelState.timer) { clearTimeout(_funnelState.timer); _funnelState.timer = null; }
    _funnelState.channelId = channelId;
    _funnelState.channelName = channelName;
    _funnelState.activeTrigger = trigger;
    _openFunnelPopover(trigger, false);
  }

  function toggleFunnelPopover(event, channelId, channelName) {
    if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
    if (_funnelState.timer) { clearTimeout(_funnelState.timer); _funnelState.timer = null; }
    const trigger = (event && event.currentTarget) ? event.currentTarget : (event && event.dataset ? event : null);
    if (channelId && typeof channelId === 'object' && channelId.dataset) {
      channelName = channelId.dataset.channelName;
      channelId = channelId.dataset.channelId;
    }
    channelId = channelId || (trigger && trigger.dataset ? trigger.dataset.channelId : null);
    channelName = channelName || (trigger && trigger.dataset ? trigger.dataset.channelName : null);
    const pop = document.getElementById('channel-funnel-popover');
    if (pop && pop.style.display === 'block' && _funnelState.channelId === channelId && _funnelState.isPinned) {
      closeFunnelPopover();
      return;
    }
    _funnelState.channelId = channelId;
    _funnelState.channelName = channelName;
    _funnelState.isPinned = true;
    _funnelState.activeTrigger = trigger;
    _openFunnelPopover(trigger, true);
  }

  function scheduleFunnelHide() {
    if (_funnelState.isPinned) return;
    _funnelState.timer = setTimeout(() => {
      closeFunnelPopover();
    }, 240);
  }

  function closeFunnelPopover() {
    const pop = document.getElementById('channel-funnel-popover');
    if (pop) pop.style.display = 'none';
    if (_funnelState.activeTrigger) {
      _funnelState.activeTrigger.classList.remove('active');
    }
    _funnelState.isPinned = false;
  }

  async function _openFunnelPopover(triggerEl, pinned) {
    const pop = document.getElementById('channel-funnel-popover');
    if (!pop) return;

    document.querySelectorAll('.btn-channel-funnel').forEach(b => b.classList.remove('active'));
    if (triggerEl) triggerEl.classList.add('active');

    const rect = triggerEl.getBoundingClientRect();
    const popWidth = 320;
    let left = rect.right - popWidth + window.scrollX;
    if (left < 10) left = 10;
    let top = rect.bottom + 8 + window.scrollY;

    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;
    pop.style.display = 'block';

    pop.onmouseenter = () => {
      if (_funnelState.timer) { clearTimeout(_funnelState.timer); _funnelState.timer = null; }
    };
    pop.onmouseleave = () => {
      scheduleFunnelHide();
    };

    await renderFunnelContent(_funnelState.window);
  }

  async function switchFunnelWindow(win) {
    _funnelState.window = win;
    await renderFunnelContent(win);
  }

  async function renderFunnelContent(win) {
    const pop = document.getElementById('channel-funnel-popover');
    if (!pop || !_funnelState.channelId) return;

    const cacheKey = `${_funnelState.channelId}_${win}`;
    let data = _funnelState.cache[cacheKey];

    pop.innerHTML = `
      <div class="funnel-popover-header">
        <div class="funnel-popover-title">📊 ${_escapeHtml(_funnelState.channelName)}</div>
        <button class="funnel-popover-close" onclick="closeFunnelPopover()">✕</button>
      </div>
      <div class="funnel-tabs">
        <button class="funnel-tab ${win === '24h' ? 'active' : ''}" onclick="switchFunnelWindow('24h')">最近 24 小时</button>
        <button class="funnel-tab ${win === 'today_bj' ? 'active' : ''}" onclick="switchFunnelWindow('today_bj')">今日 (BJ)</button>
        <button class="funnel-tab ${win === '7d' ? 'active' : ''}" onclick="switchFunnelWindow('7d')">近 7 天</button>
        <button class="funnel-tab ${win === '30d' ? 'active' : ''}" onclick="switchFunnelWindow('30d')">近 30 天</button>
        <button class="funnel-tab ${win === 'all' ? 'active' : ''}" onclick="switchFunnelWindow('all')">全生命周期</button>
      </div>
      <div id="funnel-metrics-container">
        <div style="text-align:center;padding:18px 0;color:var(--text3);font-size:0.75rem;">
          <span class="inline-spinner"></span> 正在聚合漏斗数据…
        </div>
      </div>
    `;

    if (!data) {
      try {
        const res = await fetch(`/api/channels/${_funnelState.channelId}/funnel?window=${win}`);
        const json = await res.json();
        if (json.success) {
          data = json.metrics;
          _funnelState.cache[cacheKey] = data;
        }
      } catch (e) {
        console.warn('Funnel fetch failed', e);
      }
    }

    const container = document.getElementById('funnel-metrics-container');
    if (!container) return;

    if (!data || data.total_ingested === 0) {
      container.innerHTML = `
        <div style="text-align:center;padding:20px 0;color:var(--text3);font-size:0.75rem;">
          📭 该时间窗口内暂无采集视频数据
        </div>
      `;
      return;
    }

    const ingested = data.total_ingested || 0;
    const qual = data.qualified || 0;
    const proc = data.processed || 0;
    const pub = data.published || 0;

    const qualPct = ingested > 0 ? Math.min(100, Math.round((qual / ingested) * 100)) : 0;
    const procPct = ingested > 0 ? Math.min(100, Math.round((proc / ingested) * 100)) : 0;
    const pubPct = ingested > 0 ? Math.min(100, Math.round((pub / ingested) * 100)) : 0;

    container.innerHTML = `
      <div class="funnel-steps">
        <div class="funnel-step">
          <div class="funnel-step-header">
            <span class="funnel-step-name">1. 发现采集 (Ingested)</span>
            <span class="funnel-step-value">${ingested}<span class="funnel-step-rate">基准 100%</span></span>
          </div>
          <div class="funnel-step-bar-bg"><div class="funnel-step-bar-fill funnel-bar-1" style="width:100%"></div></div>
        </div>

        <div class="funnel-step">
          <div class="funnel-step-header">
            <span class="funnel-step-name">2. 评分入围 (≥ 75 分)</span>
            <span class="funnel-step-value">${qual}<span class="funnel-step-rate">入围率 ${data.qualification_rate}%</span></span>
          </div>
          <div class="funnel-step-bar-bg"><div class="funnel-step-bar-fill funnel-bar-2" style="width:${qualPct}%"></div></div>
        </div>

        <div class="funnel-step">
          <div class="funnel-step-header">
            <span class="funnel-step-name">3. 制作加工 (Processed)</span>
            <span class="funnel-step-value">${proc}<span class="funnel-step-rate">制作率 ${data.processing_rate}%</span></span>
          </div>
          <div class="funnel-step-bar-bg"><div class="funnel-step-bar-fill funnel-bar-3" style="width:${procPct}%"></div></div>
        </div>

        <div class="funnel-step">
          <div class="funnel-step-header">
            <span class="funnel-step-name">4. 正式发布 (Published)</span>
            <span class="funnel-step-value">${pub}<span class="funnel-step-rate">全链转化 ${data.overall_conversion_rate}%</span></span>
          </div>
          <div class="funnel-step-bar-bg"><div class="funnel-step-bar-fill funnel-bar-4" style="width:${pubPct}%"></div></div>
        </div>
      </div>

      <div class="funnel-diagnosis">
        <div class="funnel-diagnosis-row">
          <span>🛡 拦截/失败:</span>
          <span style="color:${data.failed > 0 ? 'var(--red)' : 'var(--text2)'};font-weight:600;">
            ${data.failed} 条 ${data.censor_blocked > 0 ? `(敏感词 ${data.censor_blocked})` : ''}
          </span>
        </div>
        <div class="funnel-diagnosis-row">
          <span>⏱ 最近采集:</span>
          <span>${data.latest_ingested_at ? _relativeTime(data.latest_ingested_at) : '—'}</span>
        </div>
        ${data.latest_published_at ? `
        <div class="funnel-diagnosis-row">
          <span>🚀 最近发布:</span>
          <span>${_relativeTime(data.latest_published_at)}</span>
        </div>` : ''}
      </div>
    `;
  }

  // Click outside to dismiss funnel popover
  document.addEventListener('click', (e) => {
    const pop = document.getElementById('channel-funnel-popover');
    if (pop && pop.style.display === 'block') {
      if (!pop.contains(e.target) && !e.target.closest('.btn-channel-funnel')) {
        closeFunnelPopover();
      }
    }
  });

  async function deleteChannel(channelId, channelName) {
    if (channelId && typeof channelId === 'object' && channelId.dataset) {
      channelName = channelId.dataset.channelName;
      channelId = channelId.dataset.channelId;
    }
    if (navigator.vibrate) navigator.vibrate(15);
    const displayName = channelName || channelId || '';
    if (!confirm(`确认要从白名单中删除「${displayName}」吗？`)) return;
    try {
      const r = await fetch(`/api/channels/${encodeURIComponent(channelId)}`, { method: 'DELETE' });
      const d = await r.json();
      if (d.success) await fetchChannels();
    } catch(e) { console.warn('delete channel error', e); }
  }

  async function addChannel() {
    if (navigator.vibrate) navigator.vibrate(15);
    const input = document.getElementById('channel-url-input');
    const btn   = document.getElementById('btn-add-channel');
    const fb    = document.getElementById('add-channel-feedback');
    const url   = input.value.trim();
    if (!url) { fb.textContent = '请输入频道 URL'; fb.className = 'add-channel-feedback err'; return; }

    btn.disabled = true;
    btn.innerHTML = '<span class="inline-spinner"></span> 验证中...';
    fb.textContent = '🔍 正在通过 yt-dlp 验证频道（约 5~15 秒）…';
    fb.className = 'add-channel-feedback loading';

    try {
      const r = await fetch('/api/channels/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      const d = await r.json();
      if (d.success) {
        fb.textContent = `✅ 已添加：${d.channel_name} (${d.channel_id})`;
        fb.className = 'add-channel-feedback ok';
        input.value = '';
        await fetchChannels();
      } else {
        if (d.requires_promotion) {
          if (confirm(d.error)) {
            btn.disabled = true;
            fb.textContent = '⚡ 正在提升频道权限…';
            fb.className = 'add-channel-feedback loading';
            try {
              const r2 = await fetch('/api/channels/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, promote: true }),
              });
              const d2 = await r2.json();
              if (d2.success) {
                fb.textContent = `✅ 已成功提升并添加：${d2.channel_name} (${d2.channel_id})`;
                fb.className = 'add-channel-feedback ok';
                input.value = '';
                await fetchChannels();
              } else {
                fb.textContent = `❌ ${d2.error}`;
                fb.className = 'add-channel-feedback err';
              }
            } catch(e) {
              fb.textContent = '❌ 提升权限网络请求失败';
              fb.className = 'add-channel-feedback err';
            } finally {
              btn.disabled = false;
              btn.innerHTML = '验证并添加';
            }
            return;
          }
        }
        fb.textContent = `❌ ${d.error}`;
        fb.className = 'add-channel-feedback err';
      }
    } catch(e) {
      fb.textContent = '❌ 网络请求失败';
      fb.className = 'add-channel-feedback err';
    } finally {
      btn.disabled = false;
      btn.innerHTML = '验证并添加';
    }
  }

  // Export functions onto global window object for HTML inline onclicks & refresh()
  window.fetchChannels = fetchChannels;
  window.toggleChannelPause = toggleChannelPause;
  window.showFunnelPreview = showFunnelPreview;
  window.toggleFunnelPopover = toggleFunnelPopover;
  window.scheduleFunnelHide = scheduleFunnelHide;
  window.closeFunnelPopover = closeFunnelPopover;
  window.switchFunnelWindow = switchFunnelWindow;
  window.renderFunnelContent = renderFunnelContent;
  window.deleteChannel = deleteChannel;
  window.addChannel = addChannel;
  window._funnelState = _funnelState;
})();
