# 商品管理交互契约

业务证据：`docs/specs/wechat-product-link-2026-10-10.md`；服务契约由 `src/web/product_settings.py`、配置/目录/资料校验器负责。页面保存不等于发布器采用，已登记来源不等于现场平台核验，库存仅为采集时观测。此次只重构管理交互，不改变发布门禁。

生词片尾是独立配置变体，使用原生 checkbox/select/dialog，复用现有表单视觉。配置事实源为 `config/vocabulary_outro.json`，接口与草稿所有者分别为 `src/web/vocabulary_outro_settings.py`、`src/web/static/js/vocabulary_outro_settings.js`。CAS 冲突保留草稿并要求重新载入，独立只读重试不清除写入错误；过期预览不覆盖新表单。离开及重新载入需确认丢弃，Escape 保留草稿并恢复焦点。记录、最近任务和配置的读取分别反馈。保存只影响未开始片尾步骤的任务，冻结记录不代表上传/发布。独立英语世界学习卡不经过此步骤，实际任务预览明确标注不适用。验证所有者为 `tests/browser/test_vocabulary_outro_settings_browser.py`。

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

## 共享工作台 v0.3

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Navigation | src/web/static/js/console_navigation.js | docs/specs/dashboard-home-ia-v0.3.md | 桌面侧栏、移动 dialog 共享一份导航 | tests/browser/test_dashboard_workspace.py |
| Layout | src/web/static/css/console_workspace.css | DESIGN.md / dashboard.css 语义变量 | 总览、列表、商品与专题共享外框 | tests/browser/test_dashboard_workspace.py |
| Readonly overview | src/web/static/js/dashboard_workspace.js | 现有列表 total_count；只读 capabilities | 成功、旧数据、空态、失败 | tests/browser/test_dashboard_workspace.py |

根路径 view/tab/search/size/page 及全部既有筛选由 URL 恢复；旧 tab 链接仍支持。导航不提交业务操作，离开商品页复用现有草稿确认；专题模态编辑保持原焦点隔离。根路径内部切换保留手动表单值。首页点击数字进入同口径的全时间列表，受理与公开分开。404/不可用候选禁用入口并保留说明；OFF 仍可进入管理页面。


## v0.3.1 已确认增补

依据 `docs/specs/dashboard-home-fixes-v0.3.1.md`。专题状态、候选读取和写操作使用独立反馈域；只读重试不得清除保存冲突或草稿。同域恢复清旧错；12 秒读取超时、请求世代与筛选上下文防止旧响应覆盖。状态未核实时禁止依赖旧状态写入或发起搜索，更换筛选失败不保留旧条件候选。

首页流程概览按父任务入库批次与北京时间显示；交集分子/同集合分母，零分母为“—”。本地提交/完成不证明平台公开，updated_at 只称最近记录更新。建议先查看按投递待核实、登录/恢复受阻、执行异常排序，平台审核/纯策略单列观察；分类由 DAL 单一谓词提供，attention_kind 与更新时间排序随 URL 恢复，零项弱化。

## v0.4 已确认增补：YouTube 关键词采集

依据 `docs/specs/youtube-keyword-collection-v0.4.md`，2026-10-13 用户确认隔离开发。本段覆盖 v0.2 的“仅手动搜索、无主表准入”业务限制，保留既有控件、草稿、读取故障和 CAS 契约；生产开放仍需另行确认。

- 入口与频道白名单并列，保留 `/topic-candidates`。主要路径为新建采集规则 → 逐条启用定时采集 → 查看候选热度 → 受控达标准入 → 查看主队列任务。
- 规则新增语言偏好、近期范围、最低时长；使用现有 native select，系统 popup 的几何与键盘行为可接受。旧规则保持原值，新规则 1 天/30 秒起步且自动关闭。
- 页面访问和保存规则不触发搜索。定时运行归既有 queue-runner，页面只刷新状态；对话框编辑期间不以自动读取覆盖草稿。
- 搜索、定时能力、达标准入分别展示。启用准入必须展示将进入自动制作、审查与发布的后果；确认对话框初始焦点在取消，关闭也明确停止新准入及尚未开始的处理。
- 预算展示总搜索 20、自动最多 18、详情 40；计划每 4 小时顺延，维护、来源未核实、凭据错误、预算等待分开解释。热度分有统计与政策依据，不称 AI 质量分。
- 候选沿用 25 条分页。观察轮候、未知统计、已达标待准入、已入队、已存在和排除区分；入队不等于已经制作或发布。
- 验收所有者仍为 `tests/browser/test_topic_candidates_browser.py`，新增 K13/K14；共享首页、商品表单和手动选品回归继续纳入 `premium-ui.json`。

## 点赞率区间筛选

2026-10-14 用户确认指标为点赞数 ÷ 观看数，并授权直接上线。主列表复用 index.html 的筛选状态、URL 恢复和请求世代机制；DAL 在分页前按百分数闭区间筛选，总数使用同一谓词。默认不限制；启用时仅匹配观看数大于零、点赞数有效的数据，缺失不当作零。常用区间、原生双滑块和数字输入共享一组上下限；拖动仅预览，松手提交并回到第一页。上下限交叉钳制到另一端，清除筛选恢复不限；跨 Tab、分页和刷新保留。样式使用 dashboard.css 既有主题变量。验收见 test_dashboard_video_filters.py 和 test_dashboard_workspace.py。

## 封面来源 v1（2026-10-15 用户确认）
来源由 cover_provenance 契约提供，后台和 Telegram 使用相同来源、退化状态、哈希与版本。
封面缩略图下原生 details 展示来源并可键盘展开；不依赖颜色和 hover。桌面和移动端共用该组件。详情为原生 details 的非模态浮层，限制视口宽度和高度，Escape 关闭并恢复来源标签焦点。
投稿展示绑定的冻结文件，后续生成不改写历史；缺证据显示来源未核验。无重发、补通知或发布策略变更。

## 全局操作 header（2026-10-20 用户确认）
全局入口 owner 为 console_header.js / console_header.css，范围为根工作台五个分区。频道扫描由 web/console_header.py 单独运行 monitor_channels.py --bootstrap（批准频道最近5天），不启动 pipeline_manager；高互动素材沿用原刷新接口。服务器仍以 maintenance_admission 和维护准入为业务事实源；前端只读摘要不可作为解除维护的授权。

维护、运行状态未知时，扫描、扫码登录及完整流水线保持可见但禁用；菜单、外观和审计可查看。微信状态来自原会话状态接口，明确为本地验证记录，不因当前视频分页含 LOGIN_REQUIRED 推断全局会话。已有登录流程或同类扫描时禁止重复发起；请求前重新读取权限。完整流水线在应用原生 dialog 中说明扫描、评分、加工与发布后果，初始焦点在取消，Escape 取消并恢复焦点，不在打开确认时提交。扫描失败与任务结束分别展示，任务结束不证明全部来源采集成功。所有读取均不启动真实扫描、登录或平台验证。验收所有者为 test_console_header.py / test_console_header_browser.py。

微信登录入口的授权年龄与完整时间复用会话领域逻辑 relative_age / login_time_bj，经原只读状态接口返回；不以凭证文件修改时间或最近保活时间替代授权时间。缺记录、读取失败和未来时间异常保持明确，不推断授权有效。

## 视频预筛选（2026-10-21 页面已确认）

- 路由 `/video-prefilter` 与 `/api/video-prefilter`；导航 owner 为 console_navigation.js / dashboard_workspace.js，独立工作台 owner 为 video_prefilter.js / video_prefilter.css。
- 规则原生 select；字段使用原生 input/textarea，错误由 aria-describedby 关联。保存和检索分开，未保存草稿禁用检索；切换/离开使用原生 dialog，初始焦点继续编辑，Escape 保留草稿。失败或 CAS 冲突保留输入。
- 结果分类互斥，默认合格，播放量排序后每页25条；独立显示请求失败、历史快照与获取时间。查询和页面刷新无外部搜索副作用。运行中显示真实阶段及已获取数量，不伪造百分比。中断且未分类的数量单独显示，不冒充零结果。
- 页面、规则和决定均受既有本机会话、Origin、CSRF、维护状态及共享搜索锁/预算约束；不改变既有调度与准入。收藏、排除、撤销整理只写独立预筛选 DAL。资料30天到期清除，决定跨规则保留；历史过期不能收藏。
- 验证 owner：tests/unit/test_video_prefilter.py、tests/browser/test_video_prefilter_browser.py。复用控件与窗口滚动，不增加自定义列表组件或通知组件。
