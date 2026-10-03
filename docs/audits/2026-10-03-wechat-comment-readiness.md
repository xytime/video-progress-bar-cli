# 视频号首评目标卡片为零：诊断与修复

日期：2026-10-03。执行与验收：Codex。

## 目标与边界

恢复 Hochul 视频（YouTube ID `SfNypZIb0H4`）的评论管理页定位。保留唯一原生目标、完整发布文案核验、提交前请求守门、持久化提交意图、共享会话锁和作者评论回读；不允许第一张卡片或未经内容验证的 API 索引兜底。

投稿原生 ID：`export/UzFfBgAAxO-lfHlhXUmlk8zT4DCaL-2Komfbo4GS1TJIRtQfqg`。

## 现场证据与原因

- 互动账本 ID 221 为 `FAILED`，已有五次尝试，`submit_intent_at` 为空。此前失败截图仍在首页加载画面；URL 曾进入评论路由，但实际卡片未渲染。旧版用固定 2.5 / 1 / 3.5 秒等待，不能保证首页初始化和评论页加载完成。
- 只读校准在首页“最近视频”与唯一可见互动管理菜单就绪后导航，成功读到十张评论卡片，其中目标完整发布文案唯一匹配一张。
- 同一作品在投稿和评论场景使用不同的 `exportId`。旧监听器读取任意 `post/post_list`，可能混入首页/内容管理场景 ID；必须仅使用评论场景快照。
- 实测评论列表路径为 `/micro/interaction/cgi-bin/mmfinderassistant-bin/post/post_list`，成功 HTTP 状态为 201。卡片出现时响应正文也可能尚未解析完，需要同时等待有效列表快照。

## 修复

`BrowserCommenter` 改为有界等待首页正向控件、唯一可见菜单、精确评论路由、实际可见卡片和已解析评论场景列表。仅接受官方 HTTPS 源与精确列表路径，兼容 HTTP 200/201。导航前清理快照，避免父菜单自动导航时丢弃新快照；未知 schema、加载未完成、登录回跳均停止并落盘证据。

保留既有全文唯一绑定和所有提交保护，并在收据中增加列表、文案和目标卡片数量，便于区分页面未就绪与目标缺失。

## 验收

隔离测试命令：

```sh
.venv/bin/python scripts/run_isolated_tests.py --browser -- -q \
  tests/unit/test_wechat_interaction_browser.py \
  tests/unit/test_wechat_interaction_cli.py \
  tests/unit/test_wechat_interaction_state.py \
  tests/unit/test_wechat_interaction_dispatch.py \
  tests/browser/test_wechat_interaction_browser.py
```

结果：**81 passed，48.08 秒**。沙箱收据与日志：`/private/tmp/video-pytest-28esogxx/`。新增回归覆盖初始化覆写路由、隐藏同名菜单、父菜单自动导航、延迟渲染、HTTP 201、未知 schema、登录回跳、非官方源和跨场景 ID 污染。

修复后真实适配器 `verify_only=True` 验收：

- 十张可见卡片、十个评论场景作品 ID；目标卡片数 **1**。
- 使用 `unique_exact_published_description` 绑定评论场景 ID：`export/UzFfBgAAxNGkdDpUKEmlk8zT4DCaZKs-TJguejpjnSjnqGCZvw`。
- 目标详情与同作品评论列表读取成功，未发现待发作者评论。只读返回 `FAILED: verify-only 未找到目标作者评论` 表示评论尚不存在；页面定位已通过。
- 证据：`output/wechat_evidence/diagnostics/SfNypZIb0H4/attempt-20261003T083524.436758Z-2343eb3b224b44a8bb5b0408b8250abc/receipt.json` 与 `final.png`。

截至上述验收，没有打开写评论界面、填写或提交评论，没有重置原失败记录，没有发送 Telegram。作品账本仍是 `SUBMITTED_BOUND`，本次未验证公众可见性。补发须另有明确发送授权，并以平台评论 ID、作者全文回读和账本终态作为完成证据。
