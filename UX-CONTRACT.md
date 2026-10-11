# 商品管理交互契约

业务证据：`docs/specs/wechat-product-link-2026-10-10.md`；服务契约由 `src/web/product_settings.py`、配置/目录/资料校验器负责。页面保存不等于发布器采用，已登记来源不等于现场平台核验，库存仅为采集时观测。此次只重构管理交互，不改变发布门禁。

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox | src/web/static/js/product_picker.js | DESIGN.md / 原 select 值 | 商品搜索弹层使用原生 size listbox；分类/状态使用 native select | tests/browser/test_product_settings_browser.py |
| Form | src/web/static/js/product_settings.js | API 验证与 CAS | 类型配置、资料草稿、影响确认 | tests/browser/test_product_settings_browser.py |
| Scrollbar | src/web/static/css/dashboard.css | dashboard 主题变量 | 对话框与列表内部滚动 | tests/browser/test_product_settings_browser.py |
| Toast | feedback / catalog-import-feedback | product_settings.js | 页面状态及局部错误 live region，不引入额外 toast | tests/browser/test_product_settings_browser.py |
| CRUD | src/web/product_settings.py | 已确认业务规格 | 草稿、保存、恢复草稿；不新增删除商品 | tests/unit/test_wechat_product_p1.py |

专题候选是独立业务变体；共享语义颜色、字号、原生 select/dialog，不复制商品选品逻辑。

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox | native select | topic_candidates.html | 类别、时间范围、规则/整理筛选、排除原因 | tests/browser/test_topic_candidates_browser.py |
| Form | src/web/static/js/topic_candidates.js | v0.2 规格 / API 验证 / CAS | 专题草稿、字段错误、失败保留、丢弃确认 | tests/browser/test_topic_candidates_browser.py |
| Scrollbar | src/web/static/css/dashboard.css | 现有语义主题 | 继承 product_settings.css 的原生 dialog 内部滚动 | tests/browser/test_topic_candidates_browser.py |
| Toast | feedback / form-feedback / action-feedback | topic_candidates.js | 页面与局部状态 live region | tests/browser/test_topic_candidates_browser.py |
| CRUD | src/web/topic_candidates.py | docs/specs/topic-keyword-tracking-architecture.md | 暂停、归档、收藏、排除；无主表写入和发布权限 | tests/unit/test_topic_candidates_api.py |

专题筛选、标题/频道查询与页码保存在 URL；中文输入结束后过滤。异步列表请求取消过期响应。重复写入禁用；冲突和服务故障保留表单。Escape 取消对话框，未保存修改需明确丢弃；焦点回到打开入口。服务端会话与 CSRF 校验不替代实名审核；真实对端仅限回环地址。搜索不自动执行或续跑，运行中暂停仍显示停止过程。

## 操作及恢复

- 默认按类型配置，商品库与执行记录可切换；`view`、商品搜索 `q`、状态 `filter` 与页码 `page` 记录在URL。切页保留草稿，不重复读取覆盖草稿。
- 商品库每页25项，本地搜索和状态筛选；清空立即生效，中文输入完成后过滤。搜索/筛选/翻页不算修改。完整商品名称、ID、来源和引用可在编辑页读取。
- 商品选择由原 select 维护配置值。弹层内搜索与提交分开；方向键和 Enter 选择，Escape 取消，焦点回到打开按钮。搜索不改变已选值；待核实资料不进入候选。弹层不直接保存或发布。
- 修改显示待保存数量。顶部保存先执行服务端影响校验，再确认CAS写入。请求期间禁用重复写入；失败保留草稿，冲突提示重新载入。无修改时禁用保存。
- 新增/编辑资料在对话框处理；加入待保存更改后回商品库，统一保存。未应用资料关闭时确认丢弃，仅丢弃该编辑，不丢其他配置草稿。
- 恢复历史先载入草稿，返回类型配置查看；再保存生成新版本。导入在弹窗执行原可靠资料校验，防止覆盖未保存草稿；未接入实时同步展示状态，不伪造可执行刷新。
- 对话框使用原生 dialog 的焦点隔离、Escape与焦点恢复，关键保存中不允许关闭。错误为文本，必填校验关联字段并定位；loading/empty/error明确，页面自然滚动。
- 主题/字号继承控制台偏好，日期固定使用 zh-CN / Asia/Shanghai。目标：语义HTML、可见焦点、手机无横向溢出，暗/亮/高对比可读。没有承诺其他未实测平台/读屏软件。
