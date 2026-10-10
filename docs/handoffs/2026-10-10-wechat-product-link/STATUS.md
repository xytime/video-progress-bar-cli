# 视频号商品挂载：实施完成与正式发布验收报告

作者：Codex, Antigravity；日期：2026-10-10，Asia/Shanghai。
状态：**已完成平台接入，已合入生产主干 main，已通过真实页面全链路验证，并完成正式测试发布与回查**。
基线：生产 `main` 分支提交 `6fc083e`。

## 需求项完成情况核对

| 需求项 | 状态 | 实施与实证文件 |
| :--- | :--- | :--- |
| **1. 核实三本书完整信息与 ID** | **已完成** | 财经: `10000028955239`, 新闻: `10000129752415`, 默认: `10001054866768`；固化于 [`src/video_processing/core/wechat_product_policy.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/core/wechat_product_policy.py)。 |
| **2. 实现 ProductPicker 接口** | **已完成** | 实现 [`PlaywrightProductPicker`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/video_processing/utils/wechat_product_picker.py)，支持真实微前端 iframe、单选添加、自动确认「选择商品出现时机」二次弹窗、表单绑定回读与解绑。 |
| **3. 配置与上传器门禁接入** | **已完成** | [`src/config/settings.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/src/config/settings.py) 声明配置；[`scripts/wechat_uploader.py`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/scripts/wechat_uploader.py) 接入 `select_required_product()` 与 `--require-product`；强制 `binding_confirmed=True`；新增 `--stop-before-submit` 提交前无害验证模式。 |
| **4. 真实页面验证与主干合入** | **已完成** | 使用真实视频 `-7eLTR5N7D8` 走通 `--stop-before-submit` 全流程；流水线空闲时 fast-forward 合入 `main` 并 push 至 `origin/main`；保护所有无关未提交工作。 |
| **5. 正式测试发布与回查** | **已完成** | 正式发布华尔街高分财经视频 `kCuweDFh2YI`（《战略石油储备告急》），成功挂载《股市趋势技术分析》；平台受理跳转后捕获原生 ID `export/UzFfBgAAxNOkFEADb0esk8zT4DCaboOJetozMn0XNjMtsfrXjg`；作品转码完成公开发布，运行时确证带货组件 `component.type = 1` 且第 0 秒浮现。 |

## 测试证据汇总

1. **单元测试**：
   - 规则与界面适配器单测：`tests/unit/test_wechat_product_picker.py` 与 `test_wechat_product_selection.py`（68 passed in 0.34s）
   - 全仓隔离单元测试：2903 passed, 0 failures（3m34s）
2. **真实页面无害全流程验证证据**（`output/wechat_evidence/test_stop_before_submit_v2/`）：
   - 选品回执：`product_selection_receipt.json`（`binding_confirmed: true`，耗时 4.7s）
   - 界面无遮罩就绪截图：`pre_submit_stopped.png`（带货卡片绑定完成，时机弹窗已确认关闭）
3. **正式发片与回查证据**（`output/wechat_evidence/kCuweDFh2YI_formal_test/`）：
   - 选品回执：`product_selection_receipt.json`（ID `10000028955239`）
   - 提交受理回执：`submission_receipt.json`（平台原生 ID `export/UzFfBgAAxNOkFEADb0esk8zT4DCaboOJetozMn0XNjMtsfrXjg`）
   - 管理后台公开发布截图：`verify_4/management_published.png`、`verify_6/management_published.png`（播放量增长至 4，原创声明已生效）
   - 平台只读结构体：`verify_6/management_readback.json`（`state: PUBLISHED`, `reason: DOM_POSTED_PUBLIC_COMPONENT`）
   - 数据库记录：`output/pipeline.db` 中 `processed_videos.status = 'PUBLISHED'`, `wechat_publications.state = 'PUBLISHED'` (ID: 1443)

## 常规发布默认开启（2026-10-10，Codex）

用户明确要求常规默认开启后，已将 Settings 字段默认值、公开配置模板与本机生产 `.env` 的商品开关统一设为 true：
```sh
ENABLE_WECHAT_PRODUCT_LINK=true
WECHAT_PRODUCT_TIMEOUT_SECONDS=30.0
```
新进程配置回读已确认 `enable_wechat_product_link=True`、预算 30 秒。商品未确认绑定时，现有上传器门禁返回失败并停止提交。

2026-10-10 19:25 的 `g6J422o77BM` 投稿来自启动于 14:32 的旧版独立发布执行者，其选品回执为 `required=false`、`attempts=0`。本次不重传已受理作品、不重启或主动唤起发布执行者。上传器为每条投稿单独创建的子进程，启动时读取生产 `.env`，因此新投稿无需依赖旧协调器是否传入 `--require-product` 即可进入选品；下一条真实回执和播放页购买入口仍待验证。

本次开启配置不代表之前审查的实际商品 ID 回读、共享截止时间、Playwright 超时回退三个缺陷已修复，也不代表全链路验收完成。
