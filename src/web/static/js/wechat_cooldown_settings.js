/** 视频号冷却与调度策略：实时状态观测、确认平台已解冻与 CAS 策略保存。 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const base = '/api/wechat-cooldown-settings';
  const fields = {
    'scheduler-enabled': 'scheduler_enabled',
    'stable-interval-seconds': 'stable_interval_seconds',
    'daily-limit': 'daily_limit',
    'recovery-interval-seconds': 'recovery_interval_seconds',
    'recovery-limit': 'recovery_limit',
    'request-min-interval-seconds': 'request_min_interval_seconds',
    'rate-limit-cooldown-seconds': 'rate_limit_cooldown_seconds',
  };
  let saved = null, defaults = null, runtime = null, digest = '', busy = false, conflict = false;
  let leaveAction = null, returnFocus = null;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const fmtTime = epoch => {
    if (!epoch || epoch <= 0) return '无';
    return new Date(epoch * 1000).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false});
  };
  const fmtDuration = seconds => {
    if (!Number.isFinite(seconds) || seconds < 0) return '请输入有效秒数';
    if (!seconds) return '0 秒';
    if (seconds % 3600 === 0) return `${seconds / 3600} 小时 (${seconds}s)`;
    if (seconds % 60 === 0) return `${seconds / 60} 分钟 (${seconds}s)`;
    return `${seconds} 秒`;
  };
  const fmtRemaining = seconds => {
    const n = Math.max(0, Math.ceil(seconds || 0));
    if (!n) return '当前可立即启动会话';
    const h = Math.floor(n / 3600);
    const m = Math.floor((n % 3600) / 60);
    const s = n % 60;
    return `剩余 ${h ? h + ' 小时 ' : ''}${m ? m + ' 分 ' : ''}${s} 秒`;
  };

  async function api(path = '', options = {}) {
    const response = await fetch(base + path, {
      ...options,
      headers: {'Content-Type': 'application/json'},
      signal: AbortSignal.timeout(12000),
    });
    const result = await response.json();
    if (!response.ok) {
      const error = new Error(typeof result.detail === 'string' ? result.detail : '请求校验未通过，请检查输入。');
      error.status = response.status;
      throw error;
    }
    return result;
  }

  function draft() {
    const value = structuredClone(saved || {});
    Object.entries(fields).forEach(([id, name]) => {
      const el = $(id);
      if (el.type === 'checkbox') value[name] = Boolean(el.checked);
      else value[name] = el.value === '' ? null : Number(el.value);
    });
    return value;
  }

  const dirty = () => Boolean(saved && JSON.stringify(draft()) !== JSON.stringify(saved));

  function renderRuntime(rt) {
    runtime = rt;
    if (!rt) return;
    if (rt.platform_frozen) {
      $('rt-status').textContent = '平台限流冷却中';
      $('rt-reason').textContent = `触发原因：${rt.cooldown?.reason || '视频号返回限流'}${rt.business_code != null ? ` (${rt.business_code})` : ''}`;
    } else if (rt.recovering) {
      $('rt-status').textContent = '限流后 24h 恢复期';
      $('rt-reason').textContent = rt.cooldown?.active ? '正在按恢复期间隔排队' : '恢复期内可按配额启动投稿';
    } else if (rt.effective_remaining_seconds > 0) {
      $('rt-status').textContent = '正常会话节流间隔中';
      $('rt-reason').textContent = '非平台封禁；按稳定期间隔顺序放行队列';
    } else {
      $('rt-status').textContent = '空闲 · 可立即发布';
      $('rt-reason').textContent = '无活跃冷却或会话间隔等待';
    }
    $('rt-until').textContent = rt.effective_until > Date.now() / 1000 ? fmtTime(rt.effective_until) : '现在';
    $('rt-remaining').textContent = fmtRemaining(rt.effective_remaining_seconds);
    $('rt-quota').textContent = `${rt.sessions_24h_count} / ${rt.effective_daily_limit} 次`;
    $('rt-interval-mode').textContent = `${rt.recovering ? '恢复期' : '稳定期'}间隔 ${fmtDuration(rt.effective_interval_seconds)} · 排队 ${rt.queue_count} 条`;
    $('rt-streak').textContent = `级数 ${rt.failure_streak}（代码：${rt.reason_code}）`;
    $('rt-last-limited').textContent = `最近限流：${fmtTime(rt.last_limited_at)}`;
    $('btn-unfreeze').disabled = busy || !rt.can_unfreeze;
    $('rt-session-count').textContent = String(rt.sessions_24h_count || 0);
    const sessions = rt.recent_sessions || [];
    $('rt-sessions-list').innerHTML = sessions.length
      ? sessions.slice().reverse().map(s => `<div class="wc-session-row"><span><strong>${esc(s.purpose)}</strong> · ${esc(s.task)}</span><time>${esc(fmtTime(s.at))}</time></div>`).join('')
      : '<p class="hint">最近 24 小时暂无平台会话记录。</p>';
  }

  function state() {
    $('editor').disabled = !saved || busy;
    $('reload').disabled = busy;
    $('reset-defaults').disabled = !saved || busy;
    $('save').disabled = !dirty() || busy || conflict;
    $('btn-unfreeze').disabled = busy || !runtime?.can_unfreeze;
    $('dirty-state').textContent = busy
      ? '正在处理…'
      : !saved
      ? '尚未载入'
      : conflict
      ? '保存冲突，草稿已保留'
      : dirty()
      ? '有未保存的修改'
      : '与已保存策略一致';
    if (!saved) return;
    const value = draft();
    $('stable-interval-hint').textContent = `折合：${fmtDuration(value.stable_interval_seconds)}`;
    $('recovery-interval-hint').textContent = `折合：${fmtDuration(value.recovery_interval_seconds)}`;
    $('sum-enabled').textContent = value.scheduler_enabled ? '已开启（推荐）' : '已关闭（仅基础间隔）';
    $('sum-stable-interval').textContent = fmtDuration(value.stable_interval_seconds);
    $('sum-daily-limit').textContent = `${value.daily_limit ?? '—'} 次 / 24h`;
    $('sum-recovery-interval').textContent = fmtDuration(value.recovery_interval_seconds);
    $('sum-recovery-limit').textContent = `${value.recovery_limit ?? '—'} 次 / 24h`;
    $('sum-req-interval').textContent = fmtDuration(value.request_min_interval_seconds);
    $('sum-rate-cooldown').textContent = fmtDuration(value.rate_limit_cooldown_seconds);
    $('policy-preview').textContent = `${dirty() ? '未保存草稿' : '已生效策略'}：${
      value.scheduler_enabled
        ? `稳定期每 ${fmtDuration(value.stable_interval_seconds)} 放行 1 条，每日上限 ${value.daily_limit} 次。`
        : '统一调度已关闭，仅受基础会话最小间隔限制。'
    }`;
  }

  function render(data) {
    saved = data.config;
    defaults = data.defaults || saved;
    digest = data.digest;
    conflict = false;
    Object.entries(fields).forEach(([id, name]) => {
      const el = $(id);
      if (el.type === 'checkbox') el.checked = Boolean(saved[name]);
      else el.value = String(saved[name]);
      el.removeAttribute('aria-invalid');
    });
    renderRuntime(data.runtime);
    state();
  }

  async function load() {
    if (busy) return;
    busy = true; state();
    try {
      render(await api(''));
      $('feedback').textContent = '';
    } catch (error) {
      $('feedback').textContent = '读取失败：' + error.message;
    } finally {
      busy = false; state();
    }
  }

  function validate() {
    const value = draft();
    const failures = [];
    const rules = [
      ['stable-interval-seconds', 60, 86400, '稳定期最小间隔须为 60–86400 之间的整数秒。'],
      ['daily-limit', 1, 100, '稳定期 24 小时最大会话数须为 1–100 之间的整数。'],
      ['recovery-interval-seconds', 300, 86400, '恢复期最小间隔须为 300–86400 之间的整数秒。'],
      ['recovery-limit', 1, 20, '恢复期 24 小时最大会话数须为 1–20 之间的整数。'],
      ['request-min-interval-seconds', 1, 3600, '基础会话最小间隔须为 1–3600 之间的整数秒。'],
      ['rate-limit-cooldown-seconds', 300, 86400, '限流退避基数须为 300–86400 之间的整数秒。'],
    ];
    rules.forEach(([id, min, max, msg]) => {
      const num = value[fields[id]];
      if (!Number.isInteger(num) || num < min || num > max) failures.push([id, msg]);
    });
    Object.keys(fields).forEach(id => {
      $(id).setAttribute('aria-invalid', String(failures.some(([f]) => f === id)));
    });
    if (failures.length) {
      $('feedback').textContent = failures.map(([, m]) => m).join(' ');
      $(failures[0][0]).focus();
      return false;
    }
    return true;
  }

  async function save() {
    if (busy || conflict || !dirty() || !validate()) return;
    const config = draft();
    busy = true; state();
    $('feedback').textContent = '正在保存冷却与调度策略…';
    try {
      render(await api('', {method: 'PUT', body: JSON.stringify({config, expected_digest: digest})}));
      $('feedback').textContent = '策略已保存并热加载生效。';
    } catch (error) {
      conflict = error.status === 409;
      $('feedback').textContent = `${conflict ? '保存冲突：配置已被其他窗口修改，请刷新状态后重试。' : '保存失败：' + error.message} 草稿已保留。`;
    } finally {
      busy = false; state();
    }
  }

  function guarded(action) {
    if (!dirty()) { action(); return; }
    leaveAction = action; returnFocus = document.activeElement;
    $('keep-editing').disabled = false; $('discard').disabled = false;
    $('discard-dialog').showModal(); $('keep-editing').focus();
  }

  $('discard-dialog').addEventListener('close', () => returnFocus?.focus());
  $('keep-editing').addEventListener('click', () => { leaveAction = null; $('discard-dialog').close(); });
  $('discard').addEventListener('click', () => { const a = leaveAction; leaveAction = null; $('discard-dialog').close(); a?.(); });
  window.addEventListener('beforeunload', e => { if (dirty()) { e.preventDefault(); e.returnValue = ''; } });

  $('settings-form').addEventListener('input', state);
  $('settings-form').addEventListener('change', state);
  $('settings-form').addEventListener('submit', e => { e.preventDefault(); save(); });
  $('save').addEventListener('click', save);
  $('reload').addEventListener('click', () => guarded(load));
  $('reset-defaults').addEventListener('click', () => {
    if (!defaults) return;
    Object.entries(fields).forEach(([id, name]) => {
      const el = $(id);
      if (el.type === 'checkbox') el.checked = Boolean(defaults[name]);
      else el.value = String(defaults[name]);
    });
    state();
    $('feedback').textContent = '已填入推荐默认值，点击“保存策略”后生效。';
  });

  document.querySelectorAll('.wc-preset').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = $(btn.dataset.target);
      if (target) { target.value = btn.dataset.val; state(); }
    });
  });

  const unfreezeDialog = $('unfreeze-dialog');
  $('btn-unfreeze').addEventListener('click', () => {
    if (!runtime?.can_unfreeze || busy) return;
    returnFocus = document.activeElement;
    unfreezeDialog.showModal();
    $('unfreeze-cancel').focus();
  });
  unfreezeDialog.addEventListener('close', () => returnFocus?.focus());
  $('unfreeze-cancel').addEventListener('click', () => unfreezeDialog.close());
  $('unfreeze-confirm').addEventListener('click', async () => {
    unfreezeDialog.close();
    if (!runtime?.cooldown?.version || busy) return;
    busy = true; state();
    $('feedback').textContent = '正在解除平台限流与恢复期限制…';
    try {
      const res = await api('/unfreeze', {
        method: 'POST',
        body: JSON.stringify({version: runtime.cooldown.version}),
      });
      render(res);
      $('feedback').textContent = res.message || '已确认平台解冻。';
    } catch (error) {
      $('feedback').textContent = '解冻失败：' + error.message;
    } finally {
      busy = false; state();
    }
  });

  window.consoleNavigationGuard = guarded;
  load();
})();
