'use strict';
// 手动任务商品意图：只提交服务端别名，由服务端核实完整身份。
(() => {
  const select = document.getElementById('video-product');
  if (!select) return;
  const status = document.getElementById('manual-products-state');
  const detail = document.getElementById('manual-product-detail');
  const retry = document.getElementById('manual-products-retry');
  let catalog = null, loading = false, submitting = false, ready = false;
  window.ProductPicker.enhance(select);

  function controls() {
    select.disabled = submitting || loading;
    retry.disabled = submitting || loading;
    window.ProductPicker.refreshAll();
  }
  function describe() {
    const product = catalog?.products?.find(p => p.alias === select.value);
    detail.textContent = product
      ? `${product.title} · 商品 ID ${product.product_id} · 店铺 ${product.shop || '未登记'}${product.verification_note ? ` · ${product.verification_note}` : ''}${product.selectable ? '' : ` · ${product.reason || '不可选择'}`}`
      : select.value ? `此前指定商品：${select.selectedOptions[0]?.title || select.value}。当前清单无法核实，请重新选择或明确不绑定。`
      : '当前任务不绑定商品；不会由自动规则或默认商品补挂。';
  }
  function label(value, fallback) {
    if (typeof value === 'string') return value;
    return value?.label || value?.status || fallback;
  }
  function captured(value) {
    const date = value ? new Date(value) : null;
    return date && Number.isFinite(date.getTime())
      ? `${date.toLocaleString('zh-CN', {timeZone:'Asia/Shanghai',hour12:false})}（北京时间）`
      : '未登记';
  }
  async function load() {
    if (loading || submitting) return;
    loading = true; ready = false; controls();
    status.textContent = '正在加载商品清单；可按默认不绑定加入队列。';
    retry.hidden = true;
    try {
      const response = await fetch('/api/products/manual-options');
      const data = await response.json();
      if (!response.ok || !Array.isArray(data.products)) throw new Error('未收到可靠商品清单');
      const previous = select.value;
      const previousOption = select.selectedOptions[0];
      catalog = data;
      const none = new Option('不绑定商品（默认）', '');
      none.dataset.shortTitle = '不绑定商品（默认）';
      const options = data.products.map(product => {
        const reason = product.selectable ? (product.verification_note ? ' · 待发布会话核验' : '') : ` · 不可选：${product.reason || '身份或上架状态未核实'}`;
        const option = new Option(`${product.title} · ID ${product.product_id || '未登记'} · ${product.shop || '店铺未登记'}${reason}`, product.alias);
        option.disabled = product.selectable !== true;
        option.title = option.textContent;
        option.dataset.shortTitle = product.title;
        option.dataset.search = `${product.shop || ''} ${product.product_id || ''}`;
        return option;
      });
      if (previous && !options.some(option => option.value === previous)) {
        const unavailable = new Option(`${previousOption?.textContent || previous} · 当前清单无法核实`,previous);
        unavailable.disabled = true; unavailable.title = unavailable.textContent;
        options.push(unavailable);
      }
      select.replaceChildren(none, ...options);
      select.value = previous;
      ready = true;
      status.textContent = `账号 ${data.account_id || '未登记'} · 来源 ${label(data.source,'未登记')} · 采集 ${captured(data.captured_at)} · 完整性 ${label(data.completeness,'未核实')} · ${data.products.length} 件。当前清单不代表平台实时全量核验。${!data.account_id ? '有精确身份的历史商品可指定；发布时须在当前会话核实 ID、全名和有效性。不绑定商品仍可提交。' : ''}${data.error ? ` ${data.error}` : ''}`;
      retry.textContent = '重新读取清单';
    } catch (_) {
      status.textContent = '商品清单读取失败。可重试；默认不绑定仍可加入队列，已填输入和选择已保留。';
      retry.textContent = '重试读取商品';
    } finally {
      loading = false; retry.hidden = false; controls(); describe();
    }
  }
  function intent() {
    if (!select.value) return {product_intent:'NONE',product_alias:null};
    const option = select.selectedOptions[0];
    if (!ready || !option || option.disabled) throw new Error('所选商品当前不可用，请重新读取清单或选择不绑定商品。');
    return {product_intent:'PRODUCT',product_alias:select.value};
  }
  function setSubmitting(value) {
    submitting = value;
    if (value) window.ProductPicker.close();
    document.getElementById('manual-video-fields').disabled = value;
    controls();
  }
  function reset() { select.value = ''; describe(); window.ProductPicker.refreshAll(); }
  function taskText(task) {
    const intent = task.product_intent || 'AUTO';
    const mode = intent === 'NONE' ? '不绑定商品' : intent === 'PRODUCT' ? '指定商品' : '自动挂载规则';
    let decision = task.product_decision;
    if (typeof decision === 'string') { try { decision = JSON.parse(decision); } catch (_) { decision = null; } }
    const title = task.product_title || decision?.product_title;
    const id = task.product_id || decision?.product_id;
    const labels = {
      ATTACH_ENGLISH_FIRST:'英语世界当天首条要求挂载',SKIP_ENGLISH_LATER:'英语世界当天后续不挂载',
      ATTACH_THRESHOLD:'源点赞率达标，要求挂载',SKIP_BELOW_THRESHOLD:'源点赞率低于10%，不挂载',
      SKIP_METRICS_UNKNOWN:'源指标无法证实达标，不挂载',ATTACH_MANUAL:'手动指定商品，要求挂载',
      SKIP_MANUAL_NONE:'手动明确不绑定商品'
    };
    const reason = decision?.reason || decision?.reason_code;
    return `${mode}${title ? ` · ${title}` : ''}${id ? ` · ID ${id}` : ''}${reason ? ` · ${labels[reason] || reason}` : ' · 尚无商品决策记录'}。此处是任务选择与决策，不代表平台已挂载。`;
  }
  select.addEventListener('change', describe);
  retry.addEventListener('click', load);
  window.ManualProducts = {intent,setSubmitting,reset,taskText};
  load();
})();
