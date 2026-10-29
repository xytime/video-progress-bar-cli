/** 入库诊断的纯展示层：controller → view → 已有语义主题，无反向依赖。
 * Modification History:
 * | 1.0.0 | 2026-10-29 | Codex | 安全属性事件、证据语义与互斥父任务分布。 |
 */
(() => {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const WINDOWS = {'today_bj':'今日入库（北京时间）','24h':'近 24 小时入库','7d':'近 7 天入库','30d':'近 30 天入库','all':'全部入库'};
  const DELIVERY_LABELS = {IN_PREPARATION:'制作/排队中',LOCAL_READY:'本地加工完成',PLATFORM_ACCEPTED:'平台已受理，公开未核实',PUBLIC_CONFIRMED:'公开确认',LOCAL_DONE_UNVERIFIED:'本地完成待核实',DELIVERY_UNCERTAIN:'投递结果待核实',DELIVERY_UNKNOWN:'交付状态未知'};
  const PILLS = [['all_affected','受影响任务','affected_tasks'],['unresolved','当前未解决','unresolved_tasks'],['uncertain_delivery','投递结果待核','uncertain_delivery_tasks'],['stalled','停滞／超时','stalled_tasks'],['recovered','恢复待交付','recovered_pending_delivery']];
  const CATEGORIES = [['ALL','全部原因'],['SYSTEM','系统与阻塞'],['POLICY','质量与策略']];
  function button(action, value, label, extra = '') {
    return `<button type="button" data-action="${action}" data-value="${esc(value)}" ${extra}>${label}</button>`;
  }
  function scopeLabel(scope) { return `${WINDOWS[scope.window] || scope.window} · ${scope.channel || '全部频道'}`; }
  function matches(task, state, includeCause = true) {
    if (state.pill === 'unresolved' && !task.unresolved) return false;
    if (state.pill === 'uncertain_delivery' && !task.is_uncertain_delivery) return false;
    if (state.pill === 'stalled' && !task.is_stalled) return false;
    if (state.pill === 'recovered' && task.handling_state !== 'RECOVERED_PENDING_DELIVERY') return false;
    if (state.category === 'SYSTEM' && task.category === 'QUALITY_POLICY_BLOCK') return false;
    if (state.category === 'POLICY' && task.category !== 'QUALITY_POLICY_BLOCK') return false;
    return !includeCause || !state.cause || task.cause_code === state.cause;
  }
  function channelOptions(state) {
    const source = document.getElementById('video-filter-channel');
    const channels = new Map((state.channels || []).map(c => [c.channel_id,c.channel_name || c.channel_id]));
    [...(source?.options || [])].forEach(o => {if (o.value) channels.set(o.value,o.textContent);});
    if (state.channel && !channels.has(state.channel)) channels.set(state.channel,state.channel);
    return '<option value="">全部频道</option>' + [...channels].map(([id,name]) => `<option value="${esc(id)}" ${id === state.channel ? 'selected' : ''}>${esc(name)}</option>`).join('');
  }
  function header(data, state) {
    const summary = data?.summary, known = summary && !state.error && !state.loading;
    const status = !known ? '当前状态待核实' : !summary.total_ingested ? '当前范围无入库记录' : summary.unresolved_tasks ? '需关注 · 存在交付阻塞' : '本次观测未发现未解决异常';
    return `<div class="funnel-diag-header"><div class="funnel-diag-title-group"><strong>批次健康诊断</strong><span class="funnel-diag-scope-chip">${status}</span></div><div class="funnel-diag-meta">${button('refresh','','刷新诊断',`id="funnel-refresh" class="funnel-diag-btn-retry" ${state.loading ? 'disabled' : ''}`)}</div></div>
      <div class="funnel-diag-filters"><label for="funnel-window">入库范围 <select id="funnel-window">${Object.entries(WINDOWS).map(([value,text]) => `<option value="${value}" ${state.window === value ? 'selected' : ''}>${text}</option>`).join('')}</select></label><label for="funnel-channel">频道 <select id="funnel-channel">${channelOptions(state)}</select></label>${button('clear','','清除诊断筛选','id="funnel-clear" class="funnel-diag-btn-retry"')}</div>
      <p class="funnel-diag-scope-text">请求范围：${esc(scopeLabel(state))} · ${state.loading ? '正在读取…' : '观测时间：' + esc(data?.as_of_bj || '尚无成功观测')}（北京时间）${state.channelsError ? ' · 频道选项读取失败，已保留当前频道；刷新可重试。' : ''}</p>`;
  }
  function banners(data, state) {
    let html = state.error ? `<div class="funnel-diag-banner funnel-diag-banner-error" role="status">读取失败：${esc(state.error)}。${data ? `下方为旧快照（${esc(scopeLabel(state.snapshotScope))}，${esc(data.as_of_bj || '时效未知')} 北京时间），请勿据此判断当前健康。` : '暂无可信诊断数据，状态未知。'}</div>` : '';
    if (state.loading && data) html += `<div class="funnel-diag-banner funnel-diag-banner-stale" role="status">正在读取所选范围；下方为上次成功快照：${esc(scopeLabel(state.snapshotScope))}。</div>`;
    if (data?.summary?.has_insufficient_history) html += '<div class="funnel-diag-banner funnel-diag-banner-history">历史覆盖不足：部分任务缺少事件账本，异常时间可能由更新时间估算，请以任务证据为准。</div>';
    if (data?.summary?.total_ingested === 0) html += '<div class="funnel-diag-banner funnel-diag-banner-empty">当前范围无入库记录。可调整上方时间和频道。</div>';
    return html;
  }
  function renderProportionBar(summary) {
    const distribution = summary.family_distribution, total = summary.affected_tasks || 0;
    if (!total) return '';
    const groups = [['system','系统故障未解','fault'],['uncertain','投递结果待核','unverified'],['policy','策略规则拦截','policy'],['recovered','恢复待交付','recovered']];
    const valid = distribution && groups.every(([key]) => Number.isInteger(distribution[key]) && distribution[key] >= 0) && groups.reduce((n,[key]) => n + distribution[key],0) === total;
    if (!valid) return '<p class="funnel-diag-banner funnel-diag-banner-history">互斥分布尚未核实，暂不展示比例。</p>';
    return `<div class="funnel-diag-proportion-bar" role="img" aria-label="受影响父任务互斥分布，共${total}条">${groups.map(([key,label,cls]) => `<span class="funnel-diag-prop-seg seg-${cls}" style="width:${distribution[key] / total * 100}%" title="${label} ${distribution[key]}"></span>`).join('')}</div><div class="funnel-diag-prop-labels">${groups.map(([key,label]) => `<span>${label}：<b>${distribution[key]}</b></span>`).join('')}</div><p class="funnel-diag-scope-text">比例按父任务唯一主态归类；下方原因和明细保留各分集，可与父任务数不同。</p>`;
  }
  function pills(summary, state) {
    return `<div class="funnel-diag-pills" aria-label="指标筛选">${PILLS.map(([key,label,field]) => button('pill',key,`<span>${label}</span><b>${summary[field] ?? 0}</b>`,`id="funnel-pill-${key}" class="funnel-diag-pill ${state.pill === key ? 'active' : ''}" aria-pressed="${state.pill === key}"`)).join('')}</div>`;
  }
  function categoryTabs(state) {
    return `<div class="funnel-diag-category-tabs" aria-label="原因类别">${CATEGORIES.map(([key,label]) => button('category',key,label,`id="funnel-category-${key}" class="funnel-diag-cat-tab ${state.category === key ? 'active' : ''}" aria-pressed="${state.category === key}"`)).join('')}</div>`;
  }
  function renderCauses(data, state) {
    const tasks = (data.tasks || []).filter(t => matches(t,state,false));
    const causes = (data.causes || []).filter(c => tasks.some(t => t.cause_code === c.cause_code));
    const cards = causes.map((cause,index) => {
      const selected = cause.cause_code === state.cause, rows = tasks.filter(t => t.cause_code === cause.cause_code);
      const families = new Set(rows.map(t => t.family_root_id || t.video_id)).size;
      return button('cause',cause.cause_code,`<span class="funnel-diag-cause-header"><strong>${esc(cause.cause_title)}</strong><span>${families} 父任务 · ${rows.length} 明细</span></span><span class="funnel-diag-cause-body">${esc(cause.recommended_next_step || '')}</span>`,`id="funnel-cause-${index}" class="funnel-diag-cause-card ${selected ? 'selected' : ''}" aria-pressed="${selected}"`);
    }).join('');
    return `<section class="funnel-diag-causes-column" aria-label="根因聚类"><h3>根因聚类</h3><p class="funnel-diag-scope-text">随指标与类别筛选；选择原因查看对应任务。</p><div class="funnel-diag-causes-list">${cards || '<p>当前类别没有原因记录。</p>'}</div></section>`;
  }
  function renderTaskStepPills(task) {
    const parts = [], status = task.status || '未知', observed = task.runtime_observed_at_bj || '时效未记录';
    parts.push(`<span class="funnel-step-pill step-todo">当前任务：${esc(status)}</span>`);
    if (task.stage) parts.push(`<span class="funnel-step-pill ${task.unresolved ? 'step-fail' : 'step-todo'}">记录工序：${esc(task.stage)}</span>`);
    if (task.handling_state === 'RECOVERED_PENDING_DELIVERY') parts.push('<span class="funnel-step-pill step-done">故障已解除 · 交付未完成</span>');
    if (task.runtime_observation_available === false) parts.push('<span class="funnel-step-pill step-todo">运行观测不可用 · 锁与进程状态未知</span>');
    else if (task.has_active_task_lock === true) parts.push(`<span class="funnel-step-pill step-active" title="观测于 ${esc(observed)} 北京时间">观测时任务锁占用</span>`);
    else if (task.has_active_task_lock === false) parts.push('<span class="funnel-step-pill step-todo">观测时任务锁未占用</span>');
    if (task.is_uncertain_delivery) parts.push('<span class="funnel-step-pill step-warn">发表结果待核 · 禁止盲目重投</span>');
    return `<div class="funnel-step-pills">${parts.join('')}</div>`;
  }
  function evidence(task, prefix = '') {
    const blocks = [['事实清单','facts'],['诊断推测','inferences'],['处置建议','recommendations']];
    const grids = blocks.map(([label,key]) => `<section class="evidence-block"><h4>${label}</h4><ul>${(task[key] || []).map(text => `<li>${esc(text)}</li>`).join('') || '<li>暂无记录</li>'}</ul></section>`).join('');
    const error = task.sanitized_error_excerpt ? `<div class="funnel-diag-error-box">${button('copy',task.video_id,'复制错误',`id="${prefix}funnel-copy-${Number(task.video_id)}" class="funnel-diag-btn-retry"`)}<code>${esc(task.sanitized_error_excerpt)}</code></div>` : '';
    const receipt = task.is_uncertain_delivery ? button('receipt',task.video_id,'核对发布回执',`id="${prefix}funnel-receipt-${Number(task.video_id)}" class="funnel-diag-action-btn"`) : '';
    return `<div class="funnel-diag-drawer" id="${prefix}funnel-evidence-${Number(task.video_id)}"><div class="funnel-diag-evidence-grid">${grids}</div>${error}<div class="funnel-diag-guarded-actions">${prefix ? '' : button('details',task.video_id,'查看任务详情',`id="funnel-details-${Number(task.video_id)}" class="funnel-diag-action-btn funnel-diag-action-primary"`)}${receipt}</div></div>`;
  }
  function taskItem(task, state) {
    const id = Number(task.video_id), expanded = id === state.expanded, slice = Number(task.slice_index) || 0;
    return `<article class="funnel-diag-task-item"><div class="funnel-diag-task-row"><div class="funnel-diag-task-meta-line"><div class="funnel-diag-task-info"><span>#${id} · 分集 ${slice}</span><strong>${esc(task.title || task.youtube_id)}</strong></div>${button('toggle',id,expanded ? '收起证据' : '排障与证据',`id="funnel-toggle-${id}" class="funnel-diag-btn-toggle" aria-expanded="${expanded}" aria-controls="funnel-evidence-${id}"`)}</div>${renderTaskStepPills(task)}<div class="funnel-diag-task-badges"><span>${esc(task.handling_state_label || '处理状态未记录')}</span><span>${esc(DELIVERY_LABELS[task.delivery_state] || '交付状态未知')}</span></div><p class="funnel-diag-scope-text">入库：${esc(task.ingested_at || '未记录')} · 异常发生：${esc(task.occurred_at || '未记录')}（北京时间）</p></div>${expanded ? evidence(task) : `<div id="funnel-evidence-${id}" hidden></div>`}</article>`;
  }
  function renderTasks(data, state) {
    const filtered = (data.tasks || []).filter(task => matches(task,state));
    const cause = (data.causes || []).find(c => c.cause_code === state.cause);
    const active = [PILLS.find(([key]) => key === state.pill)?.[1],CATEGORIES.find(([key]) => key === state.category)?.[1],cause?.cause_title || state.cause].filter(Boolean).join(' · ');
    return `<section class="funnel-diag-tasks-column"><h3 id="funnel-task-heading" tabindex="-1">受影响明细（${filtered.length} 条）</h3><p class="funnel-diag-scope-text">生效条件：${esc(active || '全部异常')} ${state.cause ? button('cause','','清除原因筛选','id="funnel-clear-cause" class="funnel-diag-btn-retry"') : ''}</p>${filtered.map(task => taskItem(task,state)).join('') || '<p>当前条件无明细，请调整或清除上方筛选。</p>'}</section>`;
  }
  function render(data, state) {
    let html = header(data,state) + banners(data,state);
    if (!data?.summary) return html;
    const summary = data.summary;
    if (summary.diagnosis_sentence) html += `<p class="funnel-diag-narrative">${esc(summary.diagnosis_sentence)}</p>`;
    html += renderProportionBar(summary) + pills(summary,state);
    if (summary.affected_tasks) html += categoryTabs(state) + `<div class="funnel-diag-main-grid ${state.cause ? 'has-cause' : ''}">${renderCauses(data,state)}${renderTasks(data,state)}</div>`;
    return html;
  }
  function detail(data) {
    const task = {...data,...data.diagnosis,...data.evidence};
    const runtime = data.runtime || {}, available = runtime.runtime_observation_available !== false;
    const lock = !available ? '未知' : runtime.has_active_task_lock === true ? '占用' : runtime.has_active_task_lock === false ? '未占用' : '未知';
    const process = !available ? '未知' : runtime.process_alive === true ? '存活' : runtime.process_alive === false ? '未发现' : '未知';
    return `<p><strong>#${Number(data.video_id)} · ${esc(data.youtube_id)} · 分集 ${Number(data.slice_index) || 0}</strong></p><h3>${esc(data.title)}</h3><p>当前状态：${esc(data.status || '未知')} · ${esc(DELIVERY_LABELS[data.delivery_state] || '交付状态未知')}</p><p>本次运行观测：锁${lock} · 进程${process}</p><p>服务观测时间：${esc(data.as_of_bj || runtime.runtime_observed_at_bj || task.runtime_observed_at_bj || '未提供')}（北京时间）</p>${evidence(task,'detail-')}`;
  }
  window.FunnelDiagnosisView = {esc,WINDOWS,scopeLabel,matches,render,detail,renderProportionBar,renderTaskStepPills};
})();
