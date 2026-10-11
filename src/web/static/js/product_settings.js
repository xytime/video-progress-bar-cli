'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let publisherConnected = false;
  let catalogItems = new Map();
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
      option.disabled = !p.enabled; option.title = detail(alias);
      select.add(option);
    });
    select.value = value || '';
  }
  function setDirty() {
    dirty = true; previewSequence++;
    invalidateImport();
    $('dirty-state').textContent = '有未保存修改';
    $('preview-result').textContent = '配置已修改，请重新预览。';
  }
  async function api(path, options = {}) {
    const response = await fetch(path, {...options, headers: {'Content-Type': 'application/json'}, signal: AbortSignal.timeout(15000)});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '数据格式不正确，请检查输入后重试。');
    return data;
  }
  function status(data) {
    publisherConnected = data.publisher_connected === true;
    $("publisher-state").textContent = publisherConnected ? "发布器已接入；实际采用以选品记录为准。" : "配置中心已上线，当前发布器尚未接入五类配置。此处可保存和预览，暂不改变实际发布选品。";
    $('saved-version').textContent = `已保存版本：${data.saved_version}`;
    const last = data.last_selection;
    $('adopted-version').textContent = data.runtime_error || (last ? `最近实际选品：${last.config_version} · ${last.phase} · ${last.recorded_at}。${data.adopted_by_last_selection ? '已采用当前版本' : '尚未采用当前版本'}${last.reason ? ' · ' + last.reason : ''}` : '尚无实际选品记录；保存与预览不代表已发布。');
  }
  function productField(parent, id, label, value, empty, changed) {
    const wrap = element('div'), lab = element('label', label), select = element('select'), info = element('p', value ? detail(value) : (empty === '无额外备选' ? empty : detail(value)));
    lab.htmlFor = select.id = id; info.id = `${id}-detail`; info.className = 'product-detail';
    select.setAttribute('aria-describedby', info.id); choices(select, value, empty);
    select.addEventListener('change', () => { changed(select.value); info.textContent = select.value ? detail(select.value) : (empty === '无额外备选' ? empty : detail(select.value)); });
    wrap.append(lab, select, info); parent.append(wrap);
  }
  function render(data) {
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
    $('catalog-time').textContent = catalog?.captured_at ? `采集时间：${new Date(catalog.captured_at).toLocaleString('zh-CN')}${catalog.account_id ? ` · 清单声明账号：${catalog.account_id}` : ''} · 来源：后台商品列表快照。当前实时清单尚未核验。` : '当前实时清单尚未核验。';
    if (config.schema_version !== 2) throw new Error('当前配置是旧格式，请先用配置工具升级为五类策略后重新载入。');
    $('profiles').replaceChildren(); $('channel-fields').replaceChildren(); $('legacy-rules').replaceChildren();
    Object.entries(groups).forEach(([key, name]) => {
      const row = element('div'), grid = element('div'); row.className = 'profile-row'; grid.className = 'profile-grid';
      row.append(element('h3', name), grid); $('profiles').append(row);
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
    choices($('manual'), '', '按类型自动选择');
    $('timeout').value = config.timeout_seconds; $('attempts').value = config.max_attempts;
    status(data.status); dirty = false; $('dirty-state').textContent = '尚未修改'; $('editor').disabled = false; $('preview').disabled = false;
  }
  function draft() {
    if (!config) throw new Error('请先成功载入配置。');
    const result = structuredClone(config);
    result.timeout_seconds = Number($('timeout').value); result.max_attempts = Number($('attempts').value);
    $('timeout').removeAttribute('aria-invalid'); $('attempts').removeAttribute('aria-invalid');
    if (!Number.isFinite(result.timeout_seconds) || result.timeout_seconds <= 0 || result.timeout_seconds > 60) {
      $('timeout').setAttribute('aria-invalid', 'true'); $('timeout').closest('details').open = true; $('timeout').focus();
      throw new Error('总时限必须大于 0 且不超过 60 秒。');
    }
    return result;
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
    try { render(await api('/api/product-settings')); note('配置已载入，正在读取视频列表…'); $('editor').disabled = true; $('preview').disabled = true; await loadVideos(); note('配置已载入。'); }
    catch (error) { note(`读取失败：${error.message}`, true); }
    finally { pending = false; importControls(); $('reload').disabled = false; if (config && config.schema_version === 2) { $('editor').disabled = false; $('preview').disabled = false; } }
  }
  function guard(action) {
    if (!dirty) { action(); return; }
    discardAction = action; $('discard-dialog').showModal(); $('keep-editing').focus();
  }
  $('keep-editing').onclick = () => $('discard-dialog').close();
  $('discard').onclick = () => { $('discard-dialog').close(); dirty = false; discardAction(); };
  $('back').onclick = event => { event.preventDefault(); guard(() => { window.location.href = '/'; }); };
  $('reload').onclick = () => guard(load);
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  $('settings-form').addEventListener('input', setDirty);
  $('settings-form').addEventListener('change', setDirty);
  $('default-product').onchange = () => { config.default_candidates = [$('default-product').value]; $('default-detail').textContent = detail($('default-product').value); };
  $('settings-form').onsubmit = event => event.preventDefault();
  $('save').onclick = async event => {
    event.preventDefault(); if (pending) return;
    let candidate; try { candidate = draft(); } catch (error) { note(error.message, true); return; }
    previewSequence++; pending = true; $('editor').disabled = true; $('reload').disabled = true; $('preview').disabled = true; $('save').setAttribute('aria-busy', 'true'); note('正在保存配置…');
    invalidateImport();
    try { const data = await api('/api/product-settings', {method: 'PUT', body: JSON.stringify({config: candidate, expected_digest: digest})}); render(data); note(publisherConnected ? '配置已保存；下一次开始选品时采用。在途任务继续使用原快照。' : '配置已保存；发布器尚未接入，当前实际选品不会改变。'); }
    catch (error) { note(`保存未确认：${error.message} 当前编辑内容已保留。`, true);
      if (error.message.includes('不可达')) { $('editor').disabled = false; $('attempts').setAttribute('aria-invalid','true'); $('attempts').closest('details').open = true; $('attempts').focus(); }
    }
    finally { pending = false; importControls(); $('editor').disabled = false; $('reload').disabled = false; $('preview').disabled = false; $('save').removeAttribute('aria-busy'); }
  };
  $('catalog-file').onchange = () => { invalidateImport(); importNote('请先校验文件；当前清单尚未改变。'); };
  async function catalogAction(apply) {
    if (pending) return;
    if (dirty) { importNote('类型配置有未保存修改，请先保存或重新载入，再校验清单。', true); return; }
    const file = $('catalog-file').files[0];
    if (!file || file.size > 5000000) { invalidateImport(); importNote('请选择不超过 5 MB 的 JSON 文件。', true); return; }
    if (apply && !importDraft) return;
    pending = true; previewSequence++; importControls();
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
          element('p', `声明账号：${result.account_id} · 采集时间：${new Date(result.captured_at).toLocaleString('zh-CN')} · ${result.total_pages} 页 / ${result.total_items} 件商品。`),
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
      pending = false; importControls(); $('editor').disabled = false; $('reload').disabled = false; $('preview').disabled = false;
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
      const list = element('ol'); result.candidates.forEach(p => list.append(element('li', `${p.title} · ID ${p.product_id}`)));
      $('preview-result').replaceChildren(element('h3', result.video_group_label), element('p', `${result.group_reason}；选品规则：${result.matched_rule}`), element('p', dirty ? '当前未保存表单的预览' : '当前已保存配置的预览'), list,
        element('p', `总时限 ${result.timeout_seconds} 秒，最多 ${result.max_attempts} 次。尚未验证平台可用性或实际挂载。`));
    } catch (error) { if (sequence === previewSequence) $('preview-result').textContent = `预览失败：${error.message}`; }
    finally { if (!pending) $('preview').disabled = false; }
  };
  ['reload','save','keep-editing','discard'].forEach(id => { $(id).disabled = false; });
  load();
})();
