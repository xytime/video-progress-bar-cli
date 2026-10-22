/** 原视频发布时间：所有列表共用的六档新鲜度字段。
 * Modification History: 1.0.0 | 2026-10-22 | Codex | 统一相对时间、日期降级、异常状态与定时刷新。
 */
(() => {
  'use strict';
  const DAY = 86400000;
  const tiers = ['fresh', 'green', 'yellow', 'orange', 'rust', 'old'];
  function calendarDate(value) {
    const raw = String(value || '').trim();
    const match = /^(\d{4})-?(\d{2})-?(\d{2})$/.exec(raw);
    if (!match) return null;
    const [, year, month, day] = match.map(Number);
    const date = new Date(Date.UTC(year, month - 1, day));
    return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day ? date : null;
  }
  function describe(publishedAt, uploadDate, now = Date.now()) {
    const raw = String(publishedAt || uploadDate || '').trim();
    if (!raw) return {tier: 'unknown', age: '时间未知', detail: '未提供原视频发布时间'};
    const dateOnly = calendarDate(raw);
    if (dateOnly) {
      const today = new Date(new Date(now).toISOString().slice(0, 10) + 'T00:00:00Z');
      const days = (today - dateOnly) / DAY;
      if (days < 0) return {tier: 'unknown', age: '时间异常', detail: '来源日期晚于当前日期：' + raw};
      return {tier: tiers[days < 1 ? 0 : days < 2 ? 1 : days < 3 ? 2 : days < 7 ? 3 : days < 10 ? 4 : 5],
        age: days === 0 ? '约今天' : `约 ${days} 天前`, detail: '来源仅提供日期，按 UTC 日期估算，无法精确到小时：' + raw};
    }
    const instant = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}.*(?:Z|[+-]\d{2}:\d{2})$/i.test(raw) ? new Date(raw) : null;
    if (!instant || !Number.isFinite(instant.getTime()) || !calendarDate(raw.slice(0, 10)))
      return {tier: 'unknown', age: '时间异常', detail: '来源发布时间格式无效或缺少时区：' + raw};
    const elapsed = now - instant.getTime();
    if (elapsed < 0) return {tier: 'unknown', age: '时间异常', detail: '来源发布时间晚于当前时间：' + raw};
    const days = elapsed / DAY, hours = elapsed / 3600000;
    const age = elapsed < 60000 ? '刚刚' : hours < 1 ? `${Math.floor(elapsed / 60000)} 分钟前`
      : hours < 24 ? `${Math.floor(hours)} 小时前` : `${days.toFixed(1)} 天前`;
    return {tier: tiers[days < 1 ? 0 : days < 2 ? 1 : days < 3 ? 2 : days < 7 ? 3 : days < 10 ? 4 : 5], age,
      detail: '原视频发布时间（北京时间）：' + instant.toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false})};
  }
  function paint(element) {
    const value = describe(element.dataset.sourcePublishedAt, element.dataset.sourceDate);
    element.dataset.freshness = value.tier;
    element.textContent = `${element.dataset.sourceLabel || '原始发布'} ${value.age}`;
    element.title = value.detail;
    element.setAttribute('aria-label', `${element.textContent}；${value.detail}`);
  }
  function create(publishedAt, uploadDate, label = '原始发布') {
    const element = document.createElement('span');
    element.className = 'source-age';
    element.dataset.sourcePublishedAt = publishedAt || '';
    element.dataset.sourceDate = uploadDate || '';
    element.dataset.sourceLabel = label;
    paint(element);
    return element;
  }
  function refresh() { document.querySelectorAll('.source-age').forEach(paint); }
  window.SourcePublication = {create, describe, refresh, html: (...args) => create(...args).outerHTML};
  // 仅更新本地文本，不请求接口，也不重绘列表或打断焦点。
  setInterval(refresh, 60000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
})();
