# 原生控件
FastAPI 提供 HTML + vanilla JS，无 React、Tailwind 或组件库。使用原生 button/input/select/dialog，候选业务 owner 为 topic_candidates.js。
### src/web/templates/topic_candidates.html
```html
<!doctype html>
<!-- Modification History: 1.0.0 | 2026-10-11 | Codex | v0.2 本机候选工作台，无制作或发布操作。 -->
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="topic-csrf" content="__TOPIC_CSRF__"><title>YouTube 关键词采集 · 视频控制台</title>
<script src="/static/js/topic_display_preferences.js?v=1"></script>
<link rel="stylesheet" href="/static/css/dashboard.css"><link rel="stylesheet" href="/static/css/product_settings.css?v=20261011-redesign">
<link rel="stylesheet" href="/static/css/topic_candidates.css?v=20261015-01"><script defer src="/static/js/topic_candidates.js?v=20261015-05"></script>
<link rel="stylesheet" href="/static/css/console_workspace.css?v=20261013-04"><script defer src="/static/js/console_navigation.js"></script></head><body><main class="product-settings topic-workbench">
<nav class="breadcrumbs" aria-label="当前位置"><a href="/">视频控制台</a><span aria-hidden="true"> / </span><span aria-current="page">YouTube 关键词采集</span></nav>
<header class="page-header"><div><h1>YouTube 关键词采集</h1><p class="hint">跨频道搜索事件报道，跟踪热度并按现有规则筛选。</p></div><div class="header-actions"><button disabled id="reload" type="button">重新载入</button><button id="new-topic" class="primary" type="button" disabled>新建采集规则</button></div></header>
<div class="status-banner"><div><p id="mode-state" role="status">正在读取运行状态…</p><p id="gate-reason" class="hint"></p><p id="budget" class="hint"></p><p id="collection-state" class="hint"></p></div><button id="mode-button" type="button" disabled>开启搜索</button></div>
<div class="read-feedback"><div><p class="hint">达标准入开放后可进入现有自动制作发布流程。</p><p id="admission-usage" class="hint" role="status"></p></div><button id="admission-button" type="button" disabled>开启达标准入</button></div>
<div class="read-feedback"><p id="state-feedback" role="status" aria-live="polite"></p><button disabled id="state-retry" type="button">重试运行状态</button></div>
<p id="feedback" role="status" aria-live="polite"></p>
<section aria-labelledby="topics-heading"><div class="section-head"><h2 id="topics-heading">采集规则</h2><span class="hint">最多 10 个有效采集规则；同时最多 1 条定时规则；保存后默认不自动采集。</span></div><div id="topics" aria-busy="true"><p>正在载入采集规则…</p></div></section>
<section aria-labelledby="pool-heading"><div class="section-head"><h2 id="pool-heading">候选池</h2><span class="hint">收藏仅保存选题意向。</span></div>
<form id="filters" class="candidate-filters" novalidate>
<div><label for="topic-filter">采集规则</label><select id="topic-filter"><option value="">全部采集规则</option></select></div>
<div><label for="state-filter">整理状态</label><select id="state-filter"><option value="">全部</option><option value="NEW">未整理</option><option value="SAVED">收藏</option><option value="REJECTED">排除</option></select></div>
<div><label for="eligibility-filter">规则状态</label><select id="eligibility-filter"><option value="">全部</option><option value="CHECKABLE">可人工核实</option><option value="INCOMPLETE">资料不足</option><option value="RESTRICTED">规则受限</option><option value="UNAVAILABLE">不可用</option></select></div>
<div class="candidate-search"><label for="candidate-query">标题或频道</label><input id="candidate-query" type="search" maxlength="120" placeholder="搜索已有候选"><button disabled id="clear-query" type="button" aria-label="清空候选搜索">清空</button></div>
</form>
<div class="read-feedback"><p id="candidate-feedback" role="status" aria-live="polite"></p><button disabled id="candidate-retry" type="button">重试候选列表</button><button disabled id="candidate-previous-filter" type="button" hidden>返回上次成功条件</button></div>
<div id="candidates" aria-busy="true"><p>正在载入候选…</p></div><div class="candidate-pagination"><p id="candidate-range" class="hint"></p><div><button id="previous" type="button" disabled>上一页</button><button id="next" type="button" disabled>下一页</button></div></div></section>
<section aria-labelledby="jobs-heading"><h2 id="jobs-heading">采集与刷新记录</h2><div id="jobs"></div><details><summary id="audit-open">操作记录</summary><div id="audit-records"></div></details></section>
<dialog id="topic-editor" aria-labelledby="editor-title"><form id="topic-form" novalidate><div class="dialog-head"><h2 id="editor-title">新建采集规则</h2><button disabled id="editor-close" type="button" aria-label="关闭采集规则编辑">×</button></div><div class="dialog-body">
<label for="topic-name">采集规则名称</label><input id="topic-name" type="text" maxlength="40" aria-describedby="name-error"><p id="name-error" class="field-error"></p>
<label for="topic-query">查询词</label><input id="topic-query" type="text" maxlength="120" placeholder="例如 plague outbreak" aria-describedby="query-error"><p id="query-error" class="field-error"></p>
<p class="hint">保留原查询，不自动扩词。可使用 YouTube 的 OR（|）与排除词（-）。</p>
<label for="topic-category">类别</label><select id="topic-category"><option>宏观经济</option><option>科技产业</option><option>商业历史</option><option>健康科学</option><option>地缘战略</option></select>
<label for="topic-lookback">发布时间范围</label><select id="topic-lookback"><option value="1" selected>最近 24 小时</option><option value="3">最近 72 小时</option><option value="7">最近 7 天</option><option value="30">最近 30 天</option></select>
<label for="topic-language">搜索语言偏好（不代表语言已核实）</label><select id="topic-language"><option value="en">英语</option><option value="zh">中文</option><option value="ja">日语</option><option value="es">西班牙语</option><option value="fr">法语</option><option value="de">德语</option></select>
<label for="topic-duration">最低时长（最长 30 分钟）</label><select id="topic-duration"><option value="30">30 秒</option><option value="60">1 分钟</option><option value="180">3 分钟</option></select>
<label for="topic-days">有效天数</label><input id="topic-days" type="number" min="1" max="30" step="1" value="7" aria-describedby="days-error"><p id="days-error" class="field-error"></p>
<p id="form-feedback" role="status"></p></div><div class="dialog-foot"><button disabled id="editor-cancel" type="button">返回采集规则列表</button><button id="topic-save" class="primary" type="submit">保存采集规则</button></div></form></dialog>
<dialog id="action-dialog" aria-labelledby="action-title"><form id="action-form" novalidate><div class="dialog-head"><h2 id="action-title"></h2></div><div class="dialog-body"><p id="action-description"></p><div id="reason-field"><label for="reject-reason">排除原因</label><select id="reject-reason"><option>不相关</option><option>来源不可信</option><option>不适合受众</option><option>已重复</option><option>其他</option></select></div><div id="renew-field"><label for="renew-days">新有效期（天）</label><input id="renew-days" type="number" min="1" max="30" value="7"></div><p id="action-feedback" role="status"></p></div><div class="dialog-foot"><button disabled id="action-cancel" type="button">返回</button><button id="action-confirm" type="submit">确认</button></div></form></dialog>
<dialog id="discard-dialog" aria-labelledby="discard-title"><h2 id="discard-title">有尚未保存的修改</h2><p>返回列表会丢弃当前表单修改。</p><div class="dialog-foot"><button disabled id="keep-editing" type="button" autofocus>继续编辑</button><button disabled id="discard-edit" type="button">丢弃修改并返回</button></div></dialog>
</main></body></html>

```

### src/web/static/css/product_settings.css
```css
/* 商品管理工作台：共享 dashboard 主题，布局与控件密度由 DESIGN.md 约定。 */
.product-settings { --product-action: var(--blue); max-width: 1480px; margin: auto; padding: 20px 28px 40px; font: .875rem/1.5 -apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif; }
.product-settings *, .product-picker-dialog * { box-sizing: border-box; }
.product-settings [hidden] { display: none !important; }
.product-settings h1 { font-size: 1.5rem; line-height: 1.3; margin: 0 0 4px; }
.product-settings h2 { font-size: 1rem; line-height: 1.45; margin: 0 0 8px; }
.product-settings h3 { font-size: .875rem; }
.product-settings p { margin: 0 0 8px; }
.product-settings a { color: var(--blue); }
.product-settings button,.product-picker-dialog button { min-height: 40px; padding: 8px 13px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg2); color: var(--text); font: inherit; cursor: pointer; }
.product-settings button:hover,.product-picker-dialog button:hover { border-color: var(--blue); background: var(--glass-b); }
.product-settings button:disabled,.product-picker-dialog button:disabled { opacity: .5; cursor: not-allowed; }
.product-settings .primary { background: var(--product-action); color: var(--bg); border-color: var(--product-action); font-weight: 650; min-width: 116px; }
.product-settings :focus-visible,.product-picker-dialog :focus-visible { outline: 2px solid var(--blue); outline-offset: 3px; }
.product-settings input,.product-settings select,.product-picker-dialog input { width: 100%; min-width: 0; min-height: 40px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg); color: var(--text); font: inherit; }
.product-settings select { cursor: pointer; }
.product-settings label { display: block; margin: 12px 0 5px; }
.product-settings fieldset { padding: 0; border: 0; min-width: 0; }
.product-settings .breadcrumbs { color: var(--text2); font-size: .75rem; margin-bottom: 14px; }
.product-settings .page-header { position: sticky; top: 0; z-index: 5; display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 14px 0; background: var(--bg); }
.product-settings .header-actions,.product-settings .actions { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.product-settings #dirty-state { color: var(--text2); font-size: .75rem; }
.product-settings .status-banner { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 9px 14px; border: 1px solid var(--orange); border-radius: 6px; background: color-mix(in srgb,var(--orange) 8%,var(--bg)); }
.product-settings .status-banner p { margin: 0; font-size: .75rem; }
.product-settings .status-banner button { border: 0; min-height: 32px; white-space: nowrap; color: var(--blue); background: transparent; padding: 4px; }
.product-settings #feedback { min-height: 30px; margin: 0; padding: 5px 0; font-size: .75rem; overflow-wrap: anywhere; }
.product-settings [data-error="true"] { color: var(--red); }
.product-settings .view-tabs { display: flex; gap: 20px; margin-bottom: 18px; border-bottom: 1px solid var(--border); }
.product-settings .view-tabs button { border: 0; border-radius: 0; background: transparent; padding: 10px 4px; border-bottom: 3px solid transparent; }
.product-settings .view-tabs button[aria-current] { color: var(--blue); border-bottom-color: var(--blue); font-weight: 650; }
.product-settings #library-count { font-size: .7rem; color: var(--text2); }
.product-settings .rules-layout { display: grid; grid-template-columns: minmax(0,2.6fr) minmax(280px,1fr); gap: 18px; align-items: start; }
.product-settings .rules-main,.product-settings .details-panel { min-width: 0; }
.product-settings section { padding: 18px; border: 1px solid var(--border); border-radius: 8px; background: var(--glass); margin-bottom: 14px; }
.product-settings .section-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 10px; }
.product-settings .section-head h2 { margin: 0; }
.product-settings .section-head .hint { font-size: .7rem; }
.product-settings .mapping-columns,.product-settings .profile-row { display: grid; grid-template-columns: 1.05fr 1.15fr 1.15fr; gap: 12px; align-items: center; }
.product-settings .mapping-columns { padding: 8px 0; color: var(--text2); font-size: .75rem; border-bottom: 1px solid var(--border); }
.product-settings .profile-row { padding: 12px 0; border-bottom: 1px solid var(--border); }
.product-settings .profile-row:last-child { border-bottom: 0; }
.product-settings .profile-row h3 { font-size: .8rem; font-weight: 650; margin: 0; }
.product-settings .profile-row .profile-description { color: var(--text2); font-size: .65rem; margin-top: 3px; }
.product-settings .profile-row[data-current="true"] h3 { color: var(--blue); }
.product-settings .product-picker-trigger { display: flex; justify-content: space-between; align-items: center; gap: 10px; width: 100%; text-align: left; min-width: 0; font-size: .75rem; background: var(--bg2); }
.product-settings .product-picker-trigger span:first-child { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.product-settings .default-panel { display: grid; grid-template-columns: 1fr 1.4fr; align-items: center; gap: 14px; }
.product-settings .default-panel h2 { font-size: .875rem; margin-bottom: 4px; }
.product-settings .hint { font-size: .75rem; color: var(--text2); }
.product-settings .advanced { padding: 14px 18px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 12px; background: var(--glass); }
.product-settings summary { cursor: pointer; font-weight: 550; font-size: .8rem; }
.product-settings details[open] > summary { margin-bottom: 12px; }
.product-settings .eyebrow { font-size: .7rem; color: var(--text2); margin-bottom: 10px; }
.product-settings #current-title { font-size: 1.125rem; overflow-wrap: anywhere; margin-bottom: 16px; }
.product-settings .product-facts { margin-bottom: 12px; font-size: .75rem; }
.product-settings .product-facts div { display: grid; grid-template-columns: 76px minmax(0,1fr); gap: 8px; margin-bottom: 10px; }
.product-settings dt { color: var(--text2); }
.product-settings dd { margin: 0; overflow-wrap: anywhere; }
.product-settings #current-catalog { font-size: .7rem; }
.product-settings .details-panel { border: 1px solid var(--border); border-radius: 8px; background: var(--glass); }
.product-settings .details-panel section { border: 0; margin: 0; border-radius: 0; }
.product-settings .details-panel .preview-panel { border-top: 1px solid var(--border); }
.product-settings .preview-panel label { font-size: .7rem; }
.product-settings .preview-panel details { margin: 10px 0; }
.product-settings #preview-result { margin-top: 14px; font-size: .75rem; overflow-wrap: anywhere; }
.product-settings #preview-result ol { padding-left: 18px; }
.product-settings #preview-result li { margin: 6px 0; }
.product-settings .library-toolbar { display: flex; gap: 12px; margin: 18px 0; }
.product-settings .library-toolbar > select { width: 150px; }
.product-settings .search-field { position: relative; flex: 1; }
.product-settings .search-field input { padding-right: 42px; }
.product-settings .search-field button { position: absolute; right: 3px; top: 3px; border: 0; min-height: 34px; padding: 3px 10px; }
.product-settings .library-table { width: 100%; border-collapse: collapse; font-size: .8rem; table-layout: fixed; }
.product-settings .library-table th { text-align: left; color: var(--text2); font-weight: 500; font-size: .7rem; padding: 8px; background: var(--glass-b); }
.product-settings .library-table td { padding: 12px 8px; border-bottom: 1px solid var(--border); vertical-align: middle; overflow-wrap: anywhere; }
.product-settings .library-table th:first-child { width: 42%; }
.product-settings .library-table th:last-child { width: 80px; }
.product-settings .library-table .secondary { color: var(--text2); font-size: .7rem; margin-top: 4px; }
.product-settings .library-table .book-title { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.product-settings .library-pagination { display: flex; justify-content: space-between; align-items: center; margin-top: 14px; gap: 12px; }
.product-settings .library-pagination button { margin-left: 8px; }
.product-settings .badge { display: inline-block; padding: 3px 8px; border-radius: 4px; background: var(--glass-b); font-size: .65rem; color: var(--text2); }
.product-settings .empty-state { text-align: center; padding: 32px 12px; color: var(--text2); }
.product-settings #saved-version,.product-settings #adopted-version,.product-settings #wait-records { overflow-wrap: anywhere; }
.product-settings dialog,.product-picker-dialog { position: fixed; margin: auto; border: 1px solid var(--border); border-radius: 10px; background: var(--bg2); color: var(--text); padding: 0; max-width: calc(100vw - 24px); max-height: calc(100dvh - 24px); width: 620px; overflow: auto; font: inherit; }
.product-settings dialog::backdrop { background: rgba(0,0,0,.6); }
.product-settings .dialog-head,.product-settings dialog > h2 { padding: 18px 20px; margin: 0; }
.product-settings .dialog-head { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); }
.product-settings .dialog-head h2 { margin: 0; }
.product-settings .dialog-head button { min-height: 32px; padding: 0 10px; }
.product-settings .dialog-body { padding: 18px 20px; overflow-wrap: anywhere; }
.product-settings .dialog-foot { position: sticky; bottom: 0; display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; padding: 14px 20px; background: var(--bg2); border-top: 1px solid var(--border); }
.product-settings #discard-dialog > p { padding: 0 20px; }
.product-settings #library-feedback { padding: 0 20px; overflow-wrap: anywhere; }
.product-settings .side-dialog { margin: 12px 12px 12px auto; height: calc(100dvh - 24px); width: 440px; }
.product-settings .side-dialog .dialog-body { min-height: calc(100dvh - 190px); }
.product-settings .library-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.product-settings .library-fields label { grid-column: 1; }
.product-settings .library-fields input,.product-settings .library-fields select { grid-column: 2; margin-top: 8px; }
.product-settings .sr-only,.product-picker-dialog .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
.product-picker-dialog { margin: 0; max-width: none; font: .8rem/1.5 -apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif; box-shadow: 0 16px 50px rgba(0,0,0,.4); }
.product-picker-dialog::backdrop { background: transparent; }
.product-picker-dialog .picker-search { display: flex; gap: 5px; align-items: center; padding: 12px; }
.product-picker-dialog input { padding-right: 28px; }
.product-picker-dialog .picker-clear,.product-picker-dialog .picker-close { padding: 4px 8px; min-height: 32px; }
.product-picker-dialog select { display: block; width: calc(100% - 24px); margin: 0 12px; border: 0; padding: 0; background: var(--bg2); color: var(--text); font: inherit; height: 230px; overflow: auto; border-radius: 4px; }
.product-picker-dialog option { padding: 10px; border-bottom: 1px solid var(--border); }
.product-picker-dialog option:checked { background: var(--glass-b); color: var(--blue); }
.product-picker-dialog option:disabled { color: var(--text3); }
.product-picker-dialog .picker-detail { font-size: .7rem; padding: 12px; margin: 0; overflow-wrap: anywhere; min-height: 55px; color: var(--text2); }
.product-picker-dialog .picker-footer { padding: 10px 12px; display: flex; align-items: center; justify-content: space-between; gap: 8px; border-top: 1px solid var(--border); font-size: .7rem; }
html { scroll-padding-top: 110px; }
@media (max-width: 1050px) { .product-settings .rules-layout { grid-template-columns: minmax(0,1fr); }.product-settings .details-panel { display: grid; grid-template-columns: 1fr 1fr; }.product-settings .details-panel .preview-panel { border-top: 0; border-left: 1px solid var(--border); } }
@media (max-width: 600px) {
.product-settings { padding: 10px 12px 24px; }.product-settings .page-header { align-items: flex-start; flex-direction: column; gap: 8px; }.product-settings .header-actions { width: 100%; justify-content: flex-end; gap: 8px; }.product-settings #dirty-state { margin-right: auto; font-size: .65rem; }.product-settings .header-actions button { padding: 8px 10px; font-size: .75rem; }
.product-settings .status-banner { align-items: flex-start; }.product-settings .view-tabs { gap: 18px; }.product-settings section { padding: 14px; }.product-settings .mapping-columns { display: none; }.product-settings .profile-row { grid-template-columns: 1fr 1fr; gap: 10px; padding: 14px 0; }.product-settings .profile-identity { grid-column: 1 / -1; }.product-settings .profile-row .field-label { position: static; width: auto; height: auto; clip-path: none; font-size: .7rem; margin: 0 0 5px; }.product-settings .profile-description { display: none; }.product-settings .section-head { align-items: flex-start; flex-wrap: wrap; }.product-settings .section-head > .hint { font-size: .65rem; }
.product-settings .default-panel { grid-template-columns: 1fr; }.product-settings .details-panel { display: block; }.product-settings .details-panel .preview-panel { border-left: 0; border-top: 1px solid var(--border); }.product-settings .library-toolbar { flex-wrap: wrap; }.product-settings .library-toolbar > select { width: 100%; }.product-settings .library-table th,.product-settings .library-table td { padding: 8px 4px; font-size: .7rem; }.product-settings .library-table th:first-child { width: 49%; }.product-settings .library-table th:last-child { width: 52px; }.product-settings .library-table button { font-size: .7rem; padding: 4px 6px; }.product-settings .library-table .stock-col { display: none; }.product-settings .library-pagination button { padding: 6px; font-size: .7rem; }.product-settings .library-fields { display: block; }.product-settings .dialog-foot { padding: 12px; }.product-settings .dialog-body { padding: 14px; }.product-settings #library-feedback { padding: 0 14px; }
.product-picker-dialog .picker-detail { max-height: 110px; overflow: auto; }
html { scroll-padding-top: 150px; }
}
@media (forced-colors: active) { .product-settings button:focus-visible,.product-picker-dialog :focus-visible { outline-color: Highlight; }.product-settings .view-tabs button[aria-current] { border-color: Highlight; } }
.product-settings .profile-grid { display: contents; }
.product-settings .profile-grid > div { min-width: 0; }
.product-settings .preview-decision-block { border-top:1px solid var(--border); padding-top:12px; margin-top:12px; overflow-wrap:anywhere; }
.product-settings .preview-decision-block h4 { margin:0 0 8px; font-size:.8125rem; }
.product-settings .profile-row label { margin: 0; }

/* 限定全局 dashboard 表单/头部规则，避免主题样式改变工作台网格。 */
.product-settings .page-header { border: 0; border-radius: 0; margin: 0; }
.product-settings .default-panel > div { min-width: 0; }
.product-settings .details-panel { overflow: hidden; }
.product-settings .details-panel section { background: transparent; }
.product-settings .product-picker-trigger { max-width: 100%; }
.product-settings #view-rules .default-panel { grid-template-columns: minmax(180px,1fr) minmax(0,1.4fr); }
@media(max-width:600px){.product-settings #view-rules .default-panel{grid-template-columns:minmax(0,1fr);}}

```
