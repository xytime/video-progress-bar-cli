'use strict';
// 可搜索商品选择器：原 select 保持值契约；弹层使用浏览器原生 listbox 键盘语义。
(() => {
  const controls = new Map();
  let active = null;
  const dialog = document.createElement('dialog'); dialog.className = 'product-picker-dialog';
  dialog.setAttribute('aria-label', '选择商品');
  dialog.innerHTML = '<div class="picker-search"><label for="picker-search" class="sr-only">搜索商品名称、ID、店铺</label><input id="picker-search" type="search" placeholder="搜索商品名称、ID、店铺" autocomplete="off"><button type="button" class="picker-clear" aria-label="清空商品搜索" hidden>×</button><button type="button" class="picker-close" aria-label="关闭商品选择">×</button></div><label for="picker-list" class="sr-only">匹配商品</label><select id="picker-list" size="7"></select><p class="picker-detail"></p><div class="picker-footer"><span class="picker-count" role="status"></span><button type="button" class="picker-apply">使用此商品</button></div>';
  document.body.append(dialog);
  const search = dialog.querySelector('input'), list = dialog.querySelector('select');
  const clear = dialog.querySelector('.picker-clear'), apply = dialog.querySelector('.picker-apply');
  function refresh(select) {
    const button = controls.get(select); if (!button) return;
    button.querySelector('span').textContent = select.selectedOptions[0]?.dataset.shortTitle || select.selectedOptions[0]?.textContent || '选择商品';
    button.disabled = select.disabled || !!select.closest('fieldset:disabled');
    button.title = select.selectedOptions[0]?.title || button.textContent;
  }
  function describe() {
    dialog.querySelector('.picker-detail').textContent = list.selectedOptions[0]?.title || '没有匹配的商品，请修改搜索词。';
    apply.disabled = !list.selectedOptions.length || list.selectedOptions[0].disabled;
  }
  function filter() {
    if (!active) return;
    const q = search.value.trim().toLocaleLowerCase('zh-CN'), old = list.value;
    const all = [...active.options], matches = all.filter(o => !q || `${o.textContent} ${o.title} ${o.dataset.search || ''}`.toLocaleLowerCase('zh-CN').includes(q));
    list.replaceChildren(...matches.map(o => o.cloneNode(true)));
    const selected = matches.find(o => o.value === old && !o.disabled) || matches.find(o => o.value === active.value && !o.disabled) || matches.find(o => !o.disabled);
    list.value = selected?.value ?? '__none__';
    clear.hidden = !q; dialog.querySelector('.picker-count').textContent = matches.length ? `显示 ${matches.length} / ${all.length} 项` : '没有匹配的商品';
    describe();
  }
  function position() {
    if (!active || !dialog.open) return;
    const r = controls.get(active).getBoundingClientRect();
    // 长中文书名需要更多空间；窄屏采用整页对话框，均保留原生焦点隔离。
    const width = Math.min(Math.max(r.width, 380), innerWidth - 24);
    dialog.style.width = `${width}px`; dialog.style.maxHeight = `${Math.max(240,innerHeight-24)}px`;
    const height = Math.min(dialog.scrollHeight, innerHeight-24);
    dialog.style.left = `${Math.min(Math.max(12,r.left),innerWidth-width-12)}px`;
    dialog.style.top = `${Math.max(12,Math.min(r.bottom+6,innerHeight-height-12))}px`;
  }
  function close() { if (dialog.open) dialog.close(); }
  function commit() {
    if (!active || !list.selectedOptions.length || list.selectedOptions[0].disabled) return;
    const select = active; select.value = list.value;
    select.dispatchEvent(new Event('change', {bubbles:true})); refresh(select); close();
  }
  function open(select) {
    if (controls.get(select).disabled) return;
    active = select; search.value = ''; list.value = select.value; filter(); dialog.showModal(); position(); search.focus();
    select.dispatchEvent(new Event('product-inspect', {bubbles:true}));
  }
  function enhance(select) {
    if (controls.has(select)) { refresh(select); return; }
    const button = document.createElement('button'); button.type = 'button'; button.className = 'product-picker-trigger'; button.id = `${select.id}-picker`;
    button.innerHTML = '<span></span><span aria-hidden="true">⌄</span>'; button.setAttribute('aria-haspopup','dialog');
    const label = select.labels[0];
    if (label) { label.id ||= `${select.id}-label`; button.setAttribute('aria-labelledby', `${label.id} ${button.id}-value`); button.querySelector('span').id = `${button.id}-value`; }
    if (select.hasAttribute('aria-describedby')) button.setAttribute('aria-describedby',select.getAttribute('aria-describedby'));
    select.hidden = true; select.after(button); controls.set(select,button);
    button.onclick = () => open(select);
    button.addEventListener('keydown', e => {if (e.key==='ArrowDown' || e.key==='ArrowUp') {e.preventDefault();open(select);}});
    select.addEventListener('change', () => refresh(select));
    refresh(select);
  }
  search.addEventListener('input', e => { if (!e.isComposing) filter(); }); search.addEventListener('compositionend',filter);
  clear.onclick = () => {search.value='';filter();search.focus();};
  search.addEventListener('keydown', e => {if (e.isComposing) return; if (e.key==='ArrowDown') {e.preventDefault();list.focus();} else if (e.key==='Enter') {e.preventDefault();commit();}});
  list.addEventListener('change',describe);
  list.addEventListener('click', e => {if (e.target.tagName==='OPTION') commit();});
  list.addEventListener('keydown', e => {if (e.key==='Enter' && !e.isComposing) {e.preventDefault();commit();}});
  apply.onclick = commit; dialog.querySelector('.picker-close').onclick = close;
  // 原生 search 的 Escape 默认先清空文本；选择器统一将其作为取消并归还焦点。
  dialog.addEventListener('keydown', e => {if (e.key==='Escape' && !e.isComposing) {e.preventDefault();close();}});
  dialog.addEventListener('click', e => {if (e.target===dialog) {const r=dialog.getBoundingClientRect();if (e.clientX<r.left || e.clientX>r.right || e.clientY<r.top || e.clientY>r.bottom) close();}});
  dialog.addEventListener('close', () => {const button=controls.get(active);active=null;button?.focus();});
  window.addEventListener('resize',position);
  window.ProductPicker = {enhance,close,refreshAll:()=> {for(const select of controls.keys()) {if(select.isConnected) refresh(select);else controls.delete(select);}}};
})();
