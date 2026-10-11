# 五类商品配置页交付

作者：Codex。日期：2026-10-11。用户已确认范围。开发分支 `codex/wechat-product-config`，基于候选提交 `d77cb19`；生产仍为 `d81b2db`。

## 配置方式

新版首页点击“商品挂载”，进入 `/product-settings`：

1. 设置英语世界、华尔街、TED、AI、其他五类的首选和备选。
2. 设置全局默认。备选可空，最终候选不能空；选择“继承全局默认”时不另设备选。
3. 在“识别条件与其他类型细分”中维护来源频道 ID、旧财经/新闻细分以及总时限和尝试次数。
4. 从最近待发布任务选择视频，或填样例上下文，点击“预览选品”。预览展示类型、原因、完整商品身份和候选顺序，使用当前未保存表单。
5. 点击“保存配置”。成功后显示新版本；下次发布器开始选品才实际采用。已开始选品的任务继续使用原快照。

若多个窗口同时编辑，后保存的旧版本会被拒绝；草稿保留。重新载入会明确提示丢弃修改。网络/磁盘失败不会显示保存成功；结果不确定时重新载入核对。

**当前 `http://localhost:9100/product-settings` 实测 404，新页尚未部署。** 此文所述为开发版使用方式。没有重启生产进程，没有触发平台发表。下述测试中的 URL 属于拦截请求的隔离页面。

## 识别与默认配置

| 类型 | 稳定依据 | 初始商品 |
| --- | --- | --- |
| 英语世界短视频 | ENGLISH_WORLD_SHORT | 思考快与慢 |
| 华尔街事实炸弹 | 配置的完整频道 ID | 股市趋势技术分析 |
| TED 类 | TED / TEDx 配置频道 | 思考快与慢 |
| AI 相关资讯 | 显式主题 AI 或配置的频道 | 维特根斯坦 |
| 其他 | 未命中上述类型 | 财经/新闻细分优先；其余继承全局默认 |

优先顺序同表。显式指定商品优先于类型选品。AI 初始频道列表为空，不能把全部科技视频误归为 AI。普通任务可从 `<youtube_id>.info.json` 的 `product_topic: "AI"` 提供显式主题；不从标题猜测。来源频道优先使用任务账本，缺失时读取 info.json。分片分类优先读取该分片 `_category.txt`。

商品下拉列表来自 `config/wechat_products.json` 的已核实商品目录，不是实时抓取橱窗。新增书籍仍需用配置工具维护 ID、完整名称、核实日期和来源；五类分配无需改代码。原 schema v1 仍可由 CLI/uploader 读取；五类网页要求 v2。上线时不能仅覆盖 Python/HTML 而遗漏 v2 配置，也不能无审查覆盖运营者自行修改的策略。

## 工程入口

- `core/wechat_product_policy.py`：schema v1/v2、不可变策略、五类规则与候选校验。
- `utils/wechat_product_context.py`：预览与通用发布共享元数据读取和参数编码。
- `utils/wechat_product_config.py`：文件锁、原子保存、摘要冲突与采用记录。
- `web/product_settings.py`：独立路由，可在无后台任务的测试 App 中验收。
- `scripts/wechat_uploader.py`：接收内容类型/频道/主题/分类，仍执行实际 ID + 全名核对。
- `pipeline_manager.py` 与 `submit_english_world_review.py`：两个发布入口均传输选品上下文。

在开发 worktree 中运行离线预览（不启动平台浏览器）：

```sh
cd /private/tmp/vp-product-config-20261011
PYTHONPATH=src /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/.venv/bin/python scripts/wechat_product_config.py preview --content-type ENGLISH_WORLD_SHORT
PYTHONPATH=src /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/.venv/bin/python scripts/wechat_product_config.py preview --product-topic AI
```

`preview --video-id ID --slice-index 2` 读取具名本地元数据；显式参数优先。直接 uploader 可传 `--content-type` / `--product-topic` / `--product-category` / `--source-channel-id` / `--product-alias`。测试已截获 CLI 调用验证参数传输，没有运行平台上传。

## 验收证据

详见 `groups-ui-test-receipt.json`、`groups-ui-test-result.txt` 与 `product-settings-1280.png` / `product-settings-390.png`。

最终回归 **264 passed**，含商品配置页 8 项真实 Chromium 交互测试、17 项选品合成 DOM 测试及原控制台交互回归。

覆盖五类及重叠优先级、首选/备选/默认、不可达链拒绝、原子写入、并发冲突、在途快照、磁盘失败、实际采用记录、两个入口参数、发布恢复守卫；浏览器覆盖真实 API 保存/重载、预览、空列表、错误恢复、键盘、重复点击、过期响应与窄屏。

网页使用真实 Chromium，但 HTTP 全部转送隔离 TestClient，读写临时策略文件，没有连接生产或视频号平台。页面截图也属于隔离环境。

静态验证：`node --check`、`git diff --check`、DESIGN.md 官方 lint。Premium strict 审计保留 1 条旧页面告警：`index.html` 的删除按钮通过 JS 动态绑定，工具只识别内联 onclick；该原有功能有浏览器测试覆盖。新增页无静态告警。审计完整原始输出在 `groups-ui-static-audit.json`，不宣称全仓静态审计零告警。

扩大回归时修正两个既有测试的过时选择器：原 `.status-cell > .badge` 与 HEAD 中已存在的 `.desktop-only-status` 包装不符。仅更改测试定位，未改状态呈现业务。

## 上线仍需完成

本候选依赖前一轮严格商品实际身份回读：当前真实平台表单是否提供可核实 ID 尚无新证据。如果只显示书名，适配器会阻止提交。必须先完成允许环境中的平台接口验收，再选择发布空闲窗口合入 main、采用 v2 配置和加载新版控制台。

此前宿主对真实平台浏览器操作的拒绝仍适用，不使用 CLI/CDP/其他浏览器或委派绕过。现阶段停留于代码、隔离测试及 Git 交付；没有宣称运行采用、正式测试发布、后台挂载或播放页购买完成。
