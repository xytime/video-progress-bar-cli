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

2026-10-30 回归修复：`console_navigation.js` 为当前分组维护 `is-active-group`，复用既有子导航折叠样式。首页主行与分集的手动执行统一调用既有 `ManualVideoExecution.execute`；冷却须人工确认，取消恢复按钮及焦点，失败恢复按钮，未知响应不自动重试。所有者为 `src/web/static/js/manual_video_execution.js` 和 `src/web/templates/index.html`，验证由 `tests/browser/test_manual_video_cooldown.py`、`tests/unit/test_dashboard_interactions.py` 及 `tests/browser/test_secondary_reply_settings_browser.py` 负责。Browser plugin unavailable，使用项目 OS 隔离 Playwright；不改变发布资格、会话锁或未知投稿保护。


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
素材预览修复（2026-10-25）：待筛选、近期高互动列表中，既无封面版本也无投稿绑定的原视频，在本地封面缺失时显示 YouTube 原图并明确标注仅供素材浏览。原图不可用时显示占位；已有本地封面优先，分集及投稿封面不以原图补位。此预览不写入生成来源或投稿证据。
全列表自查补齐（2026-10-25）：主行与展开分集复用同一封面组件，分集只读取自身编号对应的封面和来源。原图补位覆盖各列表中没有投稿尝试、投稿关联及封面版本的加工前后待办任务；任一平台已进入提交、审核、结果不明或发布状态均不补位。历史记录、已有版本及冻结投稿封面缺失显示「暂无预览图」「生成封面缺失」或「投稿封面缺失」，保留原来源标识，不借用父集或原图。

## 全局操作 header（2026-10-20 用户确认）

2026-10-25 已确认的刷新提示修复：高互动采集回执按本次实际入库计算新增数，显示进入「近期高互动」以及当前频道、入库时间仍可能隐藏结果。零新增区分已有记录、入库保护、发布时间超窗、观看量不足、元数据不全、空搜索、失败与超时；部分失败和维护中断不冒充成功。`web/high_likes_refresh.py` 拥有持久化回执与任务互斥，`console_header.js` 统一呈现两处入口的结果；重载只读恢复，当前筛选不变。验收：`test_high_likes_refresh.py` 与 `test_console_header_browser.py` 的隔离 API、SQLite、Chromium 证据。
全局入口 owner 为 console_header.js / console_header.css，范围为根工作台五个分区。频道扫描由 web/console_header.py 单独运行 monitor_channels.py --bootstrap（批准频道最近5天），不启动 pipeline_manager；高互动素材沿用原刷新接口。服务器仍以 maintenance_admission 和维护准入为业务事实源；前端只读摘要不可作为解除维护的授权。

维护、运行状态未知时，扫描、扫码登录及完整流水线保持可见但禁用；菜单、外观和审计可查看。微信状态来自原会话状态接口，明确为本地验证记录，不因当前视频分页含 LOGIN_REQUIRED 推断全局会话。已有登录流程或同类扫描时禁止重复发起；请求前重新读取权限。完整流水线在应用原生 dialog 中说明扫描、评分、加工与发布后果，初始焦点在取消，Escape 取消并恢复焦点，不在打开确认时提交。扫描失败与任务结束分别展示，任务结束不证明全部来源采集成功。所有读取均不启动真实扫描、登录或平台验证。验收所有者为 test_console_header.py / test_console_header_browser.py。

微信登录入口的授权年龄与完整时间复用会话领域逻辑 relative_age / login_time_bj，经原只读状态接口返回；不以凭证文件修改时间或最近保活时间替代授权时间。缺记录、读取失败和未来时间异常保持明确，不推断授权有效。

## 视频预筛选（2026-10-21 页面已确认）

- 路由 `/video-prefilter` 与 `/api/video-prefilter`；导航 owner 为 console_navigation.js / dashboard_workspace.js，独立工作台 owner 为 video_prefilter.js / video_prefilter.css。
- 规则原生 select；字段使用原生 input/textarea，错误由 aria-describedby 关联。保存和检索分开，未保存草稿禁用检索；切换/离开使用原生 dialog，初始焦点继续编辑，Escape 保留草稿。失败或 CAS 冲突保留输入。
- 结果分类互斥，默认合格，播放量排序后每页25条；独立显示请求失败、历史快照与获取时间。查询和页面刷新无外部搜索副作用。运行中显示真实阶段及已获取数量，不伪造百分比。中断且未分类的数量单独显示，不冒充零结果。
- 页面、规则和决定均受既有本机会话、Origin、CSRF、维护状态及共享搜索锁/预算约束；不改变既有调度与准入。收藏、排除、撤销整理只写独立预筛选 DAL。资料30天到期清除，决定跨规则保留；历史过期不能收藏。
- 验证 owner：tests/unit/test_video_prefilter.py、tests/browser/test_video_prefilter_browser.py。复用控件与窗口滚动，不增加自定义列表组件或通知组件。

2026-10-21 已确认预筛选修订：配置摘要与检索入口常驻；原生 details 展开编辑，保存后收起，失败保留草稿。草稿状态在摘要显示并禁用检索，编辑折叠不等于丢弃草稿；校验失败自动展开定位字段。历史折叠，选择历史不发起外部检索。结论使用“指标合格”，明确不代表题材适合或发布批准。


## 原始发布新鲜度（2026-10-22 用户确认）

所有主视频列表、视频预筛选结果和关键词候选池使用独立行内“原始发布”字段；分集显示“原视频发布”，继承父视频的来源时间，不使用分集创建或平台发布时间。无需新增表格列，手机自然换行，绝对来源与入库时间保持辅助层级。

共享计算、DOM 与每分钟本地刷新由 `src/web/static/js/source_publication.js` 维护；来源精确时间必须含时区，只有日期时标“约”（UTC 日期估算），缺失和无效/未来时间使用中性色并显示未知/异常。入库、任务更新和平台发布时间不应用此分级。

唯一色板 owner 为 `src/web/static/css/dashboard.css` 的 `--source-age-*`：不足 1 天 #15803D、1–2 天 #4D7C0F、2–3 天 #A16207、3–7 天 #B45309、7–10 天 #9A3412、10 天以上 #6B4F43，区间左闭右开。搭配浅色底、细边框和加粗时间；暗/亮主题保持同一识别顺序，高对比主题加强边框。验证由 `tests/browser/test_source_publication_browser.py` 覆盖六档边界、刷新、全部主列表及分集、候选与预筛选的实际 DOM、三主题对比度、手机溢出和截图。

## 平台题材复核恢复（2026-10-23 用户确认）

依据 `docs/specs/censorship-review-recovery-2026-10-23.md`。既有复核弹窗使用原生 dialog，继承 dashboard 主题、局部 live region 与 Escape/焦点恢复；保留 P0 双确认。平台题材原输入不可核实时禁用批准，提供独立“重新审查”。重新审查只追加完整输入快照与当前规则审计，任务仍暂停；明确批准后才恢复既有管线。批准绑定当前显示的审计编号、输入和规则版本，服务器再次核对当前素材；错误就地显示、重复提交禁用、关闭后旧响应作废。读取故障不显示旧命中，超时结果不明须重新打开核实。验证由 `tests/unit/test_social_unrest_review.py` 与 `tests/browser/test_social_unrest_review_flow.py` 负责。

## 重试与人工复核（2026-10-23 用户确认修复）

当前错误分类 owner 为 `core/censorship_state.py`，API 返回 `censorship_state`，主行与分集共用 `censorshipBadge`。历史命中独立展示；P0 批准须有原台账。只有 FAILED 且当前错误属于审查时显示复核入口；后端再次核验，不能凭历史标签放行。技术错误显示实际失败摘要，普通重试沿用原批准边界与投稿防重保护。

字幕阶段由当前任务的近期原子心跳提供；显示复用文案、转录、翻译及正在执行的定位/渲染。过期心跳与终态不显示旧进度。沿用现有主题、自然换行与文字状态，按钮及弹窗 owner 不变。验证：`tests/browser/test_retry_resume_display.py`、`tests/unit/test_retry_review_state.py`。Browser plugin not available；使用项目隔离 Playwright。

## 发布恢复与调度（2026-10-23 用户确认）

业务依据为 docs/specs/publishing-recovery-console-2026-10-23.md；既有 /wechat-cooldown-settings 保持兼容。账号状态、固定预览与恢复操作的唯一事实源是 PublishingRecoveryService 和 publishing_recovery DAL，页面不推断发表成功。

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Table Selection | publishing_recovery.js 原生 checkbox 集合 | 固定 preview_id / 行 revision | 本页 / 全部匹配；历史估算默认不选；跨页保留 | test_publishing_recovery_browser.py |
| Select/Listbox / Date | native select / 有标签的 typed ISO 北京时间输入 | 服务端时间范围校验 | 今天 / 24h / 自定义，最长30天 | test_publishing_recovery_browser.py |
| Form / CRUD | publishing_recovery.py 路由 + 领域服务 | 固定目标与 CAS / operation_id | 单独重置 / 续跑 / 组合；取消未启动项 | test_publishing_recovery.py |
| Feedback / Dialog | 既有页面 live region / native dialog | 服务端响应与操作账本 | 首焦取消，Escape恢复焦点，超时核对原操作 | test_publishing_recovery_browser.py |
| Navigation / Scrollbar | console_navigation.js / dashboard.css | DESIGN.md / URL | 主列表失败和待发布入口，自然滚动 | test_publishing_recovery_browser.py |

预览结果分页20条，操作历史分页10条；窗口、预览页和当前批次保存在URL。全部匹配仅选择可恢复且非估算项，估算项允许显式逐条选择。改变筛选后重新预览才替换旧结果并清空选择；读取失败保留旧结果并标记过期，禁用执行。正常轮询不覆盖选择或打开的确认。恢复操作显示全部选中身份、账号、实际作用与剩余保护，不能称已解冻或已发布。提交超时保留同一操作ID和请求，先核对原操作，可幂等重放同一请求，禁止创建第二操作。批次展示等待原因、下一时间或未知、逐项结果与取消未启动项；不清理真实锁、不触发平台结果回查。

## 运行配置中心（2026-10-24）

业务与权限来源：`docs/specs/runtime-configuration-center.md`。复用既有本机真实对端/会话/CSRF、原生select/dialog及页面status反馈；本页是有版本的策略编辑变体，不复用商品选择业务逻辑。

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox | native select | runtime_configuration.html | 组/方式筛选，接受系统popup几何 | tests/browser/test_runtime_configuration_browser.py |
| Form | src/web/static/js/runtime_configuration.js | 服务端字段归属/严格Schema | 草稿、字段错误、结构化影响预览、CAS冲突 | tests/unit/test_runtime_configuration.py |
| Scrollbar | src/web/static/css/dashboard.css | DESIGN.md | 自然页面滚动、dialog内部滚动 | tests/browser/test_runtime_configuration_browser.py |
| Toast | feedback / apply-feedback / state-feedback | 页面status与live region | 读状态失败不清除保存冲突或草稿 | tests/browser/test_runtime_configuration_browser.py |
| CRUD | src/web/runtime_configuration.py | config/runtime_policy.py | 应用与回滚生成新版本，不删除事实 | tests/unit/test_runtime_configuration.py |

搜索/组/管理方式/页码/视图保存在URL，中文输入完成后过滤；每页20项。预览期间改草稿使旧预览失效。网络结果不确定不自动重提交，保留operation_id和草稿供核对；并发版本冲突不覆盖。离开或重新载入的丢弃确认初始焦点在继续编辑，Escape保留草稿并恢复焦点。版本、加载、在途和离线定时执行者分别展示，不假报全部生效。开启观众回复需要核对既有时段和内容/审批规则；安全旁路不可编辑。

## 视频主列表筛选与标签数量

2026-10-25 用户确认：标签数量复用列表筛选谓词。频道、入库时间、搜索和点赞率跨标签保留；分数、异常类型、状态及透视等场景条件按既有切换规则清除，标签预示切换后的数量。当前标签数量与列表总数一致。“清除筛选”回到第一页、全部频道及全部入库时间，并清除场景条件；空列表统一提示“当前筛选下无匹配记录”。验证由 `tests/unit/test_dashboard_video_filters.py` 和 `tests/browser/test_dashboard_workspace.py` 覆盖，查询与筛选不改变业务状态。


## 英语世界只读管理台（2026-10-25）

依据：已验收 Superdesign 草稿 29124163-8ad4-4859-8556-cb5a797bfda0 v4；当前用户授权开发与部署。任务/投稿事实来自 EnglishConsoleDAL，自动早期失败来自固定目录的运行回执；不把失败通知 ACCEPTED 当成视频发表。没有创建、重试、批准、提交或平台查询接口。成片存在、投稿授权、平台受理、审核和历史公开回读分别呈现。超过24小时未更新的在途记录标当前待确认。

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox / Date | native select / input date | english_world_console.html | 系统 popup 几何与日期选择 | test_english_world_console_browser.py |
| Scrollbar | dashboard.css / console_workspace.css | DESIGN.md | 本页列表、详情分别滚动；手机自然滚动 | test_english_world_console_browser.py |
| Navigation / Dialog / Feedback | console_navigation.js / native dialog / 页面 status | UX-CONTRACT.md | Esc关闭、入口焦点恢复、失败保留旧记录 | test_english_world_console_browser.py |
| Read-only list | english_world_console.js + EnglishConsole | 本地数据库与固定运行回执 | AND筛选、每页20、URL恢复 | test_english_world_console.py |

统计明确限定最近1000个人工任务、1000成片和200次运行，按已知review/manifest关联去重；计数不随筛选变化，待处理与已结束可重叠。关键词忽略大小写和首尾空格，与状态/来源方式/北京创建日期同时生效；IME结束后300ms读取，清空即时，过期请求取消，空结果清除旧详情。刷新保留仍匹配的选择；HTTP故障保留旧数据并标当前未知。报告仅固定七类，本地文件限output目录、拒绝越界和外部链接，使用文件内容hash核实关联；缺失或不匹配不采纳通过，报告不能修改原质量门禁。

## 英语世界可处理工作台 v10（2026-10-25 用户确认）

此段取代上方 v4 的只读交互范围；既有 `console_navigation.js`、本机会话、同源校验和 `runtime_local_session` + `X-Runtime-CSRF` 继续有效。数据 API 为 `/api/english-world/workbench`、`/task`、固定类型 `/media?task=…&kind=video|cover|submission` 与 `/actions`。服务端资格是动作唯一依据；每次动作带当前 revision、UUID operation_id 与用户输入。提交中禁止连击，冲突保留输入并重读资格，读取失败清除旧详情和动作资格，超时保留同一 operation_id 核验，禁止生成第二操作。

页面为今日运行摘要、待我处理/全部任务/运行记录、全宽任务表和任务原生 dialog 抽屉。搜索标题/来源/ID、状态、触发和创建日期范围使用 AND 组合；提交的筛选、页码、视图、历史折叠和选中任务写入 URL，支持后退、刷新和深链接。超过7天的未解决任务单独折叠并显示服务端总数。抽屉只有一个滚动内容面板，底部动作固定；阶段显示真实状态与时间，不按无心跳状态声称正在执行或估算进度。

研究创建、候选选择、制作确认、审核批准、暂缓、具名失败步骤安全续做和人工登记结果均须原生确认框显示对象/版本/后果，初始焦点为取消。候选确认与制作确认分开。resume 的资格由服务端根据原输入身份、预算、未提交、维护和租约重新验证；当前执行器不支持时不得伪造可执行。`UNCERTAIN` 只允许查看提交证据及按当前身份登记人工结果，不提供一键重发。登记 public 必须提交服务器可验证的绑定原生 ID 与固定截图证据引用，登记只更新核验记录，不调用投稿器。

成片只用受限 video 媒体通道；封面和提交证据按固定 kind 读取。报告要呈现状态、生成时间、身份核验、问题与建议；不能把文件名或历史关联当作质量通过。任务切换及详情读取失败清空上一任务的证据与动作权限。

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select / Date | 原生 select、`input[type=date]` | `english_world_console.html` | 接受系统 popup 几何；日期按北京时间 | `tests/browser/test_english_world_console_browser.py` |
| Navigation / Scrollbar | `console_navigation.js` / `dashboard.css` | 本合同 / DESIGN.md | 页面自然滚动、表格自身滚动、抽屉单滚动区 | 同上 |
| Dialog / Feedback | 原生 dialog、页面 live region | 服务端版本与资格 | 取消首焦点、Escape关闭并恢复入口焦点 | 同上 |
| List / Detail / Actions | `english_world_console.js` | 工作台 v1 API 与服务端动作回执 | URL恢复、分页20、revision+operation_id | 同上 |

## 授权与状态回执闭环（2026-10-25）

- 范围：现有授权反馈、AGY 封面认证状态、视频号人工确认提示的小修复；不改变审批条件或投稿策略。
- 所有者：`operation_receipts.js/css` 复用 native Dialog、原生 button 与项目 Toast；复核提交仍由既有 `confirmBypass` 单一拥有。
- 保存：POST 返回审计编号后 GET 再读回同一任务/分集的回执；持续显示结果，关闭或刷新后仍可从平台详情读取。HTTP 拒绝和响应丢失分别提示，核实按钮只读，不重复 POST。
- 认证：READY/AUTH_REQUIRED 仅五分钟内有效；无记录、过期或检查故障为 UNKNOWN。显式核实不运行模型、不弹 OAuth；恢复登录后可更新状态。
- 投稿：只有同次同成片提交意图及点击返回证据，才显示“等待人工确认”；UNCERTAIN、平台原生 ID 和防重复门禁保持。证据缺失继续显示结果待核实。
- 验收：隔离 Chromium + FastAPI/SQLite 覆盖成功、403、响应丢失、认证时效、移动端和键盘；生产 HTTPS 核实既有授权回执、真实认证重查及投稿提示，不新增投稿。

## 成片待投资格（2026-10-26 用户授权）

沿用 dashboard.css 主题、原生表格、行内状态与 console-notice。成片完成、当前可领取、资格阻塞、运行等待和提交结果待核实分别说明；现有发布记录入口拥有结果核实，不提供重投按钮。资格由 db/publication_eligibility.py 与执行器共同读取，页面不重建规则。分数线由 API 提供；TED50分仅改变TED/TEDx，点赞率、人工许可、历史隔离与提交防重保持。旧冷却文字不是当前状态。验证归 tests/unit/test_publication_eligibility.py 与 tests/browser/test_ready_eligibility_browser.py。
