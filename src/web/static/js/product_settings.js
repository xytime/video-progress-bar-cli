'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let publisherConnected = false, currentView, libraryAlias = null, libraryDraftDirty = false;
  let catalogItems = new Map(), baseline, baselineFields;
  let inspected = {alias:null,context:"全局默认商品"}, libraryPage = 1;
  let catalogDigest = null, importDraft = null;
  const importNote = (text, error = false) => { $('catalog-import-feedback').textContent = text; $('catalog-import-feedback').dataset.error = String(error); };
  function importControls() {
    $('catalog-file').disabled = pending;
    $('catalog-check').disabled = pending || !config || !$('catalog-file').files.length;
    $('catalog-apply').disabled = pending || dirty || !importDraft;
  }
  function invalidateImport() {
    importDraft = null; $('catalog-import-preview').replaceChildren(); importControls();
  }
  let config, digest, groups, dirty = false, pending = false, previewSequence = 0, discardAction;
  const note = (message, error = false) => { $('feedback').textContent = message; $('feedback').dataset.error = String(error); };
  const element = (tag, text) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; return el; };
  const attachmentReasons = {
    ATTACH_ENGLISH_FIRST:'英语世界当天首条要求挂载',SKIP_ENGLISH_LATER:'英语世界当天后续不挂载',
    ENGLISH_FIRST_NOT_REGISTERED:'尚未登记正式制作顺序',ATTACH_THRESHOLD:'源点赞率达到10%，要求挂载',
    SKIP_BELOW_THRESHOLD:'源点赞率低于10%，不挂载',SKIP_METRICS_UNKNOWN:'源指标未知，无法证实达标',
    SKIP_METRICS_INVALID:'源指标无效，无法证实达标',ATTACH_MANUAL:'手动指定商品，要求挂载',
    SKIP_MANUAL_NONE:'手动明确不绑定商品'
  };
  const knownValue = value => value === null || value === undefined ? '未知' : String(value);
  function attachmentDetails(attachment) {
    const fragment = document.createDocumentFragment();
    if (!attachment) { fragment.append(element('p','尚无挂载决定资料。')); return fragment; }
    const required = attachment.require_product === true ? '要求挂载' : attachment.require_product === false ? '无需挂载' : '待正式制作顺序确定';
    const intent = {AUTO:'自动规则',NONE:'手动不绑定',PRODUCT:'手动指定商品'}[attachment.product_intent] || '未确认';
    fragment.append(element('p',`商品意图：${intent} · 挂载决定：${required}`),
      element('p',`原因：${attachmentReasons[attachment.reason] || attachment.reason || '未确认'}${attachment.reason ? `（${attachment.reason}）` : ''}`));
    const metrics = attachment.metrics || {};
    const rate = metrics.like_rate_percent === null || metrics.like_rate_percent === undefined ? '未知' : `${metrics.like_rate_percent}%`;
    fragment.append(element('p',`源播放数：${knownValue(metrics.view_count)} · 源点赞数：${knownValue(metrics.like_count)} · 源点赞率：${rate}`),
      element('p',`指标状态：${{VALID:'有效',UNKNOWN:'缺失',INVALID:'无效'}[metrics.status] || '未确认'}。${attachment.product_intent === 'NONE' || attachment.product_intent === 'PRODUCT' ? '人工意图优先，不受自动首条和点赞率规则影响。' : String(attachment.reason || '').includes('ENGLISH') ? '英语世界按当天正式制作首条，不使用点赞率筛选。' : '其他自动 YouTube 视频按未四舍五入的比例判断，阈值10%。'}`));
    const production = attachment.production;
    if (production) {
      const first = production.first_task_id || (production.is_first === true ? production.task_id : null);
      fragment.append(element('p',`业务日（北京时间）：${knownValue(production.business_day)} · 本任务${production.is_first === true ? '是首条' : production.is_first === false ? '是后续任务' : '首条状态未确认'}`),
        element('p',`正式制作任务：${knownValue(production.task_id)} · 当日首条任务：${knownValue(first)}`));
      if (production.account_id) fragment.append(element('p',`内部运行范围：${production.account_id}（不代表平台账号已核实）`));
    } else fragment.append(element('p','尚无正式制作登记；预览不占每日首条名额。'));
    return fragment;
  }
  function renderPreview(result) {
    const simulation = element('div'); simulation.className = 'preview-decision-block'; simulation.id = 'preview-simulation';
    simulation.setAttribute('aria-label','当前配置模拟');
    const list = element('ol'); (result.candidates || []).forEach(p=>list.append(element('li',`${p.title} · ID ${p.product_id}`)));
    simulation.append(element('h4',result.frozen_task ? '新配置模拟（不改变已冻结任务）' : '当前配置模拟'),
      element('p',dirty ? '当前未保存表单的预览' : '当前已保存配置的预览'),
      element('p',`模拟版本：${knownValue(result.config_version)} · 摘要：${knownValue(result.config_digest)}`),attachmentDetails(result.attachment),
      element('p',result.attachment?.require_product === false ? '本次无需挂载，不执行商品选择器。以下仅为类型配置的选品模拟：' : '当前配置的选品候选顺序：'),list,
      element('p',`总时限 ${result.timeout_seconds} 秒，最多 ${result.max_attempts} 次。候选不代表平台已挂载。`));
    const blocks = [element('h3',result.video_group_label),element('p',`${result.group_reason}；选品规则：${result.matched_rule}`)];
    if (result.frozen_task) {
      const frozen = result.frozen_task, actual = element('div'); actual.className = 'preview-decision-block'; actual.id = 'preview-frozen';
      actual.setAttribute('aria-label','已冻结实际决定');
      const candidates = element('ol'); (frozen.product_decision?.candidates || []).forEach(p=>candidates.append(element('li',`${p.title} · ID ${p.product_id}`)));
      actual.append(element('h4','已冻结实际决定（重试沿用）'),
        element('p','该任务实际继续使用以下原快照。保存或预览新配置不会改变它，也不代表平台已经挂载。'),
        element('p',`冻结版本：${knownValue(frozen.config_version)} · 摘要：${knownValue(frozen.config_digest)}`),
        attachmentDetails(frozen));
      if (candidates.children.length) actual.append(element('p','冻结的商品候选顺序：'),candidates);
      else actual.append(element('p',frozen.require_product === false ? '冻结决定无需商品，不执行商品选择器。' : '冻结快照尚无商品候选资料。'));
      blocks.push(actual);
    }
    blocks.push(simulation,element('p',result.order_warning || '预览不占每日首条名额，不保存采用记录。'),
      element('p','尚未验证平台当前商品可用性或实际挂载。'));
    $('preview-result').replaceChildren(...blocks);
  }
  const stockLabel = item => item ? (item.stock === null ? '采集时库存未知' : item.stock === 0 ? '采集时缺货' : `采集时库存 ${item.stock}`) : '未在最近清单中核实';
  const detail = alias => {
    if (!alias) return '继承全局默认商品';
    const p = config.products[alias], item = catalogItems.get(p.product_id);
    return `${p.title} · ID ${p.product_id}${item ? ` · ${item.shop} · ${item.price}` : ''} · ${stockLabel(item)}`;
  };
  function choices(select, value, emptyLabel) {
    select.replaceChildren();
    if (emptyLabel) select.add(new Option(emptyLabel, ''));
    const seen = new Set();
    // 保留当前规则别名；同一平台 ID 只展示一次，同名不同 ID 仍分列。
    const entries = Object.entries(config.products).sort(([a], [b]) => Number(b === value) - Number(a === value));
    entries.forEach(([alias, p]) => {
      if (seen.has(p.product_id)) return;
      seen.add(p.product_id);
      const item = catalogItems.get(p.product_id);
      const option = new Option(`${p.title.slice(0, 26)}${p.title.length > 26 ? '…' : ''} · ${p.product_id}${item?.stock === 0 ? ' · 采集时缺货' : ''}${p.enabled ? '' : ' · 已停用'}`, alias);
      option.disabled = !p.enabled; option.title = detail(alias); option.dataset.shortTitle = config.library?.[alias]?.short_name || p.title; option.dataset.search = config.library?.[alias]?.shop || item?.shop || '';
      select.add(option);
    });
    select.value = value || '';
  }
  function dirtyCount() {
    if (!config || !baseline) return 0;
    let count = 0;
    for (const key of Object.keys(config.profiles)) if (JSON.stringify(config.profiles[key]) !== JSON.stringify(baseline.profiles[key])) count++;
    for (const key of ['default_candidates','rules']) if (JSON.stringify(config[key]) !== JSON.stringify(baseline[key])) count++;
    const aliases = new Set([...Object.keys(config.library || {}),...Object.keys(baseline.library || {})]);
    for (const key of aliases) if (JSON.stringify(config.library?.[key]) !== JSON.stringify(baseline.library?.[key])) count++;
    for(const key of new Set([...Object.keys(config.products),...Object.keys(baseline.products)])) if (JSON.stringify(config.products[key]) !== JSON.stringify(baseline.products[key]) && JSON.stringify(config.library?.[key]) === JSON.stringify(baseline.library?.[key])) count++;
    for (const [id,value] of Object.entries(baselineFields || {})) if ($(id).value !== value) count++;
    return count + Number(libraryDraftDirty);
  }
  function updateControls() {
    $('save').disabled = pending || !config || !dirty;
    $('save').setAttribute('aria-busy', String(pending));
    window.ProductPicker.refreshAll();
  }
  function setDirty() {
    const count = dirtyCount(); dirty = count > 0; previewSequence++;
    invalidateImport();
    $('dirty-state').textContent = dirty ? `${count} 处修改待保存` : '所有更改已保存';
    $('preview-result').textContent = '配置已修改，请重新预览。'; updateControls();
  }
  function inspect(alias,context) {
    inspected = {alias,context};
    const p = config.products[alias], item = p && catalogItems.get(p.product_id);
    $('current-context').textContent = context;
    $('current-title').textContent = p?.title || '使用全局默认商品';
    $('current-id').textContent = p?.product_id || '—';
    $('current-shop').textContent = config.library?.[alias]?.shop || item?.shop || '资料未提供';
    $('current-identity').textContent = p?.verified_source ? '已登记核实来源' : '待核实';
    $('current-stock').textContent = stockLabel(item);
    $('current-catalog').textContent = `最近留存清单 ${catalogItems.size} 件；库存与完整性以商品库来源信息为准。`;
  }
  function selectView(view,write = true) {
    if (!['rules','library','records'].includes(view)) view = 'rules';
    window.ProductPicker.close();
    for (const key of ['rules','library','records']) {
      $('view-'+key).hidden = key !== view;
      if (key === view) $('tab-'+key).setAttribute('aria-current','page'); else $('tab-'+key).removeAttribute('aria-current');
    }
    if (write) { const url = new URL(location.href); url.searchParams.set('view',view); window.history.replaceState(null,'',url); }
  }
  async function api(path, options = {}) {
    const response = await fetch(path, {...options, headers: {'Content-Type': 'application/json'}, signal: AbortSignal.timeout(15000)});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '数据格式不正确，请检查输入后重试。');
    return data;
  }
  function status(data) {
    publisherConnected = data.publisher_connected === true;
    $("publisher-state").textContent = publisherConnected ? "发布器已接入；实际采用以选品记录为准。" : "发布器尚未接入：当前可保存配置，实际发布尚未采用。";
    $('saved-version').textContent = `已保存版本：${data.saved_version}`;
    const last = data.last_selection;
    $('adopted-version').textContent = data.runtime_error || (last ? `最近实际选品：${last.config_version} · ${last.phase} · ${last.recorded_at}。${data.adopted_by_last_selection ? '已采用当前版本' : '尚未采用当前版本'}${last.reason ? ' · ' + last.reason : ''}` : '尚无实际选品记录；保存与预览不代表已发布。');
  }
  function productField(parent, id, label, value, empty, changed) {
    const wrap = element('div'), lab = element('label', label), select = element('select'), info = element('p', value ? detail(value) : (empty === '无额外备选' ? empty : detail(value)));
    lab.htmlFor = select.id = id; info.id = `${id}-detail`; info.className = 'product-detail';
    select.setAttribute('aria-describedby', info.id); lab.className = 'field-label sr-only'; info.classList.add('sr-only'); choices(select, value, empty);
    select.addEventListener('change', () => { changed(select.value); info.textContent = select.value ? detail(select.value) : (empty === '无额外备选' ? empty : detail(select.value)); });
    select.dataset.productPicker = ''; select.addEventListener('product-inspect', () => {inspect(select.value || config.default_candidates[0],label); document.querySelectorAll('.profile-row').forEach(row => row.dataset.current = String(row.contains(select)));});
    select.addEventListener('change', () => {inspect(select.value || config.default_candidates[0],label); window.ProductPicker.refreshAll();});
    wrap.append(lab, select, info); parent.append(wrap); window.ProductPicker.enhance(select);
  }
  function render(data) {
    currentView = data; libraryDraftDirty = false;
    previewSequence++; $('preview-result').textContent = '配置已载入，请预览选品结果。';
    config = data.config; digest = data.status.saved_digest; groups = data.groups;
    const catalog = data.catalog;
    catalogDigest = catalog?.digest ?? null;
    invalidateImport();
    catalogItems = new Map((catalog?.items || []).map(p => [p.product_id, p]));
    if (catalog) config.products = catalog.products;
    const count = new Set(Object.values(config.products).map(p => p.product_id)).size;
    $('catalog-state').textContent = catalog?.error || `已载入后台快照中的 ${catalogItems.size} 件商品，下拉框共 ${count} 件；${catalog?.completeness === 'complete' ? `导入完整性校验通过（${catalog.total_pages} 页），非平台实时核验` : '全量完整性尚未确认'}。`;
    $('catalog-state').dataset.error = String(Boolean(catalog?.error));
    $('catalog-time').textContent = catalog?.captured_at ? `采集时间：${new Date(catalog.captured_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}${catalog.account_id ? ` · 清单声明账号：${catalog.account_id}` : ''} · 来源：后台商品列表快照。当前实时清单尚未核验。` : '当前实时清单尚未核验。';
    if (config.schema_version !== 2) throw new Error('当前配置是旧格式，请先用配置工具升级为五类策略后重新载入。');
    $('profiles').replaceChildren(); $('channel-fields').replaceChildren(); $('legacy-rules').replaceChildren();
    Object.entries(groups).forEach(([key, name]) => {
      const row = element('div'), grid = element('div'); row.className = 'profile-row'; grid.className = 'profile-grid'; const identity = element('div'); identity.className='profile-identity'; identity.append(element('h3',name)); const descriptions={english_world:'英语学习与热点解读',wallstreet:'金融市场与投资观点',ted:'演讲与思想分享',ai_news:'人工智能行业动态',other:'未命中以上类型'}; const desc=element('p',descriptions[key]);desc.className='profile-description';identity.append(desc); row.append(identity,grid); $('profiles').append(row);
      ['首选商品', '备选商品'].forEach((label, index) => productField(grid, `${key}-${index}`, `${name} · ${label}`, config.profiles[key].candidates[index], index ? '无额外备选' : '继承全局默认', () => {
        if (!$(key + '-0').value) $(key + '-1').value = '';
        $(key + '-1').disabled = !$(key + '-0').value;
        config.profiles[key].candidates = [...new Set([$(key + '-0').value, $(key + '-1').value].filter(Boolean))];
        $(key + '-1-detail').textContent = $(key + '-1').value ? detail($(key + '-1').value) : '无额外备选';
      }));
      $(key + '-1').disabled = !$(key + '-0').value;
      if (['wallstreet', 'ted', 'ai_news'].includes(key)) {
        const label = element('label', `${name} · 来源频道 ID`), input = element('input');
        label.htmlFor = input.id = `${key}-channels`; input.type = 'text'; input.value = config.profiles[key].channel_ids.join(', ');
        input.addEventListener('input', () => { config.profiles[key].channel_ids = [...new Set(input.value.split(/[,，\s]+/).filter(Boolean))]; });
        $('channel-fields').append(label, input);
      }
    });
    config.rules.forEach((rule, index) => {
      // 历史频道规则仍保留；完整条件与商品可见，避免隐藏配置影响解释。
      productField($('legacy-rules'), `rule-${index}`, `其他 · ${rule.kind === 'channel' ? '频道' : '分类'} ${rule.values.join('、')}`, rule.candidates[0], null, value => { rule.candidates = [value]; });
    });
    choices($('default-product'), config.default_candidates[0]); $('default-detail').textContent = detail(config.default_candidates[0]);
    choices($('manual'), '', '沿用视频意图与自动规则');
    const waitPolicy = config.wait_policy || {base_seconds:300,max_seconds:21600,max_checks:8,lease_seconds:120};
    Object.entries(waitPolicy).forEach(([k,v]) => { $('wait-'+k).value = v; });
    $('timeout').value = config.timeout_seconds; $('attempts').value = config.max_attempts;
    status(data.status); drawLibrary(); baseline = structuredClone(config); baselineFields = Object.fromEntries(['timeout','attempts','wait-base_seconds','wait-max_seconds','wait-max_checks','wait-lease_seconds'].map(id=>[id,$(id).value])); dirty = false; $('dirty-state').textContent = '所有更改已保存'; $('editor').disabled = false; $('preview').disabled = false; document.querySelectorAll('[data-product-picker]').forEach(window.ProductPicker.enhance);inspect(config.products[inspected.alias] ? inspected.alias : config.default_candidates[0],inspected.context); updateControls();
  }
  function draft() {
    if (!config) throw new Error('请先成功载入配置。');
    const result = structuredClone(config);
    result.wait_policy = Object.fromEntries(['base_seconds','max_seconds','max_checks','lease_seconds'].map(k => [k,Number($('wait-'+k).value)]));
    result.timeout_seconds = Number($('timeout').value); result.max_attempts = Number($('attempts').value);
    $('timeout').removeAttribute('aria-invalid'); $('attempts').removeAttribute('aria-invalid');
    if (!Number.isFinite(result.timeout_seconds) || result.timeout_seconds <= 0 || result.timeout_seconds > 60) {
      $('timeout').setAttribute('aria-invalid', 'true'); $('timeout').closest('details').open = true; $('timeout').focus();
      throw new Error('总时限必须大于 0 且不超过 60 秒。');
    }
    return result;
  }
  const libraryFields = ['product_id','title','account_id','shop','merchant_appid','specification','short_name','notes','verified_source','verified_at','identity_status'];
  function refNames(alias) {
    const refs = config.default_candidates.includes(alias) ? ['全局默认'] : [];
    Object.entries(config.profiles).forEach(([key,p]) => { if (p.candidates.includes(alias)) refs.push(groups[key]); });
    config.rules.forEach(r => { if (r.candidates.includes(alias)) refs.push(r.id); });
    return refs;
  }
  function libraryRows() { return {...config.products,...(config.library || {})}; }
  function drawLibrary() {
    const search = $('library-search').value.trim().toLocaleLowerCase('zh-CN'), selected = $('library-choice').value;
    const filter = $('library-filter').value; const url=new URL(location.href); if (search) url.searchParams.set('q',search); else url.searchParams.delete('q'); if(filter!=='all') url.searchParams.set('filter',filter); else url.searchParams.delete('filter');
    const rows = Object.entries(libraryRows()).filter(([,p]) => {
      const text=[p.title,p.product_id,p.shop,p.notes,p.short_name,catalogItems.get(p.product_id)?.shop].filter(Boolean).join(' ').toLocaleLowerCase('zh-CN');
      return text.includes(search) && (filter === 'all' || (filter === 'unverified' ? p.identity_status === 'UNVERIFIED' : filter === 'enabled' ? p.enabled && p.identity_status !== 'UNVERIFIED' : p.enabled === false));
    });
    $('library-choice').replaceChildren(new Option('选择商品或新增资料', ''));
    rows.forEach(([alias,p]) => $('library-choice').add(new Option(`${p.short_name || p.title || '未命名资料'} · ${p.product_id || 'ID待核实'}`,alias)));
    $('library-choice').value = selected;
    const table = element('table');table.className='library-table';const head=element('thead'), header=element('tr');
    ['商品 / ID','状态','库存观测','操作'].forEach((t,i) => {const th=element('th',t);th.scope='col';if(i===2) th.className='stock-col';header.append(th);});head.append(header);table.append(head);
    const body=element('tbody'), total=rows.length; libraryPage=Math.max(1,Math.min(libraryPage,Math.ceil(total/25) || 1));
    rows.slice((libraryPage-1)*25,libraryPage*25).forEach(([alias,p]) => {
      const row=element('tr'), title=element('td'), name=element('div',p.short_name || p.title || '未命名资料');name.className='book-title';name.title=p.title || '';title.append(name);
      const id=element('p',p.product_id || '商品 ID 待核实');id.className='secondary';title.append(id);
      const state=element('td',p.identity_status==='UNVERIFIED'?'待核实':p.enabled?'启用':'停用'), stock=element('td',stockLabel(catalogItems.get(p.product_id)));stock.className='stock-col';
      const action=element('td'), edit=element('button','编辑');edit.type='button';edit.dataset.libraryAlias=alias;edit.setAttribute('aria-label',`编辑 ${p.short_name || p.title || '商品资料'}`); edit.onclick=()=>{$('library-choice').value=alias;editLibrary(alias);$('library-editor').showModal();$('lib-title').focus();};action.append(edit);row.append(title,state,stock,action);body.append(row);
    });table.append(body);$('library-results').replaceChildren(total?table:element('p','没有匹配的商品，请修改搜索词或筛选条件。'));
    $('library-clear').hidden=!search;$('library-count').textContent=Object.keys(libraryRows()).length;
    $('library-range').textContent=total?`第 ${(libraryPage-1)*25+1}–${Math.min(libraryPage*25,total)} 件，共 ${total} 件`:'0 件商品';
    url.searchParams.set('page',libraryPage);window.history.replaceState(null,'',url);$('library-prev').disabled=libraryPage<=1;$('library-next').disabled=libraryPage*25>=total;
  }
  function editLibrary(alias) {
    libraryAlias = alias; libraryDraftDirty = false;
    const p = libraryRows()[alias] || {};
    libraryFields.forEach(k => { $('lib-'+k).value = p[k] || (k === 'identity_status' ? 'UNVERIFIED' : ''); });
    $('lib-enabled').value = String(p.enabled !== false);
    $('library-references').textContent = alias ? `当前引用：${refNames(alias).join('、') || '无'}；内部引用 ${alias}` : '新增资料采用稳定内部引用，不自动改变默认商品。';
    $('library-feedback').textContent = '';
  }
  function rerenderDraft(next) {
    const savedBaseline=baseline,savedFields=baselineFields; render({...currentView,config:next,catalog:{...currentView.catalog,products:next.products}}); baseline=savedBaseline;baselineFields=savedFields;setDirty();
  }
  $('library-search').oninput = e => {if (!e.isComposing) {libraryPage=1;drawLibrary();}}; $('library-search').addEventListener('compositionend',()=>{libraryPage=1;drawLibrary();});
  $('library-clear').onclick=()=>{$('library-search').value='';libraryPage=1;drawLibrary();$('library-search').focus();};
  $('library-filter').onchange=()=>{libraryPage=1;drawLibrary();};
  $('library-prev').onclick=()=>{libraryPage--;drawLibrary();};$('library-next').onclick=()=>{libraryPage++;drawLibrary();};
  $('library-choice').onchange = () => {
    if (libraryDraftDirty) { $('library-choice').value = libraryAlias || ''; note('商品资料尚未应用，请先应用到草稿。', true); return; }
    editLibrary($('library-choice').value); if (!$('library-editor').open) $('library-editor').showModal();
  };
  libraryFields.concat(['enabled']).forEach(k => $('lib-'+k).addEventListener('input', () => { libraryDraftDirty = true; setDirty(); }));
  $('library-new').onclick = () => { if (libraryDraftDirty) { note('商品资料尚未应用，请先应用到草稿。', true); return; } editLibrary(null); $('library-editor').showModal(); $('lib-title').focus(); };
  $('library-toggle').onclick = () => {
    const alias = $('library-choice').value; if (!alias) return;
    const next = draft(), p = next.products[alias];
    if (!p) { $('library-feedback').textContent = '待核实资料不能启用为候选，请先核实身份。'; return; }
    p.enabled = !p.enabled; if (next.library?.[alias]) next.library[alias].enabled = p.enabled;
    rerenderDraft(next); editLibrary(alias);$('library-editor').close();
    note(`商品已在草稿中${p.enabled ? '启用' : '停用'}。${refNames(alias).length ? '引用：'+refNames(alias).join('、')+'；保存前请修复停用引用。' : ''}`);
  };
  $('library-apply').onclick = () => {
    const next = draft(), alias = libraryAlias || 'book_' + Array.from(crypto.getRandomValues(new Uint8Array(16)), x => x.toString(16).padStart(2,'0')).join('');
    const row = Object.fromEntries(libraryFields.map(k => [k,$('lib-'+k).value.trim()])); row.enabled = $('lib-enabled').value === 'true';
    if (row.identity_status === 'VERIFIED' && ['product_id','title','account_id','verified_at','verified_source'].some(k => !row[k])) {
      $('library-feedback').textContent = '已核实资料必须填写商品 ID、完整名称、发布账号、核实时间与来源。'; return;
    }
    next.library ||= {}; next.library[alias] = row;
    if (row.identity_status === 'VERIFIED') next.products[alias] = Object.fromEntries(['product_id','title','enabled','verified_at','verified_source'].map(k => [k,row[k]]));
    else delete next.products[alias];
    // 正在被引用的资料不能改成缺失身份；先调整引用后可保留为待核实。
    if (!next.products[alias] && refNames(alias).length) { $('library-feedback').textContent = '商品仍被引用：'+refNames(alias).join('、')+'。请先调整规则。'; return; }
    libraryDraftDirty = false; rerenderDraft(next); libraryAlias = alias; drawLibrary(); $('library-choice').value = alias;
    $('library-feedback').textContent = '已应用到草稿；通过保存前校验后才持久化。';$('library-editor').close();note('商品资料已加入待保存更改；点击顶部“保存更改”统一保存。');
  };
  async function loadWaits() {
    try {
      const data = await api('/api/product-settings/waits');
      $('wait-state').textContent = data.reason; $('wait-records').replaceChildren();
      if (!data.records.length) $('wait-records').append(element('p','暂无已记录的商品等待任务；不代表平台全部可售。'));
      const states = {WAITING:'等待检查',CHECKING:'检查中',CHECK_LIMIT:'检查次数已达上限',BLOCKED:'需核实',VERIFY_SUBMISSION:'先核验原作品',READY_FOR_EXISTING_GATES:'等待原有发布门禁'};
      const reasons = {PRODUCT_UNAVAILABLE:'全部候选不可用',QUOTA_EXHAUSTED:'平台额度不足',LOGIN_REQUIRED:'需要登录',AVAILABILITY_UNVERIFIED:'可用性待核验'};
      data.records.forEach(r => $('wait-records').append(element('p', `${r.task_key} · ${states[r.state] || r.state} · ${reasons[r.reason] || r.reason} · 下次检查：${new Date(r.next_check_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})} · 已检查 ${r.checks} 次`)));
    } catch(error) { $('wait-state').textContent = `等待状态未知：${error.message}`; }
  }
  async function loadVideos() {
    try {
      const data = await api('/api/product-settings/videos');
      $('video').replaceChildren(new Option('使用下面的样例上下文', ''));
      data.videos.forEach(v => $('video').add(new Option(`${v.title} · ${v.state}${v.slice_index ? ' · 分片 ' + v.slice_index : ''}`, v.preview_key)));
      $('videos-state').textContent = data.videos.length ? `显示最近 ${data.videos.length} 条任务；包含英语世界审核项。` : '暂无待发布视频，可使用样例预览。';
    } catch (error) { $('videos-state').textContent = `视频列表读取失败：${error.message} 可使用样例预览或重新载入。`; }
  }
  async function load() {
    if (pending) return; previewSequence++; pending = true; $('reload').disabled = true;
    invalidateImport();
    try { render(await api('/api/product-settings')); note('配置已载入，正在读取视频列表…'); $('editor').disabled = true; $('preview').disabled = true; await loadVideos(); await history(); await loadWaits(); note('配置已载入。'); }
    catch (error) { note(`读取失败：${error.message}`, true); }
    finally { pending = false; importControls(); $('reload').disabled = false; if (config && config.schema_version === 2) { $('editor').disabled = false; $('preview').disabled = false; } updateControls(); }
  }
  function guard(action) {
    if (!dirty) { action(); return; }
    discardAction = () => {dirty=false;action();}; $('discard-dialog').showModal(); $('keep-editing').focus();
  }
  $('keep-editing').onclick = () => $('discard-dialog').close();
  $('discard').onclick = () => { $('discard-dialog').close(); dirty = false; discardAction(); };
  $('back').onclick = event => { event.preventDefault(); guard(() => { window.location.href = '/'; }); };
  $('reload').onclick = () => guard(load);
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  const changed = event => {if (event.target.closest('.preview-panel')) return; if (!['library-search','library-choice','library-filter'].includes(event.target.id) && !event.target.id.startsWith('lib-')) setDirty();};
  $('settings-form').addEventListener('input', changed); $('settings-form').addEventListener('change', changed);
  $('default-product').onchange = () => { config.default_candidates = [$('default-product').value]; $('default-detail').textContent = detail($('default-product').value);inspect($('default-product').value,'全局默认商品'); };
  $('settings-form').onsubmit = event => event.preventDefault();
  let saveDraft = null;
  async function history() {
    try {
      const data = await api('/api/product-settings/history');
      $('revision').replaceChildren();
      data.revisions.forEach(r => { const option = new Option(`${r.version}${r.current ? '（当前）' : ''}`, r.digest); option.disabled = !!r.error; $('revision').add(option); });
      $('history-state').textContent = `保留 ${data.revisions.length} 个快照；历史从本功能启用后的保存开始累计。`;
    } catch(error) { $('history-state').textContent = `历史读取失败：${error.message}`; }
  }
  function showImpact(report) {
    const list = element('ul');
    const chain = d => d.candidates.map(p => `${p.title}（${p.product_id}）`).join(' → ');
    const effects = {UNCHANGED_FROZEN:'实际决定已冻结，继续沿用原快照',UNCHANGED_SKIP:'无需挂载，实际决定不变',UNCHANGED_MANUAL:'人工意图继续沿用，实际决定不变',UNKNOWN_PRODUCTION_ORDER:'正式制作顺序尚未确定，实际影响未知',APPLIES_TO_NEW_SELECTION:'预计影响下一次尚未冻结的选品'};
    report.changed.forEach(v => list.append(element('li', `${v.title}：${chain(v.before)} → ${chain(v.after)}；规则 ${v.before.reason} → ${v.after.reason}；预算 ${v.before.timeout_seconds}秒/${v.before.max_attempts}次 → ${v.after.timeout_seconds}秒/${v.after.max_attempts}次${v.actual_effect ? `；${effects[v.actual_effect] || v.actual_effect}` : ''}`)));
    report.unknown.forEach(v => list.append(element('li', `${v.title}：${v.reason}`)));
    const actualCount = Array.isArray(report.actual_changes) ? report.actual_changes.length : '未知';
    const orderUnknown = (report.excluded_actual || []).filter(v => v.actual_effect === 'UNKNOWN_PRODUCTION_ORDER').length;
    $('impact-result').replaceChildren(element('p', `最近 ${report.examined} 条：配置候选链变化 ${report.changed.length} 条；预计实际选品变化 ${actualCount} 条（冻结/跳过/人工指定不改）。候选链未变化 ${report.unchanged} 条，实际影响未知 ${report.unknown.length + orderUnknown} 条。`), list,
      element('p', `其他配置变化：${report.configuration_changes.join('、') || '无'}`), element('p', '候选链比较反映类型配置的变化；实际选品变化仅统计尚未冻结且需要自动挂载的任务。'), element('p', report.scope), element('p', '预览不验证平台库存，不启动发表。发布器尚未接入时，仅保存配置。'));
  }
  function busy(value) {
    pending = value; $('editor').disabled = value; $('reload').disabled = value; $('preview').disabled = value;
    $('restore-revision').disabled = value; $('catalog-refresh').disabled = value; importControls();updateControls();
  }
  $('save').onclick = async event => {
    event.preventDefault(); if (pending) return;
    if (libraryDraftDirty) { note('商品资料尚未应用，请先点击“加入待保存更改”。', true); return; }
    let candidate; try { candidate = draft(); } catch(error) { note(error.message, true); return; }
    previewSequence++; busy(true); invalidateImport(); note('正在计算保存影响…');
    try {
      const report = await api('/api/product-settings/impact', {method:'POST',body:JSON.stringify({config:candidate,expected_digest:digest})});
      saveDraft = {config:candidate,expected_digest:digest}; showImpact(report); $('impact-dialog').showModal(); $('impact-cancel').focus(); note('请核对影响后确认保存。');
    } catch(error) { note(`保存未确认：${error.message} 当前编辑内容已保留。`, true); }
    finally { busy(false); }
  };
  $('impact-cancel').onclick = () => { saveDraft = null; $('impact-dialog').close(); };
  $('impact-dialog').addEventListener('cancel', event => { if (pending) {event.preventDefault();return;} saveDraft = null; });
  $('impact-confirm').onclick = async () => {
    if (pending || !saveDraft) return;
    busy(true); $('impact-confirm').disabled = true; $('impact-cancel').disabled = true; note('正在保存配置…');
    try {
      const data = await api('/api/product-settings', {method:'PUT',body:JSON.stringify(saveDraft)});
      render(data); saveDraft = null; note(publisherConnected ? '配置已保存；下一次开始选品时采用。在途任务继续使用原快照。' : '配置已保存；发布器尚未接入，当前实际选品不会改变。');
      await history();
    } catch(error) { note(`保存未确认：${error.message} 当前编辑内容已保留。`, true); }
    finally { $('impact-dialog').close(); busy(false); $('impact-confirm').disabled = false; $('impact-cancel').disabled = false; }
  };
  $('restore-revision').onclick = () => {
    if (pending) return;
    guard(async () => {
      busy(true);
      try {
        const data = await api('/api/product-settings/history/restore-draft', {method:'POST',body:JSON.stringify({digest:$('revision').value,expected_digest:digest})});
        const current = await api('/api/product-settings');
        if (current.status.saved_digest !== digest) throw new Error('当前版本已更新，请重新载入');
        // 历史草稿保留自己的启停状态，不能被当前目录合并覆盖。
        const savedBaseline=baseline,savedFields=baselineFields;render({...current,config:data.config,catalog:{...current.catalog,products:data.config.products}});baseline=savedBaseline;baselineFields=savedFields;setDirty();$('history-dialog').close();selectView('rules');
        note('历史版本已载入为恢复草稿；检查类型配置后点击“保存更改”。');
      } catch(error) { note(`恢复失败：${error.message}`, true); }
      finally { busy(false); }
    });
  };
  $('catalog-refresh').onclick = async () => {
    if (pending) return; busy(true);
    try { const data = await api('/api/product-settings/catalog/refresh', {method:'POST'}); $('refresh-state').textContent = data.reason; }
    catch(error) { $('refresh-state').textContent = error.message; }
    finally { busy(false); }
  };
  $('catalog-file').onchange = () => { invalidateImport(); importNote('请先校验文件；当前清单尚未改变。'); };
  async function catalogAction(apply) {
    if (pending) return;
    if (dirty) { importNote('类型配置有未保存修改，请先保存或重新载入，再校验清单。', true); return; }
    const file = $('catalog-file').files[0];
    if (!file || file.size > 5000000) { invalidateImport(); importNote('请选择不超过 5 MB 的 JSON 文件。', true); return; }
    if (apply && !importDraft) return;
    pending = true; previewSequence++; importControls(); updateControls();
    $('editor').disabled = true; $('reload').disabled = true; $('preview').disabled = true;
    try {
      const body = apply ? importDraft : {content: await file.text(), expected_catalog_digest: catalogDigest, expected_policy_digest: digest};
      importNote(apply ? '正在导入清单…' : '正在校验清单…');
      const result = await api(`/api/product-settings/catalog/${apply ? 'import' : 'preview'}`, {method:'POST', body:JSON.stringify(body)});
      if (apply) {
        render(result); $('catalog-file').value = '';
        importNote(`已导入 ${result.import_report.total_items} 件商品，所有下拉框已更新；类型匹配与默认商品未修改。当前平台清单仍未实时核验。`);
      } else {
        importDraft = body;
        const wrap = $('catalog-import-preview'); wrap.replaceChildren(
          element('p', `声明账号：${result.account_id} · 采集时间：${new Date(result.captured_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})} · ${result.total_pages} 页 / ${result.total_items} 件商品。`),
          element('p', `新增 ${result.added.length} 件，资料变化 ${result.updated.length} 件，原清单中有 ${result.missing.length} 件未出现。已有规则引用保留，不推断下架。`));
        if (result.account_first_import) wrap.append(element('p', '首次登记清单账号，请核对与当前发布账号一致；系统尚未向平台核验账号身份。'));
        for (const [title, items] of [['新增商品',result.added],['资料变化',result.updated],['新清单中未出现',result.missing]]) {
          if (!items.length) continue;
          const details = element('details'), list = element('ul'); details.append(element('summary', `${title}（${items.length}）`));
          items.forEach(p => list.append(element('li', `${p.title} · ID ${p.product_id} · ${p.shop} · ${p.price} · ${stockLabel(p)}`)));
          details.append(list); wrap.append(details);
        }
        importNote('文件完整性校验通过，尚未导入。请核对账号和变更后点击“确认导入清单”。');
      }
    } catch (error) {
      invalidateImport();
      importNote(`${apply ? '导入结果未确认，请重新载入核对' : '校验失败，旧清单未改变'}：${error.message}`, true);
    } finally {
      pending = false; importControls(); $('editor').disabled = false; $('reload').disabled = false; $('preview').disabled = false; updateControls();
    }
  }
  $('catalog-check').onclick = () => catalogAction(false);
  $('catalog-apply').onclick = () => catalogAction(true);
  ['video', 'manual', 'content-type', 'channel', 'category', 'topic'].forEach(id => $(id).addEventListener('input', () => { previewSequence++; $('preview-result').textContent = '上下文已修改，请重新预览。'; }));
  $('video').onchange = () => { $('sample-context').hidden = Boolean($('video').value); };
  $('preview').onclick = async () => {
    const sequence = ++previewSequence; $('preview').disabled = true;
    try {
      const body = {config: draft(), video_key: $('video').value || null, product_alias: $('manual').value || null,
        context: {content_type: $('content-type').value, source_channel_id: $('channel').value.trim() || null, category: $('category').value || null, product_topic: $('topic').value || null}};
      $('preview-result').textContent = '正在计算选品结果…';
      const result = await api('/api/product-settings/preview', {method: 'POST', body: JSON.stringify(body)});
      if (sequence !== previewSequence) return;
      renderPreview(result);
    } catch (error) { if (sequence === previewSequence) $('preview-result').textContent = `预览失败：${error.message}`; }
    finally { if (!pending) $('preview').disabled = false; }
  };
  $('default-product').addEventListener('product-inspect',()=>inspect($('default-product').value,'全局默认商品'));
  document.querySelectorAll('[data-view]').forEach(button=>button.onclick=()=>selectView(button.dataset.view));
  $('runtime-link').onclick=()=>selectView('records');
  $('history-open').onclick=()=>{$('history-dialog').showModal();$('revision').focus();};
  $('catalog-open').onclick=()=>{$('catalog-dialog').showModal();$('catalog-dialog').querySelector('details').open=true;};
  function closeLibrary() {
    if (pending) return;
    if (libraryDraftDirty) {
      discardAction=()=>{libraryDraftDirty=false;editLibrary(libraryAlias);setDirty();$('library-editor').close();};
      $('discard-dialog').showModal();$('keep-editing').focus();
    } else $('library-editor').close();
  }
  ['history-dialog','catalog-dialog'].forEach(id=>$(id).addEventListener('cancel',e=>{if(pending) e.preventDefault();}));
  $('library-editor').addEventListener('cancel',e=>{e.preventDefault();closeLibrary();});
  document.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>{if(button.dataset.close==='library-editor') closeLibrary();else if (!pending) $(button.dataset.close).close();});
  $('discard').onclick=()=>{$('discard-dialog').close();discardAction();};
  selectView(new URL(location.href).searchParams.get('view'),false);
  const params=new URL(location.href).searchParams; $('library-search').value=params.get('q') || '';if(['all','enabled','disabled','unverified'].includes(params.get('filter'))) $('library-filter').value=params.get('filter');libraryPage=Math.max(1,Number(params.get('page')) || 1);
  document.querySelectorAll('.product-settings button').forEach(button=>{if(button.id!=='save') button.disabled=false;});
  load();
})();
